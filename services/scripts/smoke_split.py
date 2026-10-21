"""Regression for split decision, committed assignment and generated acknowledgement."""
import argparse
import json
import sys
import httpx
from shared.config import settings,ROOT
from shared.db import J,tx
from scripts.smoke_flow import Sess
from agent.app.split_reply import assignment_text,split_violations

P={'T1':'COLLEAGUE','T3':'CANDIDATE','faq_candidate':3}
DEFAULT={'T1':'CANDIDATE','T3':'COLLEAGUE','faq_candidate':3}
S=settings()
checks=[]


def check(name,ok):
    checks.append({'name':name,'passed':bool(ok)})
    print(('PASS ' if ok else 'FAIL ')+name,flush=True)


def propose(x,p):
    r=x.c.post(f'/sessions/{x.sid}/split',json={'proposal':p});r.raise_for_status()
    check('split request creates response run',bool(r.json()['run_id']))
    return x.wait(x.idle)


def confirm(x,s,p):
    check('card confirms exactly accepted proposal',s['split']['confirmed'] and s['split']['proposal']==p)
    check('board matches confirmed owners',x.task(s,'T1')['owner']==p['T1'] and x.task(s,'T3')['owner']==p['T3'] and f"지원자 {p['faq_candidate']}개" in x.task(s,'T2')['note'])
    last=x.last(s,'COLLEAGUE');reply=last['content']
    run=x.c.get(f"/runs/{last['source_run_id']}").json()
    check('confirmation passes validation without fallback',not run['error'])
    check('reply matches all confirmed owners and FAQ counts',not split_violations(reply,{'run_type':'split','text':'','ctx':{'state':{'split':s['split']}}}))


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--mode',required=True);args=ap.parse_args()
    B=S.app_origin+'/api/v1'
    adm=httpx.Client(base_url=B,headers={'Origin':S.app_origin},timeout=30)
    adm.headers['X-CSRF-Token']=adm.post('/auth/login',json={'email':S.seed_admin_email,'password':S.seed_admin_password}).json()['csrf_token']
    check('health mode',httpx.get(S.gateway_internal_url+'/api/v1/health').json()['mode']==args.mode)
    x=Sess(B,adm,'split-rehearsal-'+args.mode)
    check('initial provisional card is unconfirmed',not x.snap()['split']['confirmed'])
    s=propose(x,P);confirm(x,s,P)
    _,s=x.say('감사합니다!')
    reply=x.last(s,'COLLEAGUE')['content']
    check('does not reopen or recap split without candidate request',not split_violations(reply,{'run_type':'message','text':'감사합니다!','ctx':{'state':{'split':s['split']}}}) and assignment_text(P) not in reply)
    y=Sess(B,adm,'split-pushback-'+args.mode)
    imbalanced={'T1':'COLLEAGUE','T3':'COLLEAGUE','faq_candidate':1}
    s=propose(y,imbalanced)
    check('imbalanced proposal remains negotiating, never confirmed',not s['split']['confirmed'] and s['split']['proposal']==imbalanced)
    run=y.c.get(f"/runs/{y.last(s,'COLLEAGUE')['source_run_id']}").json()
    check('pushback passes validation without fallback',not run['error'])
    check('pushback is one question without acceptance',not split_violations(y.last(s,'COLLEAGUE')['content'],{'run_type':'split','text':'','ctx':{'state':{'split':s['split']}}}))
    s=propose(y,P);confirm(y,s,P)
    # Exercise default fallback from a persisted three-round negotiation.
    z=Sess(B,adm,'split-default-'+args.mode)
    with tx(S.psycopg_dsn) as c:
        c.execute("UPDATE sessions SET scenario_state=jsonb_set(scenario_state,'{split,rounds}','3') WHERE id=%s",(z.sid,))
    s=propose(z,P);confirm(z,s,DEFAULT)
    check('fourth proposal defaults rather than confirming submitted proposal',s['split']['rounds']==4 and s['split']['proposal']!=P)
    for session in (x,y,z):
        session.c.post(f'/sessions/{session.sid}/submit',json={'summary':''}).raise_for_status()
    print(f"{sum(c['passed'] for c in checks)}/{len(checks)} split checks passed",flush=True)
    (ROOT/'evals/results'/f'split-rehearsal-{args.mode}.json').write_text(json.dumps({'mode':args.mode,'checks':checks},ensure_ascii=False,indent=2)+'\n')
    return 0 if all(c['passed'] for c in checks) else 1

if __name__=='__main__':sys.exit(main())

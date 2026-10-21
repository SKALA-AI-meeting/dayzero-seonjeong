"""Candidate review approval survives agent restart; local state contains no cookies/tokens."""
import json
import sys
import time
from http.cookies import SimpleCookie
import httpx
from fastapi import Response
from shared.config import ROOT, settings
from shared.db import all_,one,tx
from gateway.app.auth import issue_cookie,COOKIE
from scripts.smoke_flow import Sess,save
S=settings();B=S.app_origin+'/api/v1';O={'Origin':S.app_origin}
STATE=ROOT/'evidence/.restart_resume_state.local.json'


def prepare():
    adm=httpx.Client(base_url=B,headers=O,timeout=30)
    adm.headers['X-CSRF-Token']=adm.post('/auth/login',json={'email':S.seed_admin_email,'password':S.seed_admin_password}).json()['csrf_token']
    x=Sess(B,adm,'smoke-restart-review')
    save(x,'T1','친구 초대하면 포인트 쏴드림!')
    _,s=x.say('제가 작성한 T1 안내문 검토 부탁드립니다!')
    assert s['approvals'],'review approval required'
    a=s['approvals'][0]
    with tx(S.psycopg_dsn) as c:
        r=one(c,'SELECT thread_id FROM runs WHERE id=%s',(a['run_id'],))
    STATE.write_text(json.dumps({'sid':x.sid,'approval_id':a['id'],'run_id':a['run_id'],'thread_id':r['thread_id'],
                                'version':x.art(s,'T1')['version']}))
    print('PREPARED suggest_candidate_edit approval; only non-secret identifiers persisted')


def decide():
    st=json.loads(STATE.read_text());sid=st['sid']
    with tx(S.psycopg_dsn) as c:
        session=one(c,'SELECT participant_id,company_id FROM sessions WHERE id=%s',(sid,))
    response=Response()
    csrf=issue_cookie(response,sub=str(session['participant_id']),role='CANDIDATE',company_id=str(session['company_id']),session_id=sid)
    cookie=SimpleCookie();cookie.load(response.headers['set-cookie'])
    client=httpx.Client(base_url=B,headers={**O,'X-CSRF-Token':csrf},cookies={COOKIE:cookie[COOKIE].value},timeout=30)
    s=client.get(f'/sessions/{sid}').json()
    restored=any(a['id']==st['approval_id'] for a in s['approvals'])
    statuses=[client.post(f"/sessions/{sid}/approvals/{st['approval_id']}/decision",json={'decision':'APPROVE'}).status_code for _ in range(2)]
    for _ in range(90):
        s=client.get(f'/sessions/{sid}').json()
        if not s['active_run']:break
        time.sleep(1)
    with tx(S.psycopg_dsn) as c:
        revs=all_(c,"SELECT r.id FROM artifact_revisions r JOIN artifacts a ON a.id=r.artifact_id WHERE r.session_id=%s AND a.key='T1' AND r.actor='COLLEAGUE'",(sid,))
        receipts=one(c,'SELECT count(*) AS n FROM mutation_receipts WHERE approval_id=%s',(st['approval_id'],))['n']
        r=one(c,'SELECT status,thread_id FROM runs WHERE id=%s',(st['run_id'],))
    body=next(a for a in s['artifacts'] if a['key']=='T1')
    ok=restored and statuses==[202,202] and '쏴드림' not in body['body'] and len(revs)==receipts==1 and r['status']=='SUCCEEDED' and r['thread_id']==st['thread_id']
    print('RESTART_RESUME', 'PASS' if ok else 'FAIL', {'restored':restored,'statuses':statuses,'revisions':len(revs),'receipts':receipts,'run':r['status']})
    return ok

if __name__=='__main__':sys.exit(0 if (prepare() if sys.argv[1]=='prepare' else decide()) in (None,True) else 1)

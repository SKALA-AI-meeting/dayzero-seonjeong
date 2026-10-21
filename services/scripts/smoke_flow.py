"""Real-time scenario regression using persisted development clock shifts."""
from __future__ import annotations

import argparse
import re
import sys
import time
import uuid
from urllib.parse import parse_qs, urlparse

import httpx

from shared.config import settings

S = settings()
res: list[tuple[str, bool, str]] = []
PUSHBACK = "제가 하는 게 맞을까요"


def check(n, ok, d=""):
    res.append((n, bool(ok), d)); print(("PASS " if ok else "FAIL ") + n + (f" — {d}" if d else ""), flush=True)


class Sess:
    def __init__(self, base: str, adm: httpx.Client, alias: str):
        self.adm = adm
        url = adm.post("/invites", json={"alias": alias}).json()["invite_url"]
        self.c = httpx.Client(base_url=base, headers={"Origin": S.app_origin}, timeout=30)
        e = self.c.post("/auth/exchange", json={"token": parse_qs(urlparse(url).query)["token"][0]}).json()
        self.sid = e["session_id"]
        self.c.headers["X-CSRF-Token"] = e["csrf_token"]
        self.c.post(f"/sessions/{self.sid}/start", json={"consent": True})

    def snap(self) -> dict:
        return self.c.get(f"/sessions/{self.sid}").json()

    def wait(self, pred, timeout=60) -> dict:
        t = time.time()
        while time.time() - t < timeout:
            s = self.snap()
            if s.get("session", {}).get("status") == "SUBMITTED" or pred(s):
                return s
            time.sleep(0.7)
        return self.snap()

    def idle(self, s: dict) -> bool:
        return not s["active_run"]

    def say(self, text: str, to: str = "COLLEAGUE") -> tuple[httpx.Response, dict]:
        before = len(self.snap()["messages"])
        r = self.c.post(f"/sessions/{self.sid}/messages", json={"client_message_id": uuid.uuid4().hex, "channel": "TEAM",
                                                                 "content": text, "to": to})
        s = self.wait(lambda s: (not s["active_run"] or s["active_run"]["status"] == "WAITING_APPROVAL") and len(s["messages"]) > before)
        return r, s

    def last(self, s: dict, actor: str | None = None) -> dict:
        ms = [m for m in s["messages"] if actor is None or m["actor"] == actor]
        return ms[-1] if ms else {"content": "", "meta": {}}

    def approve(self, decision: str = "APPROVE") -> tuple[httpx.Response, dict]:
        s = self.wait(lambda s: s["approvals"])
        a = s["approvals"][0]
        r = self.c.post(f"/sessions/{self.sid}/approvals/{a['id']}/decision", json={"decision": decision})
        return r, a

    def task(self, s: dict, key: str) -> dict:
        return next(t for t in s["tasks"] if t["key"] == key)

    def art(self, s: dict, key: str) -> dict:
        return next(a for a in s["artifacts"] if a["key"] == key)


def set_clock(x: Sess, seconds: int):
    """Test-only persisted clock shift; no turn changes, same engine as wall time."""
    from shared.db import tx
    with tx(S.psycopg_dsn) as c:
        c.execute("UPDATE sessions SET clock_offset_seconds=%s-EXTRACT(EPOCH FROM (now()-started_at))::int WHERE id=%s", (seconds,x.sid))


def db_rows(sql: str, args: tuple):
    from shared.db import tx, all_
    with tx(S.psycopg_dsn) as c:
        return all_(c,sql,args)


def save(x: Sess, key: str, body: str):
    a=x.art(x.snap(),key)
    r=x.c.patch(f"/sessions/{x.sid}/artifacts/{key}",json={"base_version":a["version"],"body":body})
    r.raise_for_status()
    return r.json()


def advance(x: Sess):
    r=x.adm.post(f"/sessions/{x.sid}/demo/advance")
    r.raise_for_status()
    return x.snap()


def new_session(base,adm,alias):
    x=Sess(base,adm,alias)
    # The provisional board starts with default owners; confirm negotiated default split.
    x.c.post(f"/sessions/{x.sid}/split",json={"proposal":{"T1":"CANDIDATE","T3":"COLLEAGUE","faq_candidate":3}}).raise_for_status()
    x.wait(x.idle)
    return x


def main() -> int:
    ap=argparse.ArgumentParser();ap.add_argument("--mode",default="fixture");ap.add_argument("--base",default=S.app_origin)
    args=ap.parse_args(); B=args.base+"/api/v1"
    adm=httpx.Client(base_url=B,headers={"Origin":S.app_origin},timeout=30)
    adm.headers["X-CSRF-Token"]=adm.post("/auth/login",json={"email":S.seed_admin_email,"password":S.seed_admin_password}).json()["csrf_token"]
    check("health mode",httpx.get(S.gateway_internal_url+"/api/v1/health").json()["mode"]==args.mode)
    x=new_session(B,adm,"seoyoon-rehearsal-"+args.mode)
    for i in range(30):save(x,"T1",f"검증 저장 {i}")
    check("30 saves never advance events before open_at",x.snap()["events"]==["E0"])
    rehearsal=["서윤님 저희 이벤트가 초대 1명당 3000P인거 같아요 확인 부탁드립니다!!",
               "리워드 일정표에는 5000포인트로 되어있어서요!",
               "서윤님 제가 아까 말한게 그거예요!! 서윤님이 잘못 작성하셨더라구요!"]
    for i,msg in enumerate(rehearsal):
        if i==2:advance(x)
        r,s=x.say(msg)
        check(f"rehearsal message {i+1}",r.status_code==202 and not s.get("active_run"))
        if i==0:
            check("T3 5000P → 3000P immediately without approval",'초대 1명당 3,000P' in x.art(s,'T3')['body'] and not s['approvals'])
            check("chat describes concrete edit",bool(re.search(r'3,?000|수정|고쳤',x.last(s,'COLLEAGUE')['content'])))
    ms=[m['content'] for m in s['messages'] if m['actor']=='COLLEAGUE' and m['meta'].get('kind')!='SCENARIO_EVENT']
    check("no repeated clarification",sum(bool(re.search(r'어떤 부분|어느 부분',m)) for m in ms)<=1)
    before=x.art(s,'T2')['body'];_,s=x.say('동일 결제수단 제외가 잘못된 것 같아요')
    check("wrong criticism leaves document unchanged",x.art(s,'T2')['body']==before and not s['approvals'])
    check("wrong criticism explains brief",'브리프' in x.last(s,'COLLEAGUE')['content'])
    check("fact correction is not blame",not db_rows("SELECT code FROM observations WHERE session_id=%s AND code='CO-1'",(x.sid,)))
    save(x,'T1','친구 초대하면 포인트 쏴드림!')
    _,s=x.say('제가 작성한 T1 안내문 검토 부탁드립니다!')
    check("review actually reads document",bool(db_rows("SELECT id FROM tool_calls WHERE session_id=%s AND tool_name='read_artifact' AND outcome='ok'",(x.sid,))))
    check("review creates approval card",bool(s['approvals']) and s['approvals'][0]['tool_name']=='suggest_candidate_edit')
    if s['approvals']:
        x.approve();s=x.wait(x.idle)
        check("approved review edit applied",'쏴드림' not in x.art(s,'T1')['body'])
    check("CO+7 review request recorded",bool(db_rows("SELECT id FROM observations WHERE session_id=%s AND code='CO+7'",(x.sid,))))
    # Clock gates, action trigger, forced trigger and absolute E4/end.
    y=new_session(B,adm,'clock-'+args.mode)
    set_clock(y,599);save(y,'T1','open gate')
    check("open_at gate",'E1' not in y.snap()['events'])
    set_clock(y,601);save(y,'T1','next candidate action')
    check("next action after open fires E1",'E1' in y.snap()['events'])
    occ=db_rows("SELECT occurrence_mode FROM event_occurrences WHERE session_id=%s AND event_id='E1'",(y.sid,))
    check("event occurrence records on_action",occ and occ[0]['occurrence_mode']=='on_action')
    set_clock(y,1561);s=y.wait(lambda s:'E2' in s['events'],timeout=10)
    check("no action force_at fires E2",'E2' in s['events'])
    occ=db_rows("SELECT occurrence_mode,elapsed_seconds FROM event_occurrences WHERE session_id=%s AND event_id='E2'",(y.sid,))
    check("forced mode and real elapsed seconds",occ and occ[0]['occurrence_mode']=='forced' and occ[0]['elapsed_seconds']>=1560)
    set_clock(y,3000);s=y.wait(lambda s:'E4' in s['events'],timeout=10)
    check("E4 at 50 minutes",'E4' in s['events'] and any(a['key']=='T4' for a in s['artifacts']))
    y.say('아직 안내문은 진행 중이고 서윤님이 초안을 작성했어요.','MANAGER')
    _,s=y.say('서윤님 초안이고 제가 전부 한 것은 아니에요.','MANAGER')
    check("E4 report does not submit",s['session']['status']=='ACTIVE')
    set_clock(y,3601)
    for _ in range(20):
        rows=db_rows("SELECT status FROM sessions WHERE id=%s",(y.sid,))
        if rows[0]['status']=='SUBMITTED':break
        time.sleep(.5)
    check("60 minutes auto submits saved state",rows[0]['status']=='SUBMITTED')
    # E3 return both paths, with actual candidate revision during absence.
    for changed in (False,True):
        z=new_session(B,adm,'return-'+str(changed)+'-'+args.mode)
        while 'E3' not in z.snap()['events']:advance(z)
        if changed:
            a=z.art(z.snap(),'T3');save(z,'T3',a['body'].replace('5,000P','3,000P'))
        prior=len([m for m in z.snap()['messages'] if m['actor']=='COLLEAGUE'])
        z.say('서윤님 지금 계신가요?');_,off=z.say('서윤님 답장 부탁드려요!')
        replies=[m for m in off['messages'] if m['actor']=='COLLEAGUE' and m['meta'].get('kind')!='SCENARIO_EVENT']
        check(f"offline reply limit ({changed})",len([m for m in off['messages'] if m['actor']=='COLLEAGUE'])-prior==1) # includes split response + one offline response
        while 'E3B' not in z.snap()['events']:advance(z)
        msg=x.last(z.snap(),'COLLEAGUE')['content']
        check('return notices changed document' if changed else 'return asks if unchanged',
              ('바뀐' in msg and '3,000P' in msg) if changed else '혹시 제 표 보셨어요?' in msg)
        z.c.post(f"/sessions/{z.sid}/submit",json={"summary":""}).raise_for_status()
    # Every generated promise must have a matching successful tool in the same run.
    from agent.app.graph import action_violations
    violations=[]
    for m in db_rows("SELECT content,source_run_id FROM messages WHERE session_id=%s AND actor='COLLEAGUE' AND COALESCE(meta->>'kind','') NOT IN ('SCENARIO_EVENT','SCENARIO_BRANCH')",(x.sid,)):
        tools=db_rows("SELECT tool_name,outcome FROM tool_calls WHERE run_id=%s",(m['source_run_id'],))
        done=[{'tool':r['tool_name'],'payload':{'ok':r['outcome']=='ok'}} for r in tools]
        violations+=action_violations(m['content'],done)
    check("promise/action audit: zero violations",not violations,str(len(violations)))
    x.c.post(f"/sessions/{x.sid}/submit",json={"summary":""}).raise_for_status()
    for _ in range(90):
        r=adm.get(f"/reports/{x.sid}")
        if r.status_code==200 and r.json()['status']=='READY':break
        time.sleep(1)
    check("report ready",r.status_code==200 and r.json()['status']=='READY')
    report=r.json().get('body') or {}
    check("timeline includes elapsed time and occurrence mode",bool(report.get('timeline')) and all(isinstance(e['elapsed_seconds'],int) and e.get('occurrence_mode') in ('forced','on_action') for e in report['timeline']))
    from shared.config import ROOT
    output=ROOT/'evidence'/f'seoyoon-{args.mode}.json'
    output.write_text(__import__('json').dumps({'mode':args.mode,'checks':[{'name':n,'passed':ok,'detail':d} for n,ok,d in res]},ensure_ascii=False,indent=2)+'\n')
    print(f"{sum(ok for _,ok,_ in res)}/{len(res)} checks passed",flush=True)
    return 0 if all(ok for _,ok,_ in res) else 1


if __name__=='__main__':sys.exit(main())

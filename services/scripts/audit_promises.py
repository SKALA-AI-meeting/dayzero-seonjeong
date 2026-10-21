"""Audit generated colleague replies against successful tools executed before each reply."""
import json
from shared.config import ROOT,settings
from shared.db import all_,one,tx
from agent.app.graph import action_violations
S=settings()
with tx(S.psycopg_dsn) as c:
    start=one(c,"SELECT max(s.created_at) AS at FROM sessions s JOIN participants p ON p.session_id=s.id WHERE p.alias='seoyoon-rehearsal-live'")['at']
    messages=all_(c,"""SELECT m.id,m.content,m.source_run_id,m.created_at FROM messages m
                        JOIN sessions s ON s.id=m.session_id WHERE s.created_at >= %s AND m.actor='COLLEAGUE'
                        AND m.source_run_id IS NOT NULL AND COALESCE(m.meta->>'kind','')<>'SCENARIO_EVENT'""",(start,))
    violations=[]
    for m in messages:
        calls=all_(c,'SELECT tool_name,outcome FROM tool_calls WHERE run_id=%s AND created_at<=%s',(m['source_run_id'],m['created_at']))
        problems=action_violations(m['content'],[{'tool':t['tool_name'],'payload':{'ok':t['outcome']=='ok'}} for t in calls])
        if problems:violations.append({'message_id':str(m['id']),'problems':problems})
    c.execute("UPDATE jobs j SET status='DONE' FROM runs r WHERE j.run_id=r.id AND j.status='QUEUED' AND r.status IN ('SUCCEEDED','CANCELLED','FAILED')")
result={'generated_replies_audited':len(messages),'violations':violations,'scope':'latest live regression and subsequent isolated sessions; tools must finish before reply'}
(ROOT/'evidence/seoyoon-promises.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
print('PROMISE_AUDIT', 'PASS' if messages and not violations else 'FAIL', 'replies=',len(messages),'violations=',len(violations))
raise SystemExit(0 if messages and not violations else 1)

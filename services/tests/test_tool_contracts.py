"""Approval safety, capability boundaries and brief contradiction against the real gateway."""
import httpx
import pytest
from shared.config import settings
from shared.db import J, one, tx
from gateway.app.domain import insert_message
from scripts.smoke_mcp import client, payload
from test_m0_auth import candidate, new_invite
S=settings();BASE=S.gateway_internal_url+'/internal/v1';HEAD={'x-service-token':S.internal_service_secret}


def request_run(text='제가 작성한 T1 안내문 검토 부탁드립니다!'):
    c,identity=candidate(new_invite('tool-contract-test'))
    sid=identity['session_id'];c.headers['X-CSRF-Token']=identity['csrf_token']
    c.post(S.gateway_internal_url+f'/api/v1/sessions/{sid}/start',json={'consent':True}).raise_for_status()
    with tx(S.psycopg_dsn) as db:
        m=insert_message(db,sid,'CANDIDATE',text)
        r=one(db,"""INSERT INTO runs(session_id,thread_id,kind,status,source_message_id,input,policy_version,prompt_version,trace_id)
                     VALUES (%s,gen_random_uuid()::text,'TEAM','RUNNING',%s,%s,'test','test','test') RETURNING id""",
              (sid,m['id'],J({'type':'message','content':text})))
    return c,sid,str(r['id'])


def cap(rid,approval=None,audience='business-mcp'):
    r=httpx.post(BASE+f'/runs/{rid}/capability',headers=HEAD,json={'audience':audience,'approval_id':approval});r.raise_for_status()
    return r.json()['token']


def tool(rid,name,args,approval=None):
    return httpx.post(BASE+'/mcp/'+name,headers={**HEAD,'x-capability':cap(rid,approval)},json={'args':args}).json()


def test_review_requires_actual_read_and_candidate_ownership():
    _,sid,rid=request_run()
    args={'artifact_key':'T1','base_version':1,'content':'친구 초대 안내입니다.','targets':['REVIEW']}
    with tx(S.psycopg_dsn) as db:
        from gateway.app.internal.routes import check_scope
        from gateway.app.business import ToolError
        run=one(db,'SELECT * FROM runs WHERE id=%s',(rid,))
        with pytest.raises(ToolError):check_scope(db,sid,run,'suggest_candidate_edit',args)
    assert tool(rid,'read_artifact',{'artifact_key':'T1'})['ok']
    r=httpx.post(BASE+f'/runs/{rid}/proposal',headers=HEAD,json={'interrupt_id':'review','tool_name':'suggest_candidate_edit','args':args,'base_versions':{'artifact_version':1}})
    assert r.status_code==200
    aid=r.json()['approval_id']
    assert httpx.post(BASE+f'/runs/{rid}/proposal',headers=HEAD,json={'interrupt_id':'review','tool_name':'suggest_candidate_edit','args':args,'base_versions':{'artifact_version':1}}).json()['approval_id']==aid
    assert not tool(rid,'suggest_candidate_edit',args)['ok']
    with tx(S.psycopg_dsn) as db:db.execute("UPDATE approvals SET status='APPROVED' WHERE id=%s",(aid,))
    tampered={**args,'content':'임의 변경'}
    assert tool(rid,'suggest_candidate_edit',tampered,aid)['error']['code']=='OUT_OF_SCOPE'
    p=tool(rid,'suggest_candidate_edit',args,aid)
    assert p['ok']
    assert tool(rid,'suggest_candidate_edit',args,aid)==p # mutation receipt replay
    with tx(S.psycopg_dsn) as db:
        assert one(db,'SELECT count(*) AS n FROM mutation_receipts WHERE approval_id=%s',(aid,))['n']==1


def test_stale_approval_cannot_overwrite_newer_candidate_edit():
    c,sid,rid=request_run()
    args={'artifact_key':'T1','base_version':1,'content':'안내드립니다.','targets':['REVIEW']}
    assert tool(rid,'read_artifact',{'artifact_key':'T1'})['ok']
    aid=httpx.post(BASE+f'/runs/{rid}/proposal',headers=HEAD,json={'interrupt_id':'stale','tool_name':'suggest_candidate_edit','args':args,'base_versions':{'artifact_version':1}}).json()['approval_id']
    c.patch(S.gateway_internal_url+f'/api/v1/sessions/{sid}/artifacts/T1',json={'base_version':1,'body':'지원자 최신 문장'}).raise_for_status()
    with tx(S.psycopg_dsn) as db:db.execute("UPDATE approvals SET status='APPROVED' WHERE id=%s",(aid,))
    assert tool(rid,'suggest_candidate_edit',args,aid)['error']['code']=='VERSION_CONFLICT'
    with tx(S.psycopg_dsn) as db:
        assert one(db,"SELECT body FROM artifacts WHERE session_id=%s AND key='T1'",(sid,))['body']=='지원자 최신 문장'


def test_wrong_criticism_and_unassigned_edits_are_blocked():
    _,sid,rid=request_run('동일 결제수단 제외가 잘못된 것 같아요')
    p=tool(rid,'edit_own_artifact',{'artifact_key':'T3','base_version':1,'content':'임의의 변경','targets':['PE-2']})
    assert p['error']['code']=='CONTRADICTS_BRIEF'
    assert not tool(rid,'read_artifact',{'artifact_key':'T1'})['ok']


def test_brief_capability_excludes_ordinary_conversation():
    import asyncio
    _,_,rid=request_run('안녕하세요!')
    async def check():
        async with client(S.rag_mcp_url,cap(rid,audience='rag-mcp')) as rag:
            p=payload(await rag.call_tool('search_docs',{'query':'금액','document_ids':['brief']}))
            assert not p['ok'] and p['error']['code']=='FORBIDDEN'
            with pytest.raises(Exception):await rag.read_resource('doc://sc-a/brief')
    asyncio.run(check())

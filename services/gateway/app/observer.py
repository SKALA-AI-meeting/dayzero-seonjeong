"""Immediate rule observations for persisted candidate document and board actions."""
from shared.db import all_, one
from shared.scenario import scenario, targets_in
from .engine import observe, state


def observe_revision(c, s: dict, revision: dict, key: str, before: str, after: str):
    sid = str(s['id'])
    event = state(s).get('active_event')
    ref = {'kind':'revision','id':str(revision['id'])}
    for pe in scenario()['planted_errors']:
        if pe['wrong'] in before and pe['wrong'] not in after:
            if pe['id'] != 'PE-4':
                observe(c,sid,'PL+3',event,ref,f"{pe['id']} 오류 수정",subject=pe['id'])
            asked = one(c,"SELECT 1 FROM observations WHERE session_id=%s AND code='CO+5' AND subject=%s",(sid,pe['id']))
            if not asked and key in ('T2','T3'):
                observe(c,sid,'CO·N1',event,ref,'요청 없이 서윤 초안을 직접 수정',subject=pe['id'])
    reviews = all_(c,"SELECT before_after FROM approvals WHERE session_id=%s AND tool_name='suggest_candidate_edit'",(sid,))
    for r in reviews:
        suggestion = r['before_after']
        if suggestion.get('artifact_key')==key and suggestion.get('after') == after:
            observe(c,sid,'CO·N2',event,ref,'서윤 검토 의견을 반영함',subject=key)

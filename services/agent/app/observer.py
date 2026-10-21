"""Observation is independent of dialogue generation and never supplies dialogue text."""
from __future__ import annotations
import json
import re
from shared.config import settings
from shared.scenario import codebook

SEMANTIC_CODES = {'CO+1','CO+2','CO+3','CO+4','CO+5','CO+6','CO-1','CO-2','CO-3','AD+1','AD+2','RS+1','RS+3'}
BLAME = re.compile(r'대충|왜\s*이렇게|제대로\s*안\s*하|한심|정신\s*차')


def observe_message(state: dict, llm) -> tuple[list[dict], dict | None]:
    """Closed codebook judgement, using messages and actual board/doc changes as evidence."""
    text, ctx = state['text'], state['ctx']
    ref = {'kind':'message','id':str(ctx['run']['source_message_id'])}
    existing = list(state.get('observes') or [])
    if settings().llm_mode != 'live':
        # Deterministic fixture evidence; fact corrections are never blame.
        if not BLAME.search(text):
            existing = [o for o in existing if not (o['code']=='CO-1' and '응답' not in o.get('note',''))]
        return existing, (state.get('effects') or {}).get('commitment')
    from langchain_core.messages import SystemMessage, HumanMessage
    definitions = {k:v['definition'] for k,v in codebook().items() if k in SEMANTIC_CODES}
    prompt = ('지원자 행동의 의미만 관찰한다. 대화 응답 생성과 독립된 관찰자다. JSON '
              '{"codes":[{"code":"...","note":"근거 설명"}],"commitment":null 또는 "실제 약속 문장"}. '
              '주어진 코드북에서 명백한 코드만 선택한다. 추측하여 없는 행동을 만들지 않는다. '
              'CO-1 비난은 대충/왜 이렇게/제대로 안 하처럼 탓하거나 깎아내리는 표현만이다. '
              '잘못 작성하셨더라구요처럼 사실을 짚는 말은 비난이 아니다. '
              '코드는 점수가 아니다. CO+5는 구체적인 정정 요청, CO+6은 실제 반문 뒤 이유를 들어 유지한 요청만. '
              '약속은 지원자가 한 실제 행동·시간 약속만 등록한다.')
    ai = llm.invoke([SystemMessage(prompt),HumanMessage(json.dumps({
        'codebook':definitions,'event':state.get('event_id'), 'state':ctx['state'],
        'messages':[{'actor':m['actor'],'content':m['content']} for m in ctx['messages']][-6:],
        'candidate_message':text,'board':ctx['tasks'],'revisions':ctx['revisions'],
    },ensure_ascii=False))])
    result = json.loads(ai.content)
    observations = [o for o in existing if o['code'] not in SEMANTIC_CODES]
    for o in result.get('codes',[]):
        code = o.get('code')
        if code not in SEMANTIC_CODES or (code=='CO-1' and not BLAME.search(text)):
            continue
        subjects = state.get('targets') or [None] if code=='CO+5' else [None]
        for subject in subjects:
            observations.append({'code':code,'event_id':state.get('event_id'),'evidence':ref,
                                 'subject':subject,'note':'[LLM 추정] '+str(o.get('note',''))[:400]})
    commitment = {'text':result['commitment']} if result.get('commitment') else None
    return observations, commitment

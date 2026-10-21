"""Ground split replies in the committed negotiation decision and task ownership."""
from __future__ import annotations
import re

WHO = {'COLLEAGUE':'한서윤','CANDIDATE':'지원자'}


def assignment_text(proposal: dict) -> str:
    return (f"T1 안내문 {WHO[proposal['T1']]}, T3 리워드 표 {WHO[proposal['T3']]}, "
            f"FAQ 지원자 {proposal['faq_candidate']}개·한서윤 {5-proposal['faq_candidate']}개")


def split_fallback(split: dict) -> str:
    if split['confirmed']:
        return f"넵, 확정된 담당은 {assignment_text(split['proposal'])}예요."
    return '앗, 분량을 조금 조정해서 다시 제안해 주실 수 있을까요?'


def split_context(ctx: dict) -> dict:
    split = ctx['state'].get('split') or {}
    return {'status':'확정' if split.get('confirmed') else '임시(미확정)',
            'proposal':split.get('proposal'), 'tasks':ctx.get('tasks',[])}


def split_prompt_context(state: dict) -> dict:
    split = state['ctx']['state']['split']
    return {'시스템 결정':{'ACCEPT':'수락하고 확정함','PUSHBACK':'미확정 상태에서 분량 조정 질문 1회','DEFAULT':'3라운드 초과로 기본 분업 확정함'}[state['split_decision']['decision']],
            '담당 상태':'확정' if split['confirmed'] else '임시(미확정)',
            '현재 담당표':assignment_text(split['proposal']),
            '응답 기준':split_fallback(split)}


def candidate_reopens(text: str) -> bool:
    return bool(re.search(r'분업|분담|담당|배분|나누|나눠|맡',text) and
                re.search(r'바꾸|바꿀|변경|다시|재조정|조정|대신|재분배',text))


def ownership_claims(text: str, *, allocation: bool = False) -> list[tuple[str, str, int | None]]:
    """Parse explicit ownership assertions; a title alone is never an ownership claim."""
    subject = re.compile(r'제가|저는|한서윤(?:님)?(?:은|이|가)?|서윤(?:님)?(?:은|이|가)?|지원자(?:님)?(?:은|이|가)?|동료분(?:이|은)?')
    matches = list(subject.finditer(text))
    claims = []
    for index, match in enumerate(matches):
        clause = text[match.end():matches[index+1].start() if index+1<len(matches) else len(text)]
        clause = re.split(r'[,.!?。]',clause)[0]
        if not allocation and not re.search(r'맡|담당|책임|분담',clause):
            continue
        actor = 'CANDIDATE' if re.match(r'지원자|동료분',match[0]) else 'COLLEAGUE'
        if re.search(r'T1|안내문',clause,re.I):claims.append((actor,'T1',None))
        if re.search(r'T3|리워드\s*(?:[·ㆍ/]?\s*일정)?\s*표|일정표',clause,re.I):claims.append((actor,'T3',None))
        if re.search(r'FAQ|T2',clause,re.I):
            counts = re.findall(r'(\d+)\s*개',clause)
            claims.append((actor,'T2',int(counts[-1]) if counts else None))
    # Also handle object-first Korean assertions: "T3는 제가 담당해요".
    person = r'(제가|저는|저|한서윤(?:님)?|서윤(?:님)?|지원자(?:님)?|동료분)'
    for key,alias in {'T1':r'T1(?:\s*안내문)?|안내문', 'T3':r'T3(?:\s*리워드\s*표)?|리워드\s*(?:[·ㆍ/]?\s*일정)?\s*표|일정표'}.items():
        for m in re.finditer(r'(?:'+alias+r')\s*(?:은|는|을|를|담당(?:은)?|의\s*담당(?:은)?|:)?\s*'+person,text,re.I):
            actor = 'CANDIDATE' if re.match(r'지원자|동료분',m[1]) else 'COLLEAGUE'
            claims.append((actor,key,None))
    for faq in re.finditer(r'FAQ[^.!?。\n]{0,140}',text,re.I):
        for m in re.finditer(person+r'\s*(?:이|은|는|가)?\s*(\d+)\s*개',faq[0]):
            actor = 'CANDIDATE' if re.match(r'지원자|동료분',m[1]) else 'COLLEAGUE'
            claims.append((actor,'T2',int(m[2])))
    return claims


def split_violations(text: str, state: dict) -> list[str]:
    split = state['ctx']['state'].get('split') or {}
    if not split.get('proposal'):
        return []
    confirmed, proposal = split.get('confirmed',False), split['proposal']
    is_run = state.get('run_type') == 'split'
    problems = []
    if re.search(r"\b(?:COLLEAGUE|CANDIDATE|SPLIT|UNASSIGNED)\b",text):
        problems.append("internal_owner_enum_in_reply")
    expected = assignment_text(proposal)
    extra = text.replace(expected,'')
    claims = ownership_claims(text, allocation=is_run)
    if is_run:
        if confirmed:
            required = {(proposal['T1'],'T1',None),(proposal['T3'],'T3',None),
                        ('CANDIDATE','T2',proposal['faq_candidate']),('COLLEAGUE','T2',5-proposal['faq_candidate'])}
            if not required.issubset(set(claims)):
                problems.append('confirmed_split_assignment_missing')
        else:
            positive = re.sub(r'미확정|확정(?:하지|되지)\s*않[가-힣]*|확정\s*전', '', text)
            if re.search(r'확정|수락|동의|그대로\s*(가|진행)',positive) or not re.search(r'\?|까요',text):
                problems.append('pushback_must_remain_unconfirmed')
    reopens = candidate_reopens(state.get('text',''))
    if confirmed and not reopens:
        if expected in text and not is_run and not re.search(r'분업|분담|담당|맡|누가',state.get('text','')):
            problems.append('unsolicited_split_recap')
        if re.search(r'맡|분업|분담|나누|나눠|배분',extra) and re.search(r'어떨|할까요|바꾸|다시|조정|제안',extra):
            problems.append('unsolicited_renegotiation')
        for actor,key,count in claims:
            expected_count = proposal['faq_candidate'] if actor=='CANDIDATE' else 5-proposal['faq_candidate']
            if (key=='T2' and count is not None and count!=expected_count) or (key!='T2' and proposal[key]!=actor):
                problems.append('ownership_differs_from_confirmed_split')
        if claims and not is_run and not re.search(r'분업|분담|담당|맡|누가',state.get('text','')):
            problems.append('unsolicited_split_recap')
    if not confirmed and claims and not re.search(r'임시|미확정|아직.{0,8}확정|제안|이대로라면',text):
        problems.append('provisional_ownership_claimed_as_final')
    return list(dict.fromkeys(problems))

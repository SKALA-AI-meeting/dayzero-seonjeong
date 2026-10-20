# smoke_flow --mode live, gpt-4o-mini (2026-10-20 12:44 KST)

LangSmith 키 미설정 → trace는 로컬 로그만(AT-17 LangSmith 부분 NOT_RUN).
```
PASS health mode 일치 — {'status': 'ok', 'db': 'up', 'agent': 'up', 'mcp': {'business': 'up', 'rag': 'up'}, 'mode': 'live'}
PASS AT-03 202
PASS AT-03 동료 근거 응답 — 현재 모바일 신규 고객의 장바구니 이탈 지표는 다음과 같습니다. 장바구니 세션 수는 4,500회, 체크아웃 세션 수는 950회, 주문 수는 550회로, 장바구니 이탈률은 87.78%, 체크아웃 이탈률은 42.11%입니다. 이탈률이 높아 문제를 해결할 필요가 있습니다.
PASS AT-03 SSE RUN_STARTED→TOOL_START/END→COLLEAGUE_MESSAGE→DONE — MANAGER_EVENT,CANDIDATE_MESSAGE,RUN_STARTED,TOOL_START,TOOL_END,TOOL_START,TOOL_END,COLLEAGUE_MESSAGE,DONE
PASS AT-04 위임 제안 카드 — {'title': 'evidence 조사: device=mobile, visitor=new 세그먼트 지표와 관련 문의·문서', 'filters': {'device': 'mobile', 'visitor': 'new'}, 'allowed_tools': ['get_funnel_metrics', 'get_support_cases', 'search_docs'], 'target_section': 'evidence', 'source_message_id': 'b52c291a-9108-441e-b040-98431103306f'}
PASS AT-04 delegation 201 + 같은 key 멱등 — 201
PASS AT-05 승인 대기 카드
PASS AT-05 승인 전 문서 무변경
PASS AT-05 거절 후 무변경
PASS REVISE → 새 run — {"task":{"id":"50268ddf-b712-4351-b5e6-3dc943d999fd","title":"evidence 조사: device=mobile, visitor=new 세그먼트 지표와 관련 문의·문서"
PASS AT-05 승인 후 revision 1개, 중복 결정 무해 — v1→v2
PASS AT-05 evidence에 동료 요약 반영
PASS 다른 결정 재전송 409 — {"error":{"code":"APPROVAL_STALE","message":"이미 다른 결정이 저장되었습니다","retryable":fals
PASS AT-07 제출 202 — {"session_status":"SUBMITTED","report_id":"fe8f3903-2608-4e80-bc45-82d606e4cd02"}
PASS AT-12 제출 후 쓰기 차단 — {"error":{"code":"SESSION_SUBMITTED","message":"제출된 세션은 변경할 수 없습니다","retryable":
PASS AT-07 리포트 READY — READY
PASS AT-07 score/rank/pass/fail 필드 없음
PASS AT-11 지원자는 리포트 조회 불가
PASS 디브리핑 200 — []
결과: 19/19 PASS (session b04e6659-edf5-4447-b908-d18d30e77b3a)
```

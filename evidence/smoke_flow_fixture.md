# smoke_flow --mode fixture (2026-10-20 12:43 KST)
```
PASS health mode 일치 — {'status': 'ok', 'db': 'up', 'agent': 'up', 'mcp': {'business': 'up', 'rag': 'up'}, 'mode': 'fixture'}
PASS AT-03 202
PASS AT-03 동료 근거 응답 — [지표 조회] current 기간 · 범위 device=mobile, visitor=new · cart_value별 (cart-data-v1)
PASS AT-03 SSE RUN_STARTED→TOOL_START/END→COLLEAGUE_MESSAGE→DONE — MANAGER_EVENT,CANDIDATE_MESSAGE,RUN_STARTED,TOOL_START,TOOL_END,TOOL_START,TOOL_END,TOOL_START,TOOL_END,TOOL_START,TOOL_END,COLLEAGUE_MESSAGE,DONE
PASS AT-04 위임 제안 카드 — {'title': 'evidence 조사: device=mobile, visitor=new 세그먼트 지표와 관련 문의·문서', 'filters': {'device': 'mobile', 'visitor': 'new'}, 'allowed_tools': ['get_funnel_metrics', 'get_support_cases', 'search_docs'], 'target_section': 'evidence', 'source_message_id': '0d480dd7-d454-4bcd-b378-7e7f64f24c61'}
PASS AT-04 delegation 201 + 같은 key 멱등 — 201
PASS AT-05 승인 대기 카드
PASS AT-05 승인 전 문서 무변경
PASS AT-05 거절 후 무변경
PASS REVISE → 새 run — {"task":{"id":"92ca5680-249c-4684-baba-a90b7246bc0e","title":"evidence 조사: device=mobile, visitor=new 세그먼트 지표와 관련 문의·문서"
PASS AT-05 승인 후 revision 1개, 중복 결정 무해 — v1→v2
PASS AT-05 evidence에 동료 요약 반영
PASS 다른 결정 재전송 409 — {"error":{"code":"APPROVAL_STALE","message":"이미 다른 결정이 저장되었습니다","retryable":fals
PASS AT-07 제출 202 — {"session_status":"SUBMITTED","report_id":"23ca94ec-493c-4b9e-b6a7-f278bf8e5213"}
PASS AT-12 제출 후 쓰기 차단 — {"error":{"code":"SESSION_SUBMITTED","message":"제출된 세션은 변경할 수 없습니다","retryable":
PASS AT-07 리포트 READY — READY
PASS AT-07 score/rank/pass/fail 필드 없음
PASS AT-11 지원자는 리포트 조회 불가
PASS 디브리핑 200 — []
결과: 19/19 PASS (session ec04ea23-7aed-470c-8169-89c5c2b29255)
```

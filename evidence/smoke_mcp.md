# smoke_mcp 실행 결과 (2026-10-20 12:08 KST)

```
PASS business tools/list 5개 — get_funnel_metrics,get_session_context,get_support_cases,patch_artifact_section,update_task_status
PASS 변경 도구 destructiveHint=true/readOnlyHint=false
PASS 조회 도구 readOnlyHint=true/destructiveHint=false
PASS AT-02 current/all 10000/3000/2200, 이탈 0.78 — {'segment': 'all', 'cart_sessions': 10000, 'checkout_sessions': 3000, 'orders': 2200, 'abandonment_rate': 0.78, 'checkout_abandonment_rate': 0.266667}
PASS AT-02 current/mobile × visitor 중첩 필터 — {'new': (4500, 950, 550), 'returning': (2500, 800, 640)}
PASS AT-02 baseline/device 검산 — {'desktop': (3000, 1400, 1320), 'mobile': (7000, 2100, 1680)}
PASS AT-02 current/device 검산 — {'desktop': (3000, 1250, 1010), 'mobile': (7000, 1750, 1190)}
PASS AT-02 current/visitor 검산 — {'new': (6000, 1560, 960), 'returning': (4000, 1440, 1240)}
PASS AT-02 current/cart_value 검산 — {'high': (4200, 1470, 1120), 'low': (5800, 1530, 1080)}
PASS AT-02 baseline 결제 후 이탈 14.2857%
PASS 잘못된 enum → 오류(프로토콜 검증 또는 INVALID_ARGUMENT)
PASS get_support_cases shipping 2건(VOC-01,06)
PASS tags 4개 → INVALID_ARGUMENT
PASS 승인 없는 변경 도구 → 권한 오류(isError) — FORBIDDEN
PASS capability 없음 → FORBIDDEN
PASS rag tools/list = search_docs
PASS rag resources/templates/list doc://{scenario_id}/{document_id}
PASS AT-16 '배송비를 면제받는 주문 금액 기준' top-3 ⊇ ['operating-policy'] — ['customer-research', 'operating-policy', 'metric-definitions'] scores=[0.6232, 0.564, 0.4802]
PASS AT-16 '분모가 다른 두 이탈 비율' top-3 ⊇ ['metric-definitions'] — ['metric-definitions', 'customer-research', 'metric-definitions'] scores=[0.4879, 0.4735, 0.4297]
PASS AT-16 '주소 입력 화면을 최근에 바꿨나' top-3 ⊇ ['release-log'] — ['customer-research', 'customer-research', 'release-log'] scores=[0.4609, 0.4027, 0.3887]
PASS AT-16 '고객이 가입 때문에 멈췄다는 근거' top-3 ⊇ ['customer-research'] — ['customer-research', 'customer-research', 'customer-research'] scores=[0.5344, 0.3323, 0.317]
PASS AT-16 '기획안에서 내가 결정할 부분' top-3 ⊇ ['brief', 'team-notes'] — ['customer-research', 'team-notes', 'team-notes'] scores=[0.4891, 0.3667, 0.3411]
PASS AT-16 검색 평가 hit율 — 5/5
PASS resources/read 원문에 50,000원 무료배송 문장 포함
PASS 인용 quote가 원문 연속 부분 문자열
PASS rag capability audience 불일치 → FORBIDDEN
결과: 26/26 PASS
```

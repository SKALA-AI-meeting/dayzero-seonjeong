# smoke_mcp — 루프랩 모아런 시나리오 (2026-10-20 13:33 KST)
```
PASS business tools/list 5개 — get_interview_notes,get_rejoin_metrics,get_session_context,patch_artifact_section,update_task_status
PASS 변경 도구 destructiveHint=true/readOnlyHint=false
PASS 조회 도구 readOnlyHint=true/destructiveHint=false
PASS 전체 4000명 중 880명, 재참여율 0.22 — {'segment': 'all', 'first_time_participants': 4000, 'rejoined_within_30d': 880, 'label': '전체', 'rejoin_rate': 0.22}
PASS 모임 규모별 재참여율 31% / 24% / 15.5% — {'large': 0.155, 'medium': 0.24, 'small': 0.31}
PASS group_size 필터
PASS 잘못된 enum → 오류
PASS 인터뷰 공개 전 get_interview_notes → NOT_FOUND — NOT_FOUND
PASS 승인 없는 변경 도구 → 권한 오류(isError) — FORBIDDEN
PASS capability 없음 → FORBIDDEN
PASS rag tools/list = search_docs
PASS rag resources/templates/list doc://{scenario_id}/{document_id}
PASS AT-16 '올해 유료 기능을 출시할 수 있나' top-3 ⊇ ['operating-policy'] — ['meeting-notes', 'operating-policy', 'meeting-notes'] scores=[0.3972, 0.3458, 0.3342]
PASS AT-16 '위치 정보는 어디까지 공개하나' top-3 ⊇ ['operating-policy'] — ['operating-policy', 'meeting-notes', 'meeting-notes'] scores=[0.4438, 0.356, 0.3192]
PASS AT-16 '모임 규모별 재참여율' top-3 ⊇ ['metrics-status'] — ['metrics-status', 'metrics-status', 'meeting-notes'] scores=[0.7817, 0.7706, 0.6361]
PASS AT-16 '이번 분기 최우선 과제' top-3 ⊇ ['meeting-notes'] — ['meeting-notes', 'meeting-notes', 'metrics-status'] scores=[0.6099, 0.6055, 0.3971]
PASS AT-16 '모아런의 주요 사용자와 핵심 기능' top-3 ⊇ ['company-intro'] — ['meeting-notes', 'company-intro', 'company-intro'] scores=[0.4984, 0.4624, 0.4205]
PASS AT-16 검색 평가 hit율 — 5/5
PASS resources/read 원문에 유료 기능 정책 문장 포함
PASS 인용 quote가 원문 연속 부분 문자열
PASS 인터뷰 공개 전 search_docs에서 user-interviews 제외 — ['meeting-notes', 'meeting-notes']
PASS rag capability audience 불일치 → FORBIDDEN
결과: 22/22 PASS
```

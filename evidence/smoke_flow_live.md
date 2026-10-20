# smoke_flow --mode live (gpt-4o-mini) — 루프랩 모아런 시나리오 (2026-10-20 13:54 KST)

LangSmith 키 미설정 → trace는 로컬 로그만(AT-17 LangSmith 부분 NOT_RUN).
```
PASS health mode 일치
PASS 00:00 킥오프: 팀장 브리프 + 동료 인사
PASS 기획안 5섹션
PASS 2시간 타이머
PASS 회사 자료 5개, 인터뷰는 시작 시 잠김
PASS 인터뷰 직접 열람 403
PASS 조사 요청 → 동료 근거 응답 — 모임 규모별 재참여율 지표는 다음과 같습니다:
PASS AI 어시스턴트 응답(문서 근거) — 모아런의 운영 정책에 대한 요약은 다음과 같습니다:
PASS 00:10 업무 분담 이벤트
PASS 분담 제안(기본안)
PASS 분담 조정 1회 → 동료 응답
PASS 분담 확정
PASS 태스크 보드 담당 반영 — {'interview_evidence': 'CANDIDATE', 'similar_cases': 'COLLEAGUE', 'metrics_timeline': 'COLLEAGUE', 'problem': 'CANDIDATE', 'features': 'CANDIDATE'}
PASS 동료 담당 섹션 승인 카드 2개(승인 전 무변경) — ['similar_cases', 'metrics_timeline']
PASS 유사 사례 승인 → 반영
PASS 두 번째 카드 승인도 반영(다른 섹션 변경으로 무효 처리되지 않음) — 202 {"run_id":"5abf580f-5c6a-4c24-874d-44f5ba89fe46","status":"QUEUED"}
PASS 동료 초안이 문서체(대화체·구분선·제목 없음) — {'similar_cases': "- 동네 운동 모임 앱 '같이달려'는 첫 참가자 짝꿍 매칭 기능을 제공함. (지난주 회의록)\n- 걷기 모임 앱 '한바퀴'는 다음 모임 자동 안내 기능을 통해 사용자 편의를 도모함. (지난주 회의록)\n- 두 서비스의 효과 수치는 확인되지 않음. (지난주 회의록)", 'metrics_timeline': '- 모아런의 월 사
PASS 근거 없는 목표치·기간 없음(% 수치는 22/31/24/15.5만) — [('22', '%')]
PASS 수정 요청 → 새 확인 카드
PASS 거절 → 무변경
PASS 지원자는 모든 섹션 직접 편집 가능(이력 기록)
PASS 00:30 도움 요청 이벤트
PASS 도움 요청에 응답 → 동료 대화 — 비슷한 서비스 사례로 다음과 같은 두 가지를 찾았습니다:
PASS 00:50 자료 지연 안내
PASS 지연 중 인터뷰 잠김 + '01:05 공개 예정'
PASS 01:05 인터뷰 공개
PASS 인터뷰 열람 가능
PASS 01:10 대상 변경 이벤트
PASS 변경된 요구사항 반영 저장
PASS 01:30 동료 오류 이벤트
PASS 유료 멤버십 제안 메시지(고정 사실)
PASS 지적 → 동료가 정책 재확인 후 정정 — 확인해 보니, 맞습니다. 운영 정책에 따르면 "루프랩은 올해 유료 기능을 출시하지 않는다"라고 명시되어 있습니다. 따라서 유료 멤버십 제안은 올해 기획 범위에 포함될 수 없네요. 제안을 철회하겠습니다. 다른 기능 아
PASS 01:50 마감 보고 이벤트
PASS 02:00 자동 제출
PASS 세션 SUBMITTED
PASS 제출 후 쓰기 차단
PASS 리포트 5영역 — {'RESPONSIBILITY': 'OBSERVED', 'RESPECT_COMMUNICATION': 'OBSERVED', 'COLLABORATION': 'OBSERVED', 'FLEXIBILITY': 'OBSERVED', 'AI_UTILIZATION': 'OBSERVED'}
PASS 영역별 관찰 근거(메시지·시각) — {'RESPONSIBILITY': 'OBSERVED', 'RESPECT_COMMUNICATION': 'OBSERVED', 'COLLABORATION': 'OBSERVED', 'FLEXIBILITY': 'OBSERVED', 'AI_UTILIZATION': 'OBSERVED'}
PASS 점수·등급·순위·합불 없음
PASS 지원자는 리포트 조회 불가
PASS 디브리핑: 연출 상황 설명 — ['T-SPLIT', 'T-HELP', 'T-DELAY', 'T-INTERVIEW', 'T-PIVOT', 'T-ERROR', 'T-DEADLINE']
결과: 41/41 PASS (session 83c39c05-3193-4aa7-a158-6571dbe8e8f8)
```

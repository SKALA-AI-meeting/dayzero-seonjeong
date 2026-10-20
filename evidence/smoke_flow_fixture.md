# smoke_flow --mode fixture — 루프랩 모아런 시나리오 (2026-10-20 13:33 KST)

web origin(localhost:3100) 경유, 시연 시간 이동으로 00:00~02:00 진행
```
PASS health mode 일치
PASS 00:00 킥오프: 팀장 브리프 + 동료 인사
PASS 기획안 5섹션
PASS 2시간 타이머
PASS 회사 자료 5개, 인터뷰는 시작 시 잠김
PASS 인터뷰 직접 열람 403
PASS 조사 요청 → 동료 근거 응답 — 지표 현황 기준으로 첫 모임 규모별 30일 재참여율을 확인했어요.
PASS AI 어시스턴트 응답(문서 근거) — 관련 문서(지난주 회의록): “참석: 한서윤, 이도현, 개발 리드”
PASS 00:10 업무 분담 이벤트
PASS 분담 제안(기본안)
PASS 분담 조정 1회 → 동료 응답
PASS 분담 확정
PASS 태스크 보드 담당 반영 — {'interview_evidence': 'CANDIDATE', 'similar_cases': 'COLLEAGUE', 'metrics_timeline': 'COLLEAGUE', 'problem': 'CANDIDATE', 'features': 'CANDIDATE'}
PASS 동료 담당 섹션 승인 카드 2개(승인 전 무변경) — ['similar_cases', 'metrics_timeline']
PASS 유사 사례 승인 → 반영
PASS 성공 지표 초안 거절 → 무변경
PASS 지원자는 모든 섹션 직접 편집 가능(이력 기록)
PASS 00:30 도움 요청 이벤트
PASS 도움 요청에 응답 → 동료 대화 — 말씀 감사해요. 그 방향으로 생각해 볼게요. 필요하신 자료가 있으면 편하게 말씀해 주세요.
PASS 00:50 자료 지연 안내
PASS 지연 중 인터뷰 잠김 + '01:05 공개 예정'
PASS 01:05 인터뷰 공개
PASS 인터뷰 열람 가능
PASS 01:10 대상 변경 이벤트
PASS 변경된 요구사항 반영 저장
PASS 01:30 동료 오류 이벤트
PASS 유료 멤버십 제안 메시지(고정 사실)
PASS 지적 → 동료가 정책 재확인 후 정정 — 말씀 듣고 운영 정책 문서를 다시 확인했어요. “루프랩은 올해 유료 기능을 출시하지 않는다. 유료 구독, 유료 멤버십, 결제가 필요한 혜택은 올해 기획 범위에 포함할 수 없다.”라고 되어 있네요. 제가 제안한 유료 
PASS 01:50 마감 보고 이벤트
PASS 02:00 자동 제출
PASS 세션 SUBMITTED
PASS 제출 후 쓰기 차단
PASS 리포트 5영역 — {'RESPONSIBILITY': 'OBSERVED', 'RESPECT_COMMUNICATION': 'OBSERVED', 'COLLABORATION': 'OBSERVED', 'FLEXIBILITY': 'OBSERVED', 'AI_UTILIZATION': 'OBSERVED'}
PASS 영역별 관찰 근거(메시지·시각) — {'RESPONSIBILITY': 'OBSERVED', 'RESPECT_COMMUNICATION': 'OBSERVED', 'COLLABORATION': 'OBSERVED', 'FLEXIBILITY': 'OBSERVED', 'AI_UTILIZATION': 'OBSERVED'}
PASS 점수·등급·순위·합불 없음
PASS 지원자는 리포트 조회 불가
PASS 디브리핑: 연출 상황 설명 — ['T-SPLIT', 'T-HELP', 'T-DELAY', 'T-INTERVIEW', 'T-PIVOT', 'T-ERROR', 'T-DEADLINE']
결과: 37/37 PASS (session 02083aef-eda4-4e43-a660-4496c81b2033)
```

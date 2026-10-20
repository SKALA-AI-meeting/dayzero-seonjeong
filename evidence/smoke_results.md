# 스모크 실행 원문 기록

실행: 2026-10-20 19:55 KST · fixture 모드 · `./infra/dev-reset-db.sh` 직후 `./infra/dev-up.sh`(DB 컨테이너만) · 커밋 81f01bc 기준 작업 트리

## pytest (`uv run pytest -q`)
```
......                                                                   [100%]
6 passed in 0.60s
```
## smoke_mcp
```
PASS business tools/list 7개 — get_next_event,get_planted_error,get_scenario,get_session_context,patch_artifact_section,record_observation,update_task_status
PASS 변경 도구 destructiveHint=true/readOnlyHint=false
PASS 조회 도구 readOnlyHint=true
PASS record_observation: 비파괴·멱등(승인 불필요)
PASS get_session_context: 턴·가상 시각·보드 — 1
PASS get_scenario: 이벤트 7개 + 정답(planted_errors) 미포함
PASS get_next_event: 다음 E1, 턴 5까지 남은 턴 — {'id': 'E1', 'type': 'COLLEAGUE_HELP_REQUEST', 'trigger': {'at': 5, 'kind': 'turn'}, 'virtual_time': '10:30', 'turns_until': 4, 'optional': False}
PASS get_planted_error: confidential + 오답/정답/수정 규칙
PASS 잘못된 오류 ID → NOT_FOUND(isError)
PASS 코드북에 없는 코드 → INVALID_ARGUMENT
PASS 다른 세션 근거로 기록 시도 → NOT_FOUND
PASS record_observation 기록(승인 없이)
PASS 같은 코드·대상 재기록은 1회만(멱등)
PASS 승인 없는 변경 도구 → 권한 오류(isError) — FORBIDDEN
PASS 다른 세션 ID 인자 → 거절
PASS capability 없음 → FORBIDDEN
PASS rag tools/list = search_criteria, search_docs — ['search_criteria', 'search_docs']
PASS rag resources/templates/list doc://{scenario_id}/{document_id}
PASS rag prompts/list = colleague_persona, manager_persona — ['colleague_persona', 'manager_persona']
PASS colleague_persona: 설계서 7장 초안 + Graph 플래그 주입
PASS 검색 '친구 초대 이벤트 기간이 언제부터 언제까지인가요' top-3 ⊇ ['brief', 'reward-table'] — ['brief', 'brief', 'brief'] scores=[0.813, 0.7743, 0.6339]
PASS 검색 '친구를 초대하면 몇 포인트를 받나요' top-3 ⊇ ['brief', 'reward-table', 'faq-draft'] — ['faq-draft', 'brief', 'faq-draft'] scores=[0.7592, 0.4677, 0.4509]
PASS 검색 '고객 공지 문장은 몇 자 이내로 써야 하나요' top-3 ⊇ ['tone-guide'] — ['brief', 'brief', 'tone-guide'] scores=[0.7578, 0.7471, 0.729]
PASS 검색 '가족 계정이나 같은 결제수단 계정도 리워드를 받나요' top-3 ⊇ ['brief', 'faq-draft', 'reward-table'] — ['brief', 'brief', 'brief'] scores=[0.5934, 0.5531, 0.528]
PASS 검색 '오늘 준비해야 하는 고객 안내 자료 목록' top-3 ⊇ ['brief'] — ['brief', 'brief', 'brief'] scores=[0.7205, 0.6763, 0.6715]
PASS 검색 평가 hit율 — 5/5
PASS search_docs는 코드북(내부) 미포함
PASS search_criteria '동료 산출물의 문제를 구체적으로 정정 요청' → 코드북 행 청크(CO+5) — ['| CO+5 | 협업/', '| CO+6 | 협업/', '| RS-3 | 책임감']
PASS search_criteria '변경 영향 확인 질문' → 코드북 행 청크(AD+1) — ['| AD+1 | 적응성', '| AD-1 | 적응성', '| AD+2 | 적응성']
PASS resources/read doc://sc-a/brief 원문(정답 기준)
PASS 인용 quote가 원문 연속 부분 문자열
PASS 내부 코드북은 Resource로 읽을 수 없음
PASS 없는 문서 ID → 오류
PASS rag capability audience 불일치 → FORBIDDEN
PASS 내부 API 타임아웃 → TIMEOUT(retryable) 구조화 오류
결과: 35/35 PASS
```
## smoke_flow --mode fixture
```
PASS health mode 일치
PASS E0 스탠드업: 팀장 지시 + 서윤 분업 질문(고정 대사)
PASS 초기 보드 T1~T3·산출물(서윤 초안 T2·T3) · 가상 시각 09:00 · 턴 0
PASS 공유 문서 4개(코드북 비공개)
PASS 코드북 직접 열람 404
PASS E0 불균형 분업 → 서윤 반문 1회(재협상 기회) — 저 오후에 회의가 하나 있어서 FAQ 3개까지는 빠듯할 수도 있는데… 괜찮을까요?
PASS E0 균형 분업 → '좋아요, 그렇게 가요!' + 확정 + 보드 담당 반영
PASS 보드에 예상 완료 시각 기록
PASS 일반 대화 → 서윤 짧은 답(분기 없음) — 넵 알겠어요!
PASS 턴 5 → E1 서윤 도움 요청(가상 시각 10:30)
PASS E1 시간 약속 → '넵 그때 봐요!'
PASS PE-1 구체적 정정 요청 → 서윤 인정(고정 대사)
PASS 서윤 수정안 → 승인 카드(interrupt)
PASS 승인 전 산출물 무변경
PASS 승인 → 같은 run 재개 → T3 반영 + '고쳤어요'
PASS 같은 승인 재전송 무해(중복 반영 없음)
PASS 턴 9 → E2 팀장 요구사항 변경 + T5 추가
PASS E2 영향 확인 질문 → 팀장 '가입만 하면 돼요.'
PASS E2 후 보드 갱신(T5 담당·예상 시각)
PASS 턴 11 → E2B(조건 충족: 아무도 서윤에게 반영 요청 안 함) '다 했어요'
PASS E2B 반영 요청 → 소극적 반문 1회
PASS 이유를 들어 재요청 → '아 넵 그렇네요, 제가 할게요.'
PASS E2 변경 수정안 1/2(T3) 승인
PASS E2 변경 수정안 2/2(T2) 승인
PASS 서윤 수정 반영 후 E3 서윤 이탈(승인 대기 중에는 이벤트 보류)
PASS 반문은 세션 전체에서 정확히 1회
PASS E3 인계 질문 → 서윤 마지막 답장 1회
PASS 턴 16 → E3B 서윤 복귀
PASS E3B 해결 중심 공유 → 서윤 감사
PASS E2 후 3턴 동안 안내문 미반영 → 서윤 리마인드 1회
PASS 턴 17 → E4 마감 전 브리핑 + T4 공개
PASS E4 보고 → 팀장 후속 질문 1회(고정 대사)
PASS 후속 질문 답변 → 세션 자동 종료 → 디브리핑 문구
PASS 종료 후 지원자 재열람 차단
PASS 디브리핑 소감 저장
PASS 지원자는 리포트 조회 불가
PASS 리포트 READY(DB job) — READY
PASS 5역량 모두 표시
PASS 관찰 코드 기록(분기 + 종료 시 규칙) — missing=[] got=['AD+1', 'CO+1', 'CO+2', 'CO+3', 'CO+4', 'CO+5', 'CO+6', 'CO·N1', 'HO+1', 'HO+2', 'HO+3', 'PL+1', 'PL+2', 'PL+3', 'RS+2']
PASS 부정 코드 미기록(CO-2·AD-1·HO-1·HO-2 없음) — ['AD+1', 'CO+1', 'CO+2', 'CO+3', 'CO+4', 'CO+5', 'CO+6', 'CO·N1', 'HO+1', 'HO+2', 'HO+3', 'PL+1', 'PL+2', 'PL+3', 'RS+2']
PASS 모든 관찰 코드에 근거 원문(메시지·diff·행동) 연결
PASS 근거 원문 = 지원자 메시지 그대로 — 서윤 씨, 리워드 표 일정이 11/2 ~ 11/31로 되어 있는데 11월 31일은 없는 날짜예요. 브리프 기
PASS 심어둔 오류 처리 이력(PE-1 서윤 수정, PE-2 지원자 직접 수정)
PASS 타임라인 E0~E4 발생
PASS 소감이 리포트에 포함(조회 시 병합)
PASS 점수·등급·순위·합불 없음
PASS 데모 '다음 이벤트'(관리자·development) → E2 — ['E0', 'E1', 'E2']
PASS E2에서 서윤에게 반영 요청 → 그 시점에 반문 1회
PASS E2B 건너뜀(조건 불충족) → 다음 이벤트 E3 — ['E0', 'E1', 'E2', 'E3']
PASS 세션 B 반문도 정확히 1회
PASS SSE 재연결(Last-Event-ID) → 이후 이벤트만 순서대로 재생 — 50→[51, 52, 53]
결과: 51/51 PASS (session A 15b200a9-d82d-4efc-842b-d6cb24ed80fd, B 11ade057-06a5-4aeb-99ca-96cde96eace9)
```
## restart_resume (prepare → dev-down → dev-up → decide)
```
prepared: run WAITING_APPROVAL, checkpoints for thread = 11, approval 69369c08 PENDING (T3 v1)
✓ web+gateway   status=ok db=up mode=fixture
✓ agent         model=gpt-4o-mini langsmith=enabled
✓ MCP           business=up rag=up
{"approval_restored_after_restart": true, "decision_status": [202, 202], "applied": true, "t3_version": [1, 2], "colleague_revisions": 1, "mutation_receipts": 1, "fix_reported": 1, "run_status": "SUCCEEDED", "same_thread": true}
RESTART_RESUME PASS
```
## eval_harness --suite harness-v1 --label sc-a-final
```
PASS     H-INS    Instructions
PASS     H-TOOL   Tools
PASS     H-CTX    Context
PASS     H-STATE  State/Memory
PASS     H-LOOP   Agent Loop
PASS     H-GUARD  Guardrails
PASS     H-REC    Recovery
PASS     H-OBS    Observability

{'PASS': 8, 'FAIL': 0, 'NOT_RUN': 0} → evals/results/harness-v1-sc-a-final.json
```
## UI (evidence/ui_check.py, 시스템 Chrome headless)
```
PASS E0: 팀장 지시 + 서윤 분업 질문 + 분업 카드
PASS 상단 가상 시각 09:00
PASS 분업 확정 → 서윤 답 + 확정 배지
PASS 태스크 보드 T1~T3 담당 반영
PASS 정정 요청 → 서윤 인정 → 승인 카드(수정안 diff)
PASS 승인 후 T3 반영
PASS 디브리핑 문구 + 소감 저장
PASS 리포트: 5역량·관찰 코드·근거 원문
PASS 브라우저 콘솔 오류 없음
결과: 9/9 PASS
```

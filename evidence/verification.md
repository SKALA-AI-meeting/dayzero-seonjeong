# 검증 기록 — 핏모아 sc-a 최소 MVP

실행: 2026-10-20 · 브랜치 `refactor/fitmoa-sc-a` · fixture 모드(`LLM_MODE=fixture`) · `./infra/dev-reset-db.sh`로 DB를 새로 만든 뒤 `./infra/dev-up.sh`(**DB 컨테이너 하나만** 기동) · 원문 출력은 [smoke_results.md](smoke_results.md).

판정 규칙: 실제로 실행해 통과한 것만 PASS. 실행하지 않았거나 조건이 안 된 것은 미검증으로 둔다. 이전 시나리오(모아런) 기준 검증 기록과 화면 캡처는 모두 지웠다(git 기록에만 남음).

## 수용 테스트 (docs/AGENT_GUIDE.md 3장)

| ID | 항목 | 결과 | 근거 |
|---|---|---|---|
| AT-01 | 초대 입장 | PASS | pytest 6/6(1회용 교환·재사용 409·만료 410·동의 전 403·start 중복 시 E0 1회·보드 T1~T3·턴 0·09:00), UI 입장 |
| AT-02 | 소유권·권한 | PASS | pytest(타인 세션 404·지원자 관리자 API 403·CSRF/Origin·내부 API 쿠키 불가), smoke_flow(종료 후 재열람 403·지원자 리포트 조회 불가) |
| AT-03 | E0 분업 | PASS | smoke_flow: 불균형 제안 → 반문 → 균형 제안 확정 + '좋아요, 그렇게 가요!' + 보드 담당 반영. UI 분업 카드 확정 |
| AT-04 | 턴 이벤트 발생 | PASS | smoke_flow: 턴 5 E1(10:30), 9 E2(13:00, T5 추가), 11 E2B, 13 이후 E3(승인 대기 중 보류 후 발생), 16 E3B, 17 E4(16:50, T4 추가), 고정 대사, 타임라인 E0~E4 순서 |
| AT-05 | E2B 조건부 | PASS | 세션 A: 아무도 요청 안 함 → E2B 발생 / 세션 B: E2에서 요청 → E2B skipped, 다음 E3 |
| AT-06 | 서윤 반문 1회 | PASS | 세션 A·B 모두 "제가 하는 게 맞을까요"가 정확히 1회, 이유를 든 재요청 → '아 넵 그렇네요, 제가 할게요.' |
| AT-07 | 승인 interrupt 후 재개 | PASS | PE-1 정정 → 승인 카드(T3 수정안) → 승인 전 무변경 → 승인 후 같은 run 재개·반영·'고쳤어요' → 같은 승인 재전송 무해. E2 변경 수정안 2건(T3·T2) 순차 승인. UI 동일 |
| AT-08 | 관찰 코드 기록 | PASS | smoke_flow 리포트에 CO+1, PL+1, CO+2, CO+5, PL+3, CO·N1, AD+1, PL+2, CO+6, CO+4, CO+3, HO+1, HO+2, HO+3, RS+2 기록, 부정 코드(CO-2·AD-1·HO-1·HO-2) 미기록. 모든 코드에 근거 연결. smoke_mcp: 코드북 밖 코드 거절·멱등 |
| AT-09 | 리포트 생성 | PASS | DB job으로 READY, 5역량, '관찰 기회 없음' 표시(UI 단축 흐름의 적응성·정직), 근거 원문 = 지원자 메시지 그대로, 심어둔 오류 처리 이력(PE-1 서윤·PE-2 지원자), 점수·등급·합불 없음. 실패 후 '다시 생성'은 이번에 실패를 주입해 보지 않아 **미검증**(코드 경로만 유지) |
| AT-10 | 재시작 복구 | PASS | restart_resume: 승인 대기 중 전체 재시작 → 승인 복원 → 같은 thread 재개, T3 v1→v2, 서윤 revision 1·receipt 1·'고쳤어요' 1 |
| AT-11 | MCP 오류 처리 | PASS | smoke_mcp: 잘못된 오류 ID NOT_FOUND, 다른 세션 근거 NOT_FOUND, capability 없음 FORBIDDEN, audience 불일치 FORBIDDEN, 승인 없는 변경 거절, 다른 세션 ID 인자 거절, gateway 무응답 → TIMEOUT(retryable) |
| AT-12 | MCP 계약 | PASS | smoke_mcp 35/35: business 7개 도구·주석, get_scenario에 정답 없음, get_next_event turns_until, get_planted_error confidential, rag search_docs·search_criteria, Resource(sc-a), Prompt 2개(플래그 주입), 검색 평가셋 5/5, 코드북 비공개 |
| AT-13 | SSE | PASS | smoke_flow: Last-Event-ID 재연결 시 이후 이벤트만 순서대로 재생. UI는 SSE로 대화·승인 카드 갱신 |
| AT-14 | Harness 8요소 | PASS | eval_harness `sc-a-final` 8/8 → [../evals/results/harness-v1-sc-a-final.json](../evals/results/harness-v1-sc-a-final.json). H-OBS: trace_id 17/17, LangSmith 매칭 17/17. token_usage는 fixture라 0 |
| AT-15 | 디브리핑 | PASS | 연출 안내 문구, 소감 1회 저장, 리포트 조회 시 병합(smoke_flow·UI) |
| AT-16 | 대기열 제거 | PASS | `infra/check-no-queue.sh` 0건(lock 파일 제외 — `package-lock.json`의 integrity 해시에 우연히 포함된 문자열, 사용자 승인). DB 컨테이너만으로 전체 기동·health ok |
| AT-17 | 실제 LLM 1회 시연 | **미검증** | `.env`에 `OPENAI_API_KEY` 없음. live 분류기·페르소나 응답·리포트 요약 경로는 실행하지 않음 |

UI(실제 브라우저, [ui_check.py](ui_check.py), 시스템 Chrome headless): 9/9 PASS, 콘솔 오류 0. 캡처: [screens/](screens/) 01 입장 · 02 과제 안내 · 03 E0 분업 카드 · 04 태스크 보드 · 05 공유 문서(작업본) · 06 승인 카드 · 07 반영 후 · 08 1024px · 09 디브리핑 · 10 관리자 세션 · 11 리포트.

## 확인한 한계

- 시나리오 흐름의 분기 판정은 fixture 규칙 분류로만 확인했다. 지원자의 다양한 표현에 대한 오분류 테스트는 하지 않았다(PRD 11장 TODO).
- 약속 이행(RS+2/RS-2), E4 보고 대조, 오류 '언급'(PL+3·CO-3) 판정은 단순 규칙이다(I7, PRD 11장).
- `search_criteria`는 정의에 가까운 질의(예: "동료 산출물의 문제를 구체적으로 정정 요청" → CO+5, "변경 영향 확인 질문" → AD+1)는 맞지만, 느슨한 바꿔 말하기("동료 실수를 근거와 함께 고쳐 달라고 요청")에서는 top-3에 CO+5가 없었다.
- Docker Compose 빌드·기동은 실행하지 않았다(로컬 프로세스 실행만 검증).
- 리허설(D8, 17턴이 15~20분에 맞는지)은 하지 않았다.
- 무응답 리마인드·자동 진행 중 E2 리마인드만 흐름에서 확인했고, 일반 리마인드(2턴)·자동 진행(+3턴)·E1 NO_RESPONSE·E0 기본 분업 fallback은 전용 테스트가 없다(코드 경로만 존재).

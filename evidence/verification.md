# 수용 테스트 검증 기록 (AT-01 ~ AT-17)

- 기준: AGENT_GUIDE.md v1.3 §6, 시나리오 `DAYZERO_EXAM_SCENARIO.md`(루프랩 모아런, `moarun-rejoin-v1`)
- 환경: 로컬 macOS, Python 3.11.9 · Node 26.7 · PostgreSQL 17 + pgvector(Docker, 호스트 5434), web `http://localhost:3100`
- 모델: `gpt-4o-mini`(live) / fixture. LangSmith 프로젝트 `dayzero-seonjeong-mvp` 연동
- 판정 원칙: 실제로 실행해 확인한 것만 PASS. 일부만 확인했으면 PARTIAL, 실행하지 않았으면 NOT_RUN
- 기록 시각: 2026-10-20 15:0x KST

## 요약

| 판정 | 개수 | 항목 |
|---|---:|---|
| PASS | 13 | AT-01 02 03 04 05 07 08 09 11 12 13 16 17 |
| PARTIAL | 4 | AT-06 10 14 15 |
| FAIL / NOT_RUN | 0 | — |

## 상세

| ID | 판정 | 실행·근거 | 메모 / 남은 확인 |
|---|---|---|---|
| AT-01 | PASS | `services/tests/test_m0_auth.py` 6/6, `smoke_flow` 킥오프 검사 | 로그인→초대→동의→start 2회, 초대 1회 사용, 킥오프(팀장+동료) 1회, 동의 전 업무 API 403 |
| AT-02 | PASS | `evidence/smoke_mcp.md` 22/22 | 전체 4,000/880 = 0.22, 규모별 0.31/0.24/0.155, group_size 필터, 잘못된 enum 오류 |
| AT-03 | PASS | `evidence/smoke_flow_live.md`, `smoke_flow_fixture.md` | 202 → RUN_STARTED → TOOL_START/END → 근거 응답(출처 chip) → DONE, 실제 business/rag MCP 호출 |
| AT-04 | PASS | `smoke_flow` 분담 조정 1회·확정 | 조정 최대 3회, 확정 담당 태스크 반영, 동료 담당 섹션별 delegation/run 생성 |
| AT-05 | PASS | `smoke_flow`, `scripts/smoke_card_revise.py` 7/7 | 승인 전 무변경, 거절 무변경, 승인 후 revision 1개, 중복 승인 무해, 다른 결정 409, 재수정 요청 시 미반영 + 새 카드 |
| AT-06 | PARTIAL | 섹션 단위 stale 판정 코드·smoke 경로 | 확인 대기 중 대상 섹션 변경 시 APPROVAL_STALE 구현. **자동 테스트로 직접 재현은 안 함.** 사용자 결정으로 지원자 담당 섹션도 채팅으로 명시 요청하면 동료가 수정안을 낼 수 있음(승인 필수) — 기존 OUT_OF_SCOPE 기대와 다름 |
| AT-07 | PASS | `smoke_flow` 제출·02:00 자동 제출 | snapshot 고정, 리포트 5영역 OBSERVED·근거 메시지와 시각, 분담 이력, score/grade/rank/pass/fail 없음, 디브리핑 7개 상황 |
| AT-08 | PASS | `evidence/at08_restart_resume.md` | agent 프로세스 종료·재기동 후 승인 대기 복원, 같은 thread_id로 재개, revision 1개·receipt 1개, 승인 2회 전송에도 중복 없음 |
| AT-09 | PASS | M1 검증(프록시 경유 curl), 브라우저 실사용 | Last-Event-ID 재접속 시 이후 seq만 재전송, 타 세션 404. 15시 이후 SYSTEM_NOTICE/DOCUMENTS_UPDATED 구독 누락 수정 |
| AT-10 | PARTIAL | `evals/results/harness-v1-baseline.json` H-REC | 재시도 로직(429 두 번 후 성공 3회, 503 지속 3회 후 실패, 비재시도 1회) 검증. **실제 LLM에 429/503 주입, 리포트 LLM 실패 주입은 NOT_RUN.** 리포트는 현재 규칙 기반(RULES_FALLBACK)만 생성 |
| AT-11 | PASS | `test_m0_auth.py`, `smoke_flow` | 타 세션 404, 지원자 관리자 API·리포트 403, 내부 API 쿠키 호출 차단, extra 필드 422 |
| AT-12 | PASS | `test_m0_auth.py`, `smoke_flow`, `smoke_mcp` | 초대 재사용 409·만료 410, 제출 후 쓰기 409, 승인 없는 변경 도구 거절, 초대 토큰 URL에서 즉시 제거·해시 저장 |
| AT-13 | PASS | `smoke_flow`(시연 시간 이동) | 9개 이벤트 정시·1회, 인터뷰 01:05 전 열람·검색·도구 차단, 01:10 변경 반영, 01:30 오류는 지적 시에만 정정(ERROR_CORRECTED), 시연 기능은 관리자 화면에만 |
| AT-14 | PARTIAL | 인용 원문 검증 코드, `smoke_mcp` | quote가 원문 부분 문자열이 아니면 citation 제거, 문서 내 지시문은 데이터 취급(프롬프트). **조작 citation·조작 tool args 주입 테스트는 NOT_RUN** |
| AT-15 | PARTIAL | `evidence/screens/*.png`(Chrome headless 실조작) | 1440/1280/1024/1920 가로 overflow 없음·페이지 스크롤 없음, PRD 팔레트·코랄 버튼 #111827, 그라데이션 없음, 상태 텍스트 라벨. **키보드만으로 전체 흐름·200% 확대·스크린리더는 NOT_RUN** |
| AT-16 | PASS | `evidence/smoke_mcp.md` | 384차원·모델 revision·index_version 저장, 검색 평가 5/5 top-3, Resource 원문 일치, 인터뷰 공개 전 검색 제외 |
| AT-17 | PASS | `evals/results/harness-v1-baseline.json` 8/8 | 8요소 고정 평가셋 PASS, LangSmith root trace 20건 중 20건이 run_id metadata로 매칭, run별 trace_id·token_usage 저장 |

## 스모크·평가 명령 (services/ 에서)

```bash
uv run pytest -q tests/test_m0_auth.py
uv run python -m scripts.smoke_mcp
uv run python -m scripts.smoke_flow --mode live          # agent가 LLM_MODE=live일 때
uv run python -m scripts.eval_harness --suite harness-v1 --label baseline
PYTHONPATH=. uv run python -m scripts.smoke_card_revise
PYTHONPATH=. uv run python -m scripts.smoke_task
uv run python -m scripts.restart_resume prepare   # → agent 재시작 → decide
```

## 알려진 한계

- 리포트의 LLM 해석(LLM_WITH_RULES)은 미구현이며 규칙 기반 사실 리포트만 생성한다(화면에 명시).
- live 동료 초안의 출처 표기가 가끔 부정확하다. 지원자가 확인 카드에서 검토한다.
- Docker Compose(`compose.yaml`)는 작성했지만 컨테이너 빌드·기동은 실행하지 않았다(NOT_RUN). 검증은 로컬 프로세스 기준이다.
- 대기열(RabbitMQ) 가산점, 다중 시나리오 등 P1 항목은 하지 않았다.

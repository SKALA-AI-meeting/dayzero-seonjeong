# 리팩터링 계획: 모아런(이전) → 핏모아 sc-a(신규) 최소 MVP

작성: 2026-10-20 · 기준 문서: 리팩터링 지시 프롬프트 > `docs/SCENARIO_SC_A.md` > `data/fitmoa-invite-v1/scenario.json` > 기존 `ARCHITECTURE.md`의 유지 계약

이 문서는 **삭제 전 인벤토리**다. 확인을 받기 전에는 어떤 파일도 지우지 않는다.

범례: **삭제** / **수정**(같은 파일을 새 시나리오에 맞게 고침) / **교체**(지우고 같은 역할의 새 파일 작성) / **유지**(손대지 않음 또는 import 정리만) / **이동** / **신규**

---

## 1. RabbitMQ 제거

| 파일 | 처리 | 내용 |
| --- | --- | --- |
| `services/shared/mq.py` | 삭제 | 큐 클라이언트 전체 |
| `services/scripts/smoke_queue.py` | 삭제 | 큐 smoke |
| `evidence/smoke_queue.md` | 삭제 | 큐 검증 기록 |
| `services/agent/app/worker.py` | 수정 | `mq.publish_report / consume_reports / enabled()` 분기와 `_report_consumer` 스레드 제거. REPORT는 `jobs` 폴링 경로 하나로만 처리 |
| `services/agent/app/main.py` | 수정 | `/health`의 queue 항목 제거 |
| `services/gateway/app/internal/routes.py` | 수정 | 큐 관련 분기 제거 |
| `compose.yaml` | 수정 | `rabbitmq` 서비스, agent의 `RABBITMQ_URL`, `depends_on` 제거 |
| `.env.example` | 수정 | `RABBITMQ_URL` 제거 |
| `infra/dev-up.sh`, `dev-status.sh`, `dev-down.sh` | 수정 | RabbitMQ 기동·확인·종료 코드 제거 (DB만 기동) |
| `services/pyproject.toml`, `services/uv.lock` | 수정 | `pika` 제거 후 `uv lock` |
| `services/shared/config.py` | 수정 | `rabbitmq_url` 설정 제거 |
| `README.md`, `docs/*.md`, `evidence/verification.md` | 수정 | RabbitMQ·DLQ·대기열 가산점 언급 제거 (6장 문서 재작성 때 함께) |

확인: `grep -rniE "rabbit|amqp|pika|dlq|mq\." --exclude-dir=.git --exclude-dir=node_modules --exclude-dir=.venv .` → 0건.
※ `frontend/package-lock.json:2568`도 매치되지만 패키지 integrity 해시(`...itephWDLqDzbe...`) 안의 우연한 `dlq`다. 검증 명령에 `--exclude=package-lock.json`을 추가하고 이 사실을 verification.md에 적는다. **→ 확인 필요 Q3**

## 2. AI 어시스턴트 제거

| 파일 | 처리 | 내용 |
| --- | --- | --- |
| `prompts/assistant-v2.md` | 삭제 | |
| `services/scripts/smoke_assistant_leak.py` | 삭제 | |
| `services/agent/app/graph.py` | 수정 | `ASSISTANT` run kind, 읽기 전용 분기, 미공개 일정 가드(`_guard_unreleased_schedule`) 제거 |
| `services/gateway/app/schema.sql` | 수정 | `messages.channel`에서 `ASSISTANT`, `runs.kind`에서 `ASSISTANT` 제거 |
| `services/gateway/app/api/sessions.py` | 수정 | 메시지 채널 `ASSISTANT` 분기 제거 |
| `services/gateway/app/internal/routes.py` | 수정 | assistant 컨텍스트·리포트 영역 제거 |
| `services/agent/app/report.py` | 수정 | AI 활용 영역 제거 (4장 리포트 재구성과 함께) |
| `frontend/src/app/office/[sid]/page.tsx` | 수정 | 어시스턴트 탭·패널·버튼 제거 |
| `frontend/src/lib/types.ts`, `lib/events.ts`, `components/Overlay.tsx`, `app/globals.css` | 수정 | assistant 채널·문구·스타일 제거 |
| `frontend/src/app/admin/reports/[sid]/page.tsx` | 교체 | 4.4 구조로 재작성 (어시스턴트 영역 포함 제거) |
| `frontend/src/styles/tokens.css` | 유지 | 지시대로 그대로 둠 (assistant 색 토큰이 있으면 미사용으로 남김) |

## 3. 이전 시나리오 전용 기능·데이터

### 3.1 데이터·프롬프트

| 파일 | 처리 | 내용 |
| --- | --- | --- |
| `data/moarun-rejoin-v1/` (11개 파일 전체) | 삭제 | 문서 6, interviews.json, policies/exam-v1.json, rejoin_metrics.csv, retrieval_eval.json, scenario.json |
| `data/fitmoa-invite-v1/scenario.json` | 유지 | 시드 계약 (현재 untracked, 커밋에 포함) |
| `data/fitmoa-invite-v1/documents/brief.md` | 신규 | 정답 기준 (`brief_facts` 그대로) |
| `data/fitmoa-invite-v1/documents/reward-table.md` | 신규 | 서윤 초안 + PE-1(11/2~11/31), PE-2(5,000P) |
| `data/fitmoa-invite-v1/documents/faq-draft.md` | 신규 | 서윤 FAQ 2개 + PE-4(Q1 반말), PE-3(Q2 가족 계정) |
| `data/fitmoa-invite-v1/documents/tone-guide.md` | 신규 | 반말 금지, 한 문장 40자 이내 등 |
| `data/fitmoa-invite-v1/documents/criteria.md` | 신규 | 설계서 6장 코드북 (rag-mcp `search_criteria` 색인 전용, 지원자 문서 목록에는 노출 안 함) |
| `data/fitmoa-invite-v1/retrieval_eval.json` | 신규 | 검색 평가셋 (eval_harness용, 최소 몇 건) |
| `prompts/colleague-v2.md` (이도현) | 교체 | → `prompts/colleague-seoyoon-v1.md` (설계서 7장 프롬프트 초안 그대로) |
| `prompts/manager-junho-v1.md` | 신규 | 이벤트 노드에서만 발화, 브리프 범위 1회 답변 |
| `prompts/classify-branch-v1.md` | 신규 | `branches[].when` + `feedback_rules[].when` 닫힌 분류기 ("해당 없으면 NONE") |
| `prompts/section-writer-v1.md` | 삭제 | 5섹션 기획안 전용 |
| `prompts/report-v1.md`, `report-observe-v1.md` | 교체 | → `prompts/report-sc-a-v1.md` 하나로 (코드 판정 보조·근거 요약, 점수 없음) |
| `prompts/summary-v1.md` | 유지 | 대화 요약 (Harness Context) |

### 3.2 백엔드

| 파일 | 처리 | 내용 |
| --- | --- | --- |
| `services/gateway/app/timeline.py` | 교체 | → `events.py` 턴 기반 이벤트 엔진 (`advance_turn`, `fire_event`, 조건부 E2B, no_response_policy, E3 오프라인). `apply_split`은 E0 분업용으로 옮겨 유지. `submit_session`은 "세션 종료 + 종료 시 일괄 판정 + REPORT job" 으로 수정 |
| `services/gateway/app/domain.py` | 수정 | `elapsed_min`, `hidden_document_ids`(인터뷰 잠금), `section_sha`(5섹션) 제거 → `virtual_time`, 산출물 단위 헬퍼 |
| `services/gateway/app/business.py` | 교체 | 재참여율·인터뷰 로직 삭제 → `get_scenario / get_next_event / get_planted_error / record_observation` 로직 |
| `services/gateway/app/api/sessions.py` | 수정 | 메시지·보드·문서 액션마다 `turn_count` 증가 → 이벤트 엔진 호출. 문서 잠금 제거. 산출물 PATCH를 산출물 ID 단위로 |
| `services/gateway/app/api/work.py` | 수정 | split(E0) · approvals decision · submit · debrief(소감 입력 추가) · report · retry 유지. 위임(delegations)·revoke·task review(5섹션 위임 검토) 제거. `/demo/advance`를 "다음 이벤트 발생"으로 변경(development 전용) |
| `services/gateway/app/internal/routes.py` | 수정 | `/timeline/tick` 제거, `/mcp/{tool}`에 새 도구 연결, 리포트 build를 4.4 구조로, `/runs/{rid}/followup`(위임 후속) 제거 |
| `services/gateway/app/schema.sql` | 수정 | 아래 DB 변경 반영 |
| `services/gateway/alembic/versions/0001_initial.py`, `0002_moarun_scenario.py` | 교체 | → 새 `0001_initial.py` 하나 (데모 DB, 데이터 보존 안 함) |
| `services/scripts/seed.py` | 수정 | fitmoa 시나리오·문서·태스크·서윤 초안 산출물만 seed |
| `services/scripts/index_documents.py` | 수정 | 새 문서 경로·`criteria` 색인 |
| `services/shared/config.py` | 수정 | `SCENARIO_ID`, `SECTION_IDS`, `DATASET_VERSION` → fitmoa 값 (`fitmoa-invite-v1` ↔ JSON `sc-a` 매핑 상수) |
| `services/agent/app/graph.py` | 수정(대폭) | 8장 Graph로 재구성. 기존 `classify_request → reason ⇄ call_mcp → validate_output → respond`와 `persist_proposal → await_approval(interrupt) → execute_write / record_rejection` 골격 재사용. section-writer·위임·`select_help`·지표 fixture 제거 |
| `services/agent/app/harness.py` | 수정 | 8요소·한도 유지. `SAFE_FALLBACK` 문구, 가드레일(숫자 근거 검사)을 새 시나리오에 맞게 + **정답 누설 가드**(`planted_errors[].correct`가 서윤 응답에 나오면 차단) |
| `services/agent/app/report.py` | 교체 | 5역량 × 관찰 코드 + 근거 원문 + 이벤트. "관찰 기회 부족 / 없음" 구분. CO·N1만 있고 CO+5 없을 때 사실 문장 |
| `services/agent/app/clients.py` | 유지 | |
| `services/business_mcp/server.py` | 수정 | `get_rejoin_metrics`, `get_interview_notes` 삭제 / `get_scenario`, `get_next_event`, `get_planted_error`, `record_observation` 추가 / `get_session_context`, `update_task_status`, `patch_artifact_section`(destructiveHint) 유지 |
| `services/rag_mcp/server.py` | 수정 | `search_docs`, `doc://` Resource 유지 / `search_criteria` Tool, `colleague_persona`·`manager_persona` Prompt 추가 |
| `services/shared/mcp_common.py`, `db.py`, `embedding.py` | 유지 | |

### 3.3 DB 변경 (schema.sql → 새 0001_initial)

| 테이블 | 처리 |
| --- | --- |
| `funnel_facts`, `support_cases` | 삭제 (커머스 잔재) |
| `delegations` (+ `tasks_delegation_fk`, `actions_delegation_idem`) | 삭제 (5섹션 위임 전용) |
| `scenario_events` | 수정: 시나리오 JSON의 `events[]`를 그대로 저장 (`trigger` jsonb) |
| `event_occurrences` | 유지 (세션당 이벤트 1회 기록, unique(session_id, event_id)) |
| `sessions` | 수정: `turn_count`, `virtual_time`, `colleague_state`(offline·남은 답장 수·allow_pushback 사용 여부) 추가 / 2시간 마감 컬럼 제거 |
| `artifacts`, `artifact_revisions` | 수정: 섹션 단위 → 산출물 단위(T1 안내문, T2 FAQ, T3 표, T5 푸시, T4 보고). 공유 문서 중 서윤 초안(reward-table, faq-draft)도 artifact로 seed해 diff 이력 남김 |
| `observations` | 신규: `session_id, code, competency, event_id, evidence_ref, note, created_at` |
| `commitments` | 신규: `session_id, message_id, text, registered_turn, status(OPEN/KEPT/BROKEN), resolved_at` |
| `messages.channel`, `runs.kind` | 수정: ASSISTANT 제거. 메시지 actor에 `manager` 추가, `kind`에 `SCENARIO_EVENT` 구분 |
| 그 외 (`users, invites, participants, scenarios, tasks, runs, approvals, mutation_receipts, documents, document_chunks, actions, tool_calls, reports, jobs, stream_events`, checkpoints 스키마) | 유지 |

### 3.4 스크립트·평가·검증 기록

| 파일 | 처리 | 판단 |
| --- | --- | --- |
| `smoke_flow.py` | 교체 | fixture 모드 E0→E4→디브리핑→리포트 한 번에 (완료 기준) |
| `smoke_mcp.py` | 수정 | 새 도구 + 오류 처리(잘못된 ID, 다른 세션, 타임아웃) 기준 유지 |
| `restart_resume.py` | 수정 | 서윤 정정 → 승인 interrupt → 재시작 → 같은 thread 재개 |
| `smoke_card_revise.py` | 교체 | → `smoke_correction.py`: 지원자 정정 요청 → 서윤 수정안 → 승인/거절 (새 흐름 핵심) |
| `smoke_joint_draft.py`, `smoke_revise.py`, `smoke_task.py` | 삭제 | 5섹션 공동 초안·위임 전용. 보드 갱신은 smoke_flow에서 검증 |
| `eval_harness.py`, `evals/harness-v1.json` | 수정 | 8요소 유지, 케이스를 새 시나리오로 (H-GUARD에 정답 누설·반문 1회 추가) |
| `evals/results/harness-v1-baseline.json` | 삭제 | 새로 실행한 결과로 다시 채움 |
| `services/tests/test_m0_auth.py` | 유지 | (시나리오 ID 참조가 있으면 값만 수정) |
| `evidence/screens/*.png` (12장) | 삭제 | |
| `evidence/at08_restart_resume.md`, `smoke_flow_fixture.md`, `smoke_flow_live.md`, `smoke_mcp.md` | 삭제 | 새 검증 결과로 다시 생성 |
| `evidence/verification.md` | 교체 | 새 수용 테스트 표 (실제 실행한 것만 PASS) |

### 3.5 프론트엔드

| 파일 | 처리 | 내용 |
| --- | --- | --- |
| `app/office/[sid]/page.tsx` | 수정(대폭) | 좌: 공유 문서 4 + 태스크 보드 / 중: 팀 메신저(서윤·팀장) / 우: 내 산출물 편집기. 상단 가상 시각. 타이머·인터뷰 잠금·5섹션 레이아웃 제거 |
| `components/Messenger.tsx` | 수정 | 팀장 actor 표시, SCENARIO_EVENT 메시지 구분 |
| `components/TaskBoard.tsx` | 수정 | 담당·예상 완료 시각 입력 (PL+1 근거) |
| `components/ArtifactEditor.tsx` | 수정 | 섹션 → 산출물 탭(T1/T2/T3/T5/T4) |
| `components/ApprovalCard.tsx`, `SplitCard.tsx` | 수정 | 서윤 수정안 diff 표시 / E0 분업 (이름·태스크만 교체) |
| `components/Overlay.tsx` | 수정 | assistant·제출 체크리스트 문구 교체 |
| `components/AdminShell.tsx`, `Icon.tsx` | 유지 | |
| `app/debrief/[sid]/page.tsx` | 수정 | 디브리핑 문구 + 소감 입력 |
| `app/admin/reports/[sid]/page.tsx` | 교체 | 5역량 × 코드 + 근거 + 이벤트 |
| `app/admin/sessions/page.tsx`, `admin/login`, `join`, `page.tsx`, `layout.tsx` | 유지/문구 수정 | 이름·시나리오 문구만 |
| `lib/types.ts`, `lib/api.ts`, `lib/events.ts` | 수정 | SECTIONS·CHANNELS·COPY 교체 / SSE 재연결·재생 로직은 유지 |
| `styles/tokens.css` | 유지 | |

### 3.6 문서

| 파일 | 처리 |
| --- | --- |
| `docs/DAYZERO_EXAM_SCENARIO.md` | 삭제 (→ SCENARIO_SC_A.md) |
| `docs/SCENARIO_DATA.md` | 삭제 (→ SCENARIO_SC_A.md) |
| `docs/ROADMAP_MULTI_COMPANY.md` | 이동 → `docs/archive/` |
| `docs/SCENARIO_SC_A.md` | 유지 (현재 untracked, 커밋에 포함) |
| `docs/PRD.md` | 교체 (v2.0, 지시된 목차) |
| `docs/ARCHITECTURE.md` | 수정 (RabbitMQ 제거, 턴 엔진, 새 테이블, MCP 계약, Graph) |
| `docs/AGENT_GUIDE.md` | 수정 (수용 테스트 재번호) |
| `docs/DESIGN_GUIDE.md` | 수정 (디자인 토큰만 남기고 이전 화면 예시 제거, 1340줄 → 대폭 축소) |
| `docs/README.md`, `README.md` | 수정 |
| `docs/REFACTOR_PLAN.md` | 신규 (이 문서) |

## 4. 이름 충돌 (한서윤·이도현)

`grep -rn "한서윤\|이도현"` 결과 26개 파일. 단순 치환 금지, 역할 기준:

- 이전 **팀장 한서윤** → 새 **팀장 박준호** (예: `seed.py`, `work.py`, `types.ts`의 팀장 표기, 공지 채널 발신자)
- 이전 **AI 동료 이도현** → 새 **AI 동료 한서윤** (예: `graph.py`, `colleague-v2.md`, `SplitCard`, `ApprovalCard`, `TaskBoard`)
- 대부분은 삭제 대상 파일(이전 시나리오 문서·데이터·assistant 프롬프트)이라 함께 사라진다. 남는 코드 파일은 역할을 확인하고 하나씩 바꾼다.

## 5. 구현 결정 (설계서에 명시가 없어 이렇게 처리할 예정)

| # | 결정 | 근거 |
| --- | --- | --- |
| I1 | `fitmoa-invite-v1`(dataset/폴더) ↔ `sc-a`(scenario_id, `doc://sc-a/...`) 매핑 상수를 `shared/config.py`에 둠 | 지시 4.1 |
| I2 | 턴 증가 대상: 팀 메시지 전송, 보드 상태/담당 변경, 산출물 저장, 승인 결정. 문서 열람은 턴이 아님(로그만) | 지시 4.2 "보드·문서 액션 1개" — 열람까지 턴으로 치면 리허설 턴 수가 흔들림 |
| I3 | 같은 턴에 트리거 여러 개면 순서대로 1개만 발생, 나머지는 다음 턴 | 세션당 1회·순서 고정 |
| I4 | E4 follow_up(팀장 유도 질문)은 지원자 첫 보고 답장 직후 고정 발화 | scenario.json `follow_up` |
| I5 | 분류기 fixture 모드: 라벨별 키워드 규칙으로 결정적 분류 (LLM 없이 smoke_flow 재현) | fixture 모드 유지 |
| I6 | 오류 "발견" 판정(PL+3): 산출물/공유 문서 diff에서 wrong 문자열 제거 또는 메시지에서 해당 위치 언급 — 종료 시 일괄 판정 | 설계서 5장 |
| I7 | 약속 이행(RS+2/RS-2): 약속 등록 후 세션 종료까지 관련 문서 변경 또는 완료 언급이 있으면 KEPT, 없으면 BROKEN — MVP는 단순 규칙, 정교화는 TODO | 설계서 9장 TODO |
| I8 | 리포트는 기존 REPORT job 하나 + `/reports/{sid}/retry` | 지시 4.4 |

## 6. 커밋 단계 (각 단계 후 기동 확인)

1. RabbitMQ 제거
2. 어시스턴트·이전 시나리오 기능 삭제 (이 시점엔 이전 시나리오가 부분적으로 깨질 수 있으므로 3과 붙여서 기동 확인할 수도 있음)
3. 새 시나리오 데이터·DB·seed
4. 턴 기반 이벤트 엔진 + Graph + MCP 도구
5. 프론트엔드 정리
6. 문서 재작성
7. 검증 (evidence 갱신)

## 7. 확인 필요 (작업 시작 전)

- **Q1 브랜치/푸시**: 지시문은 `refactor/fitmoa-sc-a` 브랜치 생성, 기존 작업 규칙(메모리)은 "main에 커밋·푸시, 브랜치 생성 금지". 어느 쪽으로 할지.
- **Q2 실제 LLM 시연**: 키가 `.env`에 있으면 1회 실행, 없으면 "미검증"으로 기록 — 이대로 진행해도 되는지.
- **Q3 grep 0건**: `frontend/package-lock.json` 매치를 grep 제외 대상으로 처리해도 되는지.

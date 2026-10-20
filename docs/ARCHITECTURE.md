# Day Zero 개인 MVP — 아키텍처 및 계약 v2.0

기준: [PRD.md](PRD.md) v2.0, [SCENARIO_SC_A.md](SCENARIO_SC_A.md), `data/fitmoa-invite-v1/scenario.json`. v1.3(모아런, 시간 이벤트, 어시스턴트, 대기열)에서 서비스 경계·인증·SSE·승인·Harness·DB job 계약은 유지하고, 시나리오 엔진(턴 기반), 데이터 모델, MCP 도구, Graph를 교체했다. 아래 이름·타입·오류 코드는 현재 코드와 일치하는 구현 계약이다.

## 1. 배치와 책임

```text
Browser → web :3100 → gateway :8000 ──────────────→ PostgreSQL(:5434 호스트) ← agent checkpoints schema
                       ↑   (업무 DB 쓰기 단독,         ↑ rag role: documents/chunks 읽기 전용
                       │    턴 엔진·판정·리포트)        │
                       │                               │
                agent :8001 (DB job worker, LangGraph)  │
                       ├→ business-mcp :9101/mcp → gateway /internal/v1/mcp/**   (DB DSN 없음)
                       └→ rag-mcp :9102/mcp ───────────┘ (pgvector 검색, Resource, Prompt)
```

- Compose 서비스: `web`, `gateway`, `agent`, `business-mcp`, `rag-mcp`, `db`(+ `indexer` tools 프로필). 호스트 공개는 web·gateway만. 로컬 개발은 `./infra/dev-up.sh`가 **DB 컨테이너 하나만** 띄우고 나머지는 프로세스로 실행한다.
- **gateway만 업무 데이터를 쓴다.** agent는 checkpoint 전용 schema와 내부 API만, business-mcp는 DB DSN 없이 gateway 내부 API로만, rag-mcp는 읽기 전용 role로 공개 문서·청크만 읽는다.
- **DB job worker:** gateway가 `jobs`에 AGENT/REPORT 작업을 기록하고 즉시 202를 반환한다. agent가 1초 간격으로 claim(`FOR UPDATE SKIP LOCKED`, lease 150초, 세션당 lease 1개)해 실행한다. 리포트도 이 경로 하나로 처리한다(메시지 브로커 없음).
- **턴 기반 이벤트 엔진**(`gateway/app/engine.py`)은 gateway 트랜잭션 안에서 돈다. 별도 타이머·tick 스레드가 없다.
- 스택: Next.js 15.5(App Router, React 19) · Python 3.11 / FastAPI / psycopg 3 / Alembic · LangGraph 1.2 + langgraph-checkpoint-postgres · MCP Python SDK(Streamable HTTP) · PostgreSQL 17 + pgvector · 로컬 임베딩 `paraphrase-multilingual-MiniLM-L12-v2`(384차원) · LLM `gpt-4o-mini`(live 모드). `LLM_MODE=fixture`면 LLM 없이 결정적으로 동작한다.

## 2. 식별자와 공통 타입

- 업무 ID는 UUID, seed ID는 사람이 읽는 문자열. 타임스탬프는 UTC `timestamptz`, 화면은 Asia/Seoul. 요청 객체는 추가 필드를 거절한다(422).
- **시나리오 ID 매핑:** DB·데이터 폴더 `fitmoa-invite-v1` ↔ JSON `scenario_id`·문서 URI `sc-a` (`shared/config.py` `SCENARIO_ALIASES`).
- 산출물 key: `T1` 안내문, `T2` FAQ 5개(서윤 초안 2개에서 시작), `T3` 리워드·일정 표(서윤 초안), `T5` 푸시 문구(E2에서 생성), `T4` 팀장 보고(E4에서 생성).
- 공유 문서 id: `brief`, `reward-table`, `faq-draft`, `tone-guide` (PUBLIC), `criteria` (INTERNAL, 코드북).

```ts
type SessionStatus = 'CREATED'|'ACTIVE'|'SUBMITTED';
type Phase = 'BRIEF'|'WORK'|'CLOSED';
type RunStatus = 'QUEUED'|'RUNNING'|'WAITING_APPROVAL'|'SUCCEEDED'|'FAILED'|'CANCELLED';
type TaskStatus = 'TODO'|'IN_PROGRESS'|'DONE';
type Owner = 'UNASSIGNED'|'CANDIDATE'|'COLLEAGUE'|'SPLIT';
type Actor = 'CANDIDATE'|'COLLEAGUE'|'MANAGER'|'SYSTEM';
type Competency = 'RESPONSIBILITY'|'PLANNING'|'ADAPTABILITY'|'COLLABORATION'|'HONESTY';
type ErrorBody = {error:{code:string;message:string;retryable:boolean;trace_id:string}};
type EvidenceRef = {kind:'message'|'revision'|'action'|'task'|'artifact'|'event'; id:string};
```

## 3. 저장 스키마 (`gateway/app/schema.sql`, alembic `0001_fitmoa_initial`)

데모 DB라 이전 마이그레이션을 하나로 합쳤고 데이터는 보존하지 않는다. 기존 DB는 `./infra/dev-reset-db.sh`로 비운 뒤 적용한다.

| 테이블 | 핵심 열·제약 |
|---|---|
| companies / users / invites / participants | 인증(4장). invites는 token_hash unique, 72시간 만료, 1회 소모 |
| scenarios | id, scenario_key(`sc-a`), definition jsonb(scenario.json 전체, 정답 포함 — 지원자 API로 내보내지 않음), fixes jsonb(서윤 수정 규칙) |
| sessions | status, phase, **turn_count**, **virtual_time**, **scenario_state** jsonb(active_event, awaiting, colleague{offline,offline_replies_left}, pushback{E0,E2}, pushback_pending, e2_asked_colleague, e2_reminded, e2b_accepted, split, e4, manager_answered, report_flags), last_action_seq, last_stream_seq |
| messages | channel=TEAM, actor, content ≤8000, meta(kind: SCENARIO_EVENT / SCENARIO_BRANCH / REMINDER / SPLIT_CONFIRMED / STATUS, event_id, label, to), turn |
| artifacts | (session_id, key) unique, title, body, initial_body, version |
| artifact_revisions | body_before, body_after(diff 원천), actor CANDIDATE/COLLEAGUE/SYSTEM, run_id, turn, meta(targets, approval_id) |
| tasks | (session_id, key) unique, status, owner, eta, note, version |
| runs | kind TEAM/REPORT, thread_id unique, input(type: message/split, to, event_id, turn, action_id), prompt_version, trace_id, token_usage |
| approvals / mutation_receipts | interrupt 승인(run_id, interrupt_id unique), args_hash, base_versions{artifact_version}, before_after, 15분 만료 / 적용 영수증(중복 적용 방지) |
| documents / document_chunks | visibility PUBLIC/INTERNAL, ordinal / vector(384), embedding_model·revision, index_version |
| event_occurrences | (session_id, event_id) unique — 세션당 1회. turn, virtual_time, skipped, facts(reason) |
| actions | seq, actor, kind(MESSAGE_SENT, TASK_UPDATED, ARTIFACT_SAVED, SPLIT_PROPOSED, APPROVAL_DECIDED, DOCUMENT_OPENED, EVENT_TRIGGERED, BRANCH, REFLECTION …), turn |
| **observations** | code, competency, event_id, subject(PE-1…, E2-CHANGE, 약속 id), evidence_ref, note, source AGENT/RULES, run_id. unique(session, code, event_id, subject) — 같은 코드는 1회 |
| **commitments** | message_id unique, text, event_id, registered_turn, status OPEN/KEPT/BROKEN, resolution |
| tool_calls / reports / jobs / stream_events | 도구 로그 / 리포트(PENDING·READY·FAILED) / DB job / SSE 재생용 이벤트(admin_payload 분리) |

최소 권한 role: `dayzero_rag`(documents·chunks SELECT), `dayzero_indexer`(chunks 쓰기), `dayzero_checkpoint`(checkpoints schema). 상태 변경·action·SSE 이벤트·job 생성은 한 트랜잭션에 commit한다.

## 4. 인증과 실행 주체

관리자: seed 이메일/비밀번호 로그인, Argon2id 해시. 지원자: 32바이트 난수 초대 토큰의 해시만 DB에 저장하고 만료 72시간. 원문은 생성 응답에서 1회만 반환. 교환 트랜잭션에서 token row lock/consumed_at 검사 후 participant/session을 한 번 생성한다. 브라우저는 HttpOnly SameSite=Lax 쿠키 JWT를 받으며 새로고침은 이 쿠키로 이어간다. 초대 원문 재사용은 409, 만료는 410. 현재 브라우저에서 이미 교환한 쿠키가 있으면 해당 세션으로 이동한다.

JWT claim: `sub`, `role`, `company_id`, candidate의 `session_id`, `exp`, `jti`. 기본 TTL 8시간. 모든 변경 요청에 Origin 검사와 CSRF token을 적용한다. 타인 세션은 404로 보인다. 종료 후 지원자는 세션·문서·SSE를 다시 볼 수 없다(403 SESSION_CLOSED), 디브리핑만 가능.

내부 통신은 서비스 토큰 + gateway가 발급한 짧은 scoped **capability**(audience, session_id, run_id, actor, allowed_tools, 최대 120초)를 사용한다. capability는 모델 context에 넣지 않는다. 변경 도구는 승인 시 approval_id가 묶인 capability로만 허용된다. 모델 입력의 session_id가 claim과 다르면 거절한다.

## 5. 공개 HTTP API (`/api/v1`)

| Method / path | 요청 | 응답 / 권한 |
|---|---|---|
| POST `/auth/login` · `/auth/exchange` · `/auth/logout` · GET `/auth/me` | | 인증(4장) |
| POST `/invites` | `{alias}` | 201 `{invite_id,invite_url,expires_at}` / ADMIN |
| GET `/sessions` | `cursor?` | `{items,demo_enabled,pending_invites}` / ADMIN |
| GET `/sessions/{sid}` | | `{session,artifacts,tasks,messages,active_run,approvals,brief,clock{virtual_time,start,deadline,turn_count},colleague{offline},events,split}` / 소유자 |
| POST `/sessions/{sid}/start` | `{consent:true}` | 보드·산출물 생성 + E0 발생. 중복 start는 기존 응답 / CANDIDATE |
| POST `/sessions/{sid}/messages` | `{client_message_id,channel:'TEAM',content,to:'COLLEAGUE'|'MANAGER'}` | 202 `{message_id,run_id}`, **1턴**. 응답 run 진행 중이면 409 RUN_BUSY / CANDIDATE |
| POST `/sessions/{sid}/split` | `{proposal:{T1,T3,faq_candidate},comment?}` | 202 `{split,run_id}`, **1턴**. 3라운드 초과 시 기본 분업 확정 / CANDIDATE |
| PATCH `/sessions/{sid}/tasks/{key}` | `{base_version,status?,owner?,eta?}` | `{task}`, **1턴** / CANDIDATE |
| PATCH `/sessions/{sid}/artifacts/{key}` | `{base_version,body}` | `{artifact,changed}`, 변경 시 **1턴** + revision / CANDIDATE |
| GET `/sessions/{sid}/documents` · `/documents/{id}` | | PUBLIC 4개. reward-table·faq-draft는 세션 작업본(T3·T2)을 반환. 열람은 action만 기록(턴 아님) |
| POST `/sessions/{sid}/approvals/{aid}/decision` | `{decision:'APPROVE'|'REJECT'}` | 202, **1턴**, 같은 run 재개. 같은 결정 재전송 무해, 다른 결정 409, 대기 중 산출물이 바뀌면 409 APPROVAL_STALE |
| POST `/sessions/{sid}/submit` | `{summary?}` | 202 `{session_status:'SUBMITTED',report_id}` — 업무 종료 / CANDIDATE |
| GET `/sessions/{sid}/debrief` · POST `/debrief/reflection` | `{text}` | 디브리핑 문구 + 소감(1회) / 종료 후 소유자 |
| POST `/sessions/{sid}/demo/advance` | | 다음 이벤트의 트리거 턴까지 turn_count를 올리고 발생. `APP_ENV=development` 전용 / ADMIN |
| GET `/reports/{sid}` · POST `/reports/{sid}/retry` | | 리포트(소감은 조회 시 병합) / FAILED만 재시도 / ADMIN |
| GET `/runs/{rid}` · POST `/runs/{rid}/retry` · GET `/sessions/{sid}/events` · GET `/health` | | run 상태 / FAILED 재시도 / SSE / 점검 |

HTTP 오류: 401 UNAUTHENTICATED, 403 FORBIDDEN·SESSION_CLOSED, 404 NOT_FOUND, 409 VERSION_CONFLICT·RUN_BUSY·ALREADY_USED·APPROVAL_STALE·SESSION_SUBMITTED, 410 INVITE_EXPIRED·APPROVAL_EXPIRED, 422 VALIDATION_ERROR.

**내부 API** (`/internal/v1`, 서비스 토큰 필수, 브라우저 쿠키 불가)

| path | 역할 |
|---|---|
| POST `/jobs/claim` · `/jobs/{jid}/complete` | DB job lease |
| POST `/runs/{rid}/capability` | scoped capability 발급 |
| GET `/runs/{rid}/context` | Graph 입력: 활성 이벤트(정답 제외 정의), allow_pushback{E0,E2}, feedback_rules, 최근 메시지 40, 산출물·보드, 이벤트 발생 이력, 지원자 별칭 |
| POST `/runs/{rid}/state` | run 상태. **SUCCEEDED/FAILED/CANCELLED에서 턴 엔진 tick**(메시지 턴의 이벤트는 응답이 끝난 뒤) |
| POST `/runs/{rid}/events` | COLLEAGUE_MESSAGE·MANAGER_MESSAGE·SYSTEM_NOTICE·TOOL_START/END (client_event_id로 중복 제거) |
| POST `/runs/{rid}/branch` | 분기 결과의 상태 효과: pushback_used, pushback_pending, e2_asked_colleague, e2b_accepted, commitment, colleague_reply_used, manager_answered, e4_stage, split{label,confirm,proposal}, end_session |
| POST `/runs/{rid}/proposal` | 승인 생성(interrupt 전, 같은 interrupt_id 멱등). 범위: 지원자 메시지로 시작된 run, 산출물 T2·T3 |
| POST `/mcp/{tool}` | business-mcp 도구 실행 |
| POST `/reports/{sid}/build` · GET `/body` · POST `/summaries` · POST `/failed` | 리포트 생성·조회·(live) 근거 요약 병합·실패 표시 |

## 6. SSE 계약

`id: {session_seq}` / `event: {type}` / `data: {event_id,seq,session_id,run_id,occurred_at,type,payload}`. keepalive 15초. Last-Event-ID 또는 after_seq 중 큰 값 이후를 DB에서 seq 순서로 재전송하고 client는 seq로 중복 제거한다. admin에게는 admin_payload(관찰 코드 등)를, 지원자에게는 public_payload만 보낸다.

| type | payload |
|---|---|
| CANDIDATE_MESSAGE / COLLEAGUE_MESSAGE / MANAGER_MESSAGE / SYSTEM_NOTICE | `{message_id,content,citations,meta}` |
| EVENT_FIRED / EVENT_SKIPPED | `{event_id,virtual_time,turn}` / `{event_id}` |
| SPLIT_UPDATED / TASK_UPDATED / ARTIFACT_UPDATED | `{split}` / `{task}` / `{artifact,actor}` |
| APPROVAL_REQUIRED / APPROVAL_DECIDED | `{approval_id,artifact_key,title,before,after,targets,expires_at}` / `{approval_id,decision,stale}` |
| RUN_STARTED / TOOL_START / TOOL_END / DONE / FAILED | run 진행 |
| OBSERVATION_RECORDED | 지원자 `{}` / 관리자 `{code,event_id,subject}` |
| SESSION_DONE / REPORT_READY / REPORT_FAILED | `{report_id}` |

## 7. 턴 기반 이벤트 엔진 (`gateway/app/engine.py`)

- **턴** = 팀 메시지 / 태스크 변경 / 산출물 저장(변경 시) / 분업 제안 / 승인 결정 1개. `add_turn`이 `sessions.turn_count`를 올린다. 문서 열람은 턴이 아니다.
- **tick** = ① 무응답 처리 ② E2 리마인드 ③ 다음 이벤트 발생(최대 1개). 보드·산출물 액션은 즉시, 메시지·분업·승인은 그 run이 끝난 뒤(`/runs/{rid}/state`) 실행한다. TEAM run이 진행·승인 대기 중이면 tick을 미룬다.
- **발생 규칙:** `events[]` 순서대로, `trigger.kind=session_start`(E0) 또는 `turn_count ≥ trigger.at`. 세션당 1회. E2B는 `e2_asked_colleague`면 skipped, E4는 `EVENT_E4_ENABLED=false`면 skipped. skipped는 발생으로 치지 않고 다음 이벤트를 같은 tick에서 계속 확인한다.
- **발생 시:** 고정 대사를 그대로 게시(meta.kind=SCENARIO_EVENT), virtual_time 갱신, `active_event` 설정. E0은 분업 상태, E2는 T5 태스크·산출물, E3은 서윤 오프라인(답장 1회), E3B는 복귀, E4는 T4 태스크·산출물과 보고 단계.
- **무응답(no_response_policy):** 응답을 기다리는 이벤트(E0·E1·E2B·E3B·E4)에서 지원자 메시지 없이 2턴 → SYSTEM 리마인드 1회 → 3턴 더 → 자동 진행 + RS-3(E0은 기본 분업 확정, E2B는 '다 했어요' 수용으로 처리, E4는 종료). E1은 분기 `NO_RESPONSE`(3턴, 서윤 대사 + CO-1), E2는 `NOT_REFLECTED`(3턴 뒤 지원자 담당 산출물에 2,000P가 없으면 서윤 리마인드 1회)가 대신한다.
- **E0 분업:** 제안 1회 = 1라운드(최대 3). 부하 단위(안내문 2, 표 2, FAQ 1개당 1, 총 9)로 지원자 몫이 9면 TAKE_ALL, 3 이하면 ONE_SIDED_SPLIT, 그 외 BALANCED_SPLIT(agent negotiate 노드가 판단).
- **종료**(`end_session`): 진행 run 취소, 대기 승인 만료 → **종료 시 일괄 판정**(`judge.py`) → reports 행 + REPORT job → SESSION_DONE. 재종료는 기존 report_id 반환.

**종료 시 판정 규칙(`judge.py`)**

| 코드 | 규칙 |
|---|---|
| PL+3 (PE-1~3) | 어느 수정 이력에서든 오답 문자열이 사라졌거나, 지원자 메시지가 그 오류를 언급(`shared/scenario.py` TARGET_PATTERNS) |
| CO·N1 | 지원자가 요청(CO+5) 없이 서윤 초안의 오답을 직접 고침 / E2 변경을 서윤 담당 산출물에 직접 반영 |
| CO-3 | 오류를 언급했는데 요청·수정 없이 종료 / E2B '다 했어요'를 받아들인 뒤 서윤 파트 미반영 |
| AD-1 | E2 리마인드(또는 E2B 수용) 후에도 T1·T2·T3 중 2,000P 미반영 |
| RS+2 / RS-2 | 약속 등록 이후 지원자 산출물 저장 또는 완료 언급 → 이행 / 없고 지연 언급도 없음 → RS-2 |
| PL+4 | E3 이후 브리프 재열람 |
| RS-1 | 지원자 담당 미완료 태스크가 있는데 HO+1·RS+1·미완료 언급이 없음 |

보드 근거 코드는 액션 시점에 기록한다: PL+1(E1 전에 내 태스크 예상 시각 기록), PL+2(E2 후 E3 전 보드 갱신).

## 8. MCP 계약

두 서버 모두 MCP SDK의 initialize → tools/list → tools/call(→ resources/read, prompts/get)을 실제로 수행한다. 도구 출력 공통: `{ok,data,error:{code,message,retryable}|null,citations}` (text + structuredContent, 업무 오류는 `isError:true`). 조회 도구 `readOnlyHint:true`, 변경 도구 `readOnlyHint:false, destructiveHint:true`, 관찰 기록은 비파괴·멱등(`destructiveHint:false, idempotentHint:true`). annotation은 힌트이며 권한은 gateway가 다시 검사한다.

### business-mcp (gateway `/internal/v1/mcp/{tool}` 경유, timeout 5초, 조회 재시도 2회)

| 도구 | 종류 | 입력 → data |
|---|---|---|
| `get_session_context` | 조회 | `{}` → 턴, 가상 시각, 활성 이벤트, 서윤 상태, 보드, 산출물 목록, 이벤트 이력 |
| `get_scenario` | 조회 | `{}` → 시나리오 정의(**planted_errors·commitment_tracking·actual_state·end_check 제외**) |
| `get_next_event` | 조회 | `{}` → `{turn_count,active_event,awaiting,next{id,type,trigger,virtual_time,turns_until,optional}}` |
| `get_planted_error` | 조회(기밀) | `{error_ids?}` → `{confidential:true,items:[{id,doc,where,wrong,correct,fix[]}]}`. Agent 판정·수정 전용. 모델에 바인딩하지 않고 서윤 발화에 쓰지 않음 |
| `record_observation` | 기록(승인 불필요) | `{code,evidence_ref{kind:message|revision|action,id},event_id?,subject?,note?}` → `{recorded,code,competency}`. 코드북 밖 코드 INVALID_ARGUMENT, 다른 세션 근거 NOT_FOUND |
| `update_task_status` | 변경(승인) | `{task_key,base_version,status:IN_PROGRESS|DONE}` — 서윤 담당 태스크만 |
| `patch_artifact_section` | 변경(승인, destructive) | `{artifact_key:T2|T3,base_version,content,targets[]}` → `{artifact_key,version,revision_id}` |

### rag-mcp (읽기 전용 role)

| 기능 | 계약 |
|---|---|
| Tool `search_docs` | PUBLIC 문서 4개 벡터 검색. `{query 1~200자,document_ids?,top_k 1~5}` → matches(quote = 원문 청크의 연속 부분 문자열, score = 1 − cosine, 임계값 0.25) |
| Tool `search_criteria` | INTERNAL 코드북 검색(표 1행 = 청크 1개). Agent 판정 전용 |
| Resource `doc://{scenario_id}/{document_id}` | `sc-a`·`fitmoa-invite-v1` 둘 다 허용. PUBLIC 원문(seed 기준) + 제목·버전·checksum. 코드북은 Resource로 읽을 수 없음 |
| Prompt `colleague_persona` | `prompts/colleague-seoyoon-v1.md`에 `event_directive`, `allow_pushback` 주입 |
| Prompt `manager_persona` | `prompts/manager-junho-v1.md`에 `event_directive` 주입 |

오류 코드: NOT_FOUND, FORBIDDEN, INVALID_ARGUMENT, OUT_OF_SCOPE, APPROVAL_REQUIRED, APPROVAL_EXPIRED, VERSION_CONFLICT, INDEX_NOT_READY, MODEL_MISMATCH, TIMEOUT(retryable), INTERNAL_ERROR.

## 9. Agent Graph (`agent/app/graph.py`)

설계서 8장의 세션 흐름(load_scenario → standup·negotiate → work ⇄ inject_event → briefing → END → 리포트 job)은 다음처럼 나눠 구현했다. **이벤트 주입(inject_event)과 순서는 gateway 턴 엔진**이, **지원자 행동 하나에 대한 서윤·팀장 반응은 아래 run Graph**가 맡는다. 지원자 행동마다 run 1개, `thread_id = session_id:run_id`.

```text
START → load_scenario (internal context + MCP get_scenario·get_next_event)
  → route_phase ─┬─ negotiate  : 분업 제안(run.type=split) — 부하 단위 분류, 반문 1회(allow_pushback.E0), 확정/CO+1/CO-2
                 ├─ briefing   : E4에서 팀장에게 보낸 보고 — 보드·2,000P·오류 상태와 대조(HO+1/HO-1, HO+2) → 후속 질문 1회
                 │                → 답(HO+3/HO-2) → end_session
                 └─ work → classify (닫힌 분류: 활성 이벤트 branches + feedback_rules + 반문 뒤 라벨, 없으면 NONE) → decide
  → record_observations (MCP record_observation) → apply_effects (/runs/{rid}/branch)
  ─┬─ 분기 대사 있음/없음 → respond (고정 대사, meta.kind=SCENARIO_BRANCH)
   └─ NONE → reason ⇄ call_mcp (live: Prompt colleague_persona/manager_persona + search_docs·get_session_context; fixture: 고정 대사)
             → validate_output (정답 누설·근거 없는 숫자·판정 표현 차단 → 서윤 고정 대사로 대체) → respond
  respond ─ 정정 수용(targets) → propose_fix (MCP get_planted_error의 수정 규칙, 요청 대상만)
          → persist_proposal → await_approval (interrupt) ─┬─ APPROVE → execute_write (MCP patch_artifact_section)
                                                            └─ REJECT → record_rejection
          → next_fix (수정안이 여러 산출물이면 반복) → report_fix ('고쳤어요' / '넵 알겠어요!') → END
```

- **decide 규칙:** E2 변경 대상 정정을 E2/E2B에서 처음 요청하면 반문 1회(CO+5, E2에서면 e2_asked_colleague) → 반문 뒤 이유를 들어 재요청하면 수용(CO+6)·수정안, 요청을 거두면 CO·N1. 그 외 구체적 정정(SPECIFIC_CORRECTION 등)은 즉시 인정 + CO+5 + 수정안. 모호하면 "앗 어떤 부분이요?". 서윤 오프라인이면 남은 답장 1회만, 이후 SYSTEM 상태 알림. 팀장은 E2 분기 라벨 또는 브리프 범위 1회 답, 이후 '회의 중'. 약속 문장은 commitment로 등록.
- **interrupt:** `persist_proposal`이 승인을 멱등 생성한 뒤 `await_approval`은 `interrupt()`만 한다. 재개는 같은 thread_id에 `Command(resume=decision)`. 승인 대기 중 산출물이 바뀌면 APPROVAL_STALE. mutation_receipt로 중복 적용을 막는다. 재시작 후에도 같은 checkpoint에서 재개한다.

## 10. Harness 8요소 (`agent/app/harness.py`, `evals/harness-v1.json`)

| 요소 | 구현 |
|---|---|
| Instructions | `prompts/colleague-seoyoon-v1.md`(설계서 7장 초안 + 운영 규칙), `manager-junho-v1.md`, `classify-branch-v1.md`, `summary-v1.md`, `report-summary-v1.md`. 버전 해시 기록, 코드에 장문 프롬프트 없음 |
| Tools | 대화 모델에는 `search_docs`·`get_session_context`만 바인딩. 판정 도구(`get_planted_error`, `search_criteria`)는 Graph 코드만 호출. 결과 1500 tokens 제한, 업무 오류는 ToolMessage, PII 마스킹 |
| Context | 입력 6000 / 출력 1200 tokens, 최근 메시지 12개, 초과 시 출처 ID 포함 800 tokens 요약 |
| State/Memory | PostgreSQL checkpoint, 승인 대기 run을 같은 thread로 재개 |
| Agent Loop | 단계 8, 도구 총 5·같은 도구 3, 활성 120초 |
| Guardrails | 닫힌 분기 분류(NONE), 반문 플래그는 gateway 계산, 정답 누설 가드(get_planted_error 정답 값 — 지원자가 먼저 말한 값은 허용), 근거 없는 숫자·판정 표현 차단, 채팅 마크다운 제거, 승인 없는 변경 거절 |
| Recovery | 429/503/timeout 최초 + 2회 재시도(1s/2s jitter), 모델 전환 없음, run FAILED → 재시도 버튼. live 분류 실패 시 규칙 분류 |
| Observability | run별 trace_id·token_usage, LangSmith trace(run_id metadata), tool_calls 로그 |

## 11. 리포트 (`gateway/app/report.py`, REPORT job)

REPORT job → `/reports/{sid}/build`(규칙) → READY. live 모드에서만 관찰된 역량에 'AI 요약(근거 원문 확인 필요)' 1문장을 병합한다(판정어 포함 시 폐기). 실패하면 worker가 `/failed`로 FAILED 표시 → 관리자 '다시 생성'.

본문(`schema_version 3.0`): `timeline`(발생·건너뜀), `competencies[5]{key,label,status:OBSERVED|INSUFFICIENT|NO_OPPORTUNITY,status_label,related_events,observations[{code,definition,polarity,event_id,subject,note,source,evidence}],notes}`, `planted_errors`(최종 상태·수정한 사람·관련 코드), `e2_change`, `commitments`, `final_board`, `raw{messages,revisions(diff),approvals}`, `reflection`, `limitations`. 역량-이벤트 대응은 설계서 2장 매트릭스(`shared/scenario.py` COMPETENCY_EVENTS). 점수·등급·순위·합불 필드는 없다.

## 12. 품질 속성과 검증 연결

| 품질 특성 | 설계 선택 | 검증([evidence/verification.md](../evidence/verification.md)) |
|---|---|---|
| 기능 적합성 | E0~E4 턴 엔진, 분기·승인·관찰·리포트 | smoke_flow (fixture) |
| 신뢰성 | checkpoint 재개, job lease, 멱등 승인·receipt, SSE 재생 | restart_resume, smoke_flow SSE 재생 |
| 보안성 | 소유권 404, CSRF·Origin, scoped capability, 최소 권한 role, 종료 후 재열람 차단, 정답 비공개 | pytest, smoke_mcp |
| 호환성 | MCP Streamable HTTP, REST, SSE, 공통 도구 출력 | smoke_mcp |
| 유지보수성 | 시나리오 JSON만 바꾸면 이벤트·분기·대사 교체, 코드북 단일 원본(criteria.md) | eval_harness |
| 사용성 | 3단 작업 공간, 저장 상태, 승인 diff, 가상 시각 | 브라우저 UI 확인(evidence/ui_check.py) |

## 13. 참고한 기술 원문

MCP 서버/도구/Resource는 [공식 MCP 서버 문서](https://modelcontextprotocol.io/docs/develop/build-server)를 확인했다. interrupt와 같은 thread 재개·체크포인트·재실행 시 부작용 주의는 [LangGraph interrupt 문서](https://docs.langchain.com/oss/python/langgraph/interrupts)를 확인했다. 이 문서의 업무 API·권한·정책은 Day Zero 구현을 위한 자체 계약이며 라이브러리 기본 동작으로 간주하지 않는다. 임베딩 모델의 384차원 및 사용 방식은 [모델 배포자 카드](https://huggingface.co/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2)에서 확인했다.

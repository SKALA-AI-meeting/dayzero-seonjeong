# Day Zero 개인 MVP — 아키텍처 및 계약 v1.3

기준: PRD v1.3, 2026-10-20 16:30 KST. v1.3은 시나리오 교체(`DAYZERO_EXAM_SCENARIO.md`, moarun-rejoin-v1)에 따라 시나리오에 묶인 식별자(지표 테이블·MCP 도구·섹션·이벤트·분담 API)만 바꿨으며 서비스 경계·인증·SSE·승인·Harness 계약은 그대로다. 공식 교안 표 5-4~6/6-3/6-13/6-14 및 사용자 디자인·포트 지정 반영. 아래 이름·타입·오류 코드는 구현 계약이다. 현재는 설계 문서이며 파일/명령의 구현 완료를 뜻하지 않는다.

## 1. 배치와 책임

```text
Browser → web :3100 → gateway :8000 → agent :8001
                       ↑                ├→ business-mcp :9101/mcp → gateway /internal/**
                       │                └→ rag-mcp :9102/mcp → pgvector chunk index (read-only)
                       └──────── PostgreSQL :5432 ← agent checkpoints/jobs
                                               ← rag-mcp read-only document role
```

Compose 서비스 이름: `web`, `gateway`, `agent`, `business-mcp`, `rag-mcp`, `db`. P1은 `rabbitmq`, `report-worker`. 호스트 공개는 web/gateway만. web은 `/api/**`를 gateway로 프록시하고 SSE buffering을 끈다. 브라우저는 같은 origin 쿠키를 사용한다. gateway만 업무 데이터 쓰기 권한을 갖는다. agent는 체크포인트 전용 schema와 자기 job 실행용 내부 API만 사용한다. business-mcp에 DB DSN을 주지 않는다. rag-mcp의 DB role은 공개 문서/청크 read-only이며 평가 기준·개입 정책을 조회할 수 없다.

web은 컨테이너 내부도 3100에 bind하고 Compose는 `3100:3100`으로 매핑한다. APP_ORIGIN은 `http://localhost:3100`이다. 프록시의 gateway 내부 주소는 `http://gateway:8000`이며 브라우저 API/SSE는 web의 동일 origin을 사용한다. CSRF/Origin 허용 목록과 브라우저 테스트 base URL은 APP_ORIGIN에서 읽는다. Next.js dev/start 모두 명시적으로 포트를 지정하고 프레임워크의 기본값에 의존하지 않는다.

디자인 토큰의 기준은 PRD 6.1이다. `frontend/src/styles/tokens.css`에 `--color-primary`, `--color-primary-hover`, `--color-primary-soft`, `--color-heading`, `--color-body`, `--color-muted`, `--color-background`, `--color-surface`, `--color-border`, `--color-success`, `--color-info`, `--color-warning`, `--color-error`, `--color-on-primary`를 정의한다. 버튼/카드/입력/상태 컴포넌트가 이를 공유하며 화면별 임의 팔레트를 추가하지 않는다. on-primary는 #111827이고 코랄 버튼에 흰 글자를 적용하지 않는다. gradient는 제외하고 panel은 border 중심으로 구분한다.

실행 비용을 줄이기 위해 agent가 세션/리포트 job executor를 겸한다. gateway는 DB jobs에 작업을 기록하고 즉시 202를 반환한다. agent는 1초마다 내부 claim API로 job을 얻어 실행한다. P0 단일 agent worker, 세션당 동시 run 1개. 인메모리 BackgroundTasks만으로 내구성 요구를 충족했다고 보지 않는다.

빈 저장소 기본 스택은 Next.js 15.5 App Router/React 19.1/TypeScript 5, Python 3.11.9/FastAPI 0.150/Pydantic 2/SQLAlchemy 2/Alembic/LangGraph 1.2(langgraph-checkpoint-postgres 3.2), mcp 2.3, sentence-transformers 6.1, PostgreSQL 17(pgvector/pgvector:pg17 이미지). 버전은 구현 환경(Node 26.7, uv 0.11)에서 설치 가능한 조합으로 확정했다. 정확한 라이브러리 버전은 첫 실행 성공 조합을 lockfile에 고정한다. MCP는 공식 Python SDK의 Streamable HTTP를 사용하고 설치 버전의 서버/클라이언트 API를 확인한다. 최신 SDK의 import 이름을 과거 FastMCP 예제와 혼합하지 않는다. `gpt-4o-mini`는 기존 자료의 모델 제약으로 설정값에 고정한다.

교안 53쪽 레퍼런스는 Vue 3/Vite, Spring Boot 3, FastAPI·LangGraph 1.x·LangChain 1.x, FastMCP 4.1/mcp 2.x, Chroma 또는 pgvector, PostgreSQL 16이다. 이 패키지는 UI/업무 서버 프레임워크를 마감용 개인 구현 가정으로 바꾸지만 계층 책임은 그대로 유지한다. 프레임워크 선택까지 공식 허용받았다는 의미는 아니다. Agent의 ‘DB 직접 쓰기 금지’는 업무 데이터에 적용하고 checkpointer의 전용 schema 저장만 허용한다(교안 64쪽은 agent checkpointer의 DB 접근을 명시).

P0 오프라인 색인 경로: `회사 자료 5개 → 모델 토큰 기준 청크 → local embedding → pgvector`. 온라인 경로: `질문 → 같은 모델의 embedding → cosine top-k → 출처 청크 → 필요시 Resource 원문 열람`. 로컬 모델은 `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`(384차원)를 구현 가정으로 선택한다. CPU 사용, 정규화 벡터, 모델 revision을 색인 metadata에 고정한다. LLM API 모델 제한과 별도인 로컬 임베딩이며 추가 유료 API를 만들지 않는다. 첫 다운로드/색인은 질문 처리 전에 완료하고 검색 중 자동 다운로드하지 않는다.

## 2. 공통 타입/식별자

업무 ID는 UUID 문자열. 문서/시나리오/이벤트 seed ID는 사람이 읽는 문자열. 타임스탬프는 UTC ISO 8601, 화면은 Asia/Seoul. SQL은 `timestamptz`, JSON 필드는 `jsonb`. 요청 객체는 추가 필드를 거절한다. 문자열 길이·배열 크기는 서버에서 검사한다.

```ts
type SessionStatus = 'CREATED'|'ACTIVE'|'SUBMITTED';
type Phase = 'BRIEF'|'WORK'|'REVIEW'|'CLOSED';
type RunStatus = 'QUEUED'|'RUNNING'|'WAITING_APPROVAL'|'SUCCEEDED'|'FAILED'|'CANCELLED';
type TaskStatus = 'TODO'|'IN_PROGRESS'|'REVIEW'|'DONE'|'CANCELLED';
type Role = 'ADMIN'|'CANDIDATE';
type Channel = 'TEAM'|'ASSISTANT';
type Actor = 'CANDIDATE'|'COLLEAGUE'|'MANAGER'|'ASSISTANT'|'SYSTEM';
type ErrorBody = {error:{code:string;message:string;retryable:boolean;trace_id:string}};
type Citation = {document_id:string;chunk_id:string;version:number;quote:string};
type EvidenceRef = {
  kind:'message'|'artifact_revision'|'action'|'tool_call'; id:string;
  field:string; start:number|null; end:number|null; quote:string|null
};
```

문자 인용 구간은 Unicode code point 기준, 0부터 시작하고 end는 제외한다. 언어 사이에 같은 기준을 적용하며 UI의 UTF-16 index를 그대로 보내지 않는다. 인용이 없는 조작 근거는 start/end/quote를 null로 둔다.

## 3. 저장 스키마

세션에 종속된 행은 `session_id`를 가지며 gateway가 소속 company와 participant를 다시 확인한다. 요청 본문에 들어 있는 company_id나 actor/role을 인증 근거로 신뢰하지 않는다.

| 테이블 | 필수 열·제약 |
|---|---|
| companies | id UUID PK, name text |
| users | id UUID PK, company_id FK, email unique, password_hash text, role ADMIN |
| invites | id UUID PK, company_id FK, alias text, token_hash unique, expires_at, consumed_at nullable, session_id nullable unique |
| participants | id UUID PK, company_id FK, alias text, session_id unique FK |
| scenarios | id text PK, version int, title text, public_brief jsonb, policy_version text. P0 seed만 허용 |
| sessions | id UUID PK, company_id FK, participant_id FK, scenario_id FK, scenario_version int, status, phase, consent_at nullable, started_at nullable, submitted_at nullable, version int default 1, last_action_seq bigint default 0, last_stream_seq bigint default 0, auto_intervention_count int default 0, policy_state jsonb default {} |
| messages | id UUID PK, session_id FK, channel, actor, content text max 8000, citations jsonb default [], source_run_id nullable, client_message_id nullable, created_at. unique(session_id,client_message_id) |
| artifacts | id UUID PK, session_id unique FK, sections jsonb (5 sections), version int default 1 |
| artifact_revisions | id UUID PK, session_id FK, artifact_id FK, version int, sections jsonb, changed_sections jsonb, actor, run_id nullable, created_at. unique(artifact_id,version) |
| tasks | id UUID PK, session_id FK, title text max 160, status, owner CANDIDATE/COLLEAGUE, target_section nullable, delegation_id nullable, result jsonb nullable, version int |
| delegations | id UUID PK, session_id FK, task_id FK, source_message_id FK, tool_allowlist jsonb, section_allowlist jsonb, constraints jsonb, expires_at, revoked_at nullable, version int |
| runs | id UUID PK, session_id FK, thread_id text unique, kind COLLEAGUE/ASSISTANT/DELEGATED/REPORT, status, source_message_id nullable, task_id nullable, input jsonb, result jsonb nullable, policy_version text, prompt_version text, trace_id text, trace_url nullable, token_usage jsonb, estimated_cost nullable, pricing_version nullable, error_code nullable, created_at, updated_at |
| approvals | id UUID PK, session_id FK, run_id FK, interrupt_id text, tool_name text, args jsonb, args_hash text, base_versions jsonb, delegation_id nullable, status PENDING/APPROVED/REJECTED/EXPIRED/APPLIED, expires_at, decided_at nullable, decision_actor_id nullable. unique(run_id,interrupt_id) |
| mutation_receipts | operation_id text PK, session_id FK, approval_id FK unique, result jsonb, applied_at |
| documents | id text PK, scenario_id FK, version int, title, body text, visibility PUBLIC, checksum text, available_after_min int(시험 시계 기준 공개 시각, 인터뷰 65) |
| document_chunks | id text PK, document_id FK, document_version int, ordinal int, body text, keywords jsonb, embedding vector(384), embedding_model text, embedding_revision text, embedding_dimension int CHECK(embedding_dimension=384), index_version text. unique(document_id,document_version,ordinal,index_version) |
| rejoin_facts | scenario_id FK, dataset_version text, group_size small/medium/large, first_time_participants int, rejoined_within_30d int. PK(scenario_id,dataset_version,group_size), CHECK(0≤rejoined≤first_time) |
| interview_notes | id text PK, scenario_id FK, group_size text, tags jsonb, quote text |
| scenario_events | id text PK, policy_version, predicate_key(이벤트 kind), payload jsonb(고정 메시지·관찰 영역), priority int, at_min int(00:00 기준 발생 분) |
| event_occurrences | id UUID PK, session_id FK, event_id FK, trigger_action_seq bigint, facts jsonb, response_message_id nullable, occurred_at_min numeric, created_at. unique(session_id,event_id) |
| actions | id UUID PK, session_id FK, seq bigint, actor, kind text, entity_id text nullable, payload jsonb, created_at. unique(session_id,seq) |
| tool_calls | id UUID PK, session_id FK, run_id FK, tool_name, safe_args jsonb, result_summary jsonb, citations jsonb, help_id text, policy_version, outcome, duration_ms, created_at |
| reports | id UUID PK, session_id unique FK, status PENDING/RUNNING/READY/FAILED, version int, source_snapshot jsonb, body jsonb nullable, attempts int default 0, error_code nullable |
| jobs | id UUID PK, session_id FK, run_id nullable unique FK, dedupe_key text unique, kind AGENT/REPORT, input jsonb, status QUEUED/LEASED/DONE/FAILED, attempt int, available_at, lease_until nullable, last_error nullable |
| stream_events | id UUID PK, session_id FK, seq bigint, run_id nullable, type text, public_payload jsonb, admin_payload jsonb nullable, created_at. unique(session_id,seq) |

LangGraph checkpoint는 공식 PostgreSQL saver의 전용 `checkpoints` schema를 사용한다. 독자적인 JSON 저장만으로 interrupt 재개를 흉내 내지 않는다. 인용 보존을 위해 messages/revisions는 immutable로 관리한다. pgvector extension과 vector(384) 열은 P0 migration에 포함한다. 데이터가 작으므로 ANN 인덱스 튜닝은 제외하고 exact cosine search를 사용한다. sessions↔participants와 tasks↔delegations의 순환 FK는 지연 검사(DEFERRABLE INITIALLY DEFERRED)로 같은 transaction에서 생성하거나 한쪽을 nullable로 두고 commit 전 연결한다. seed는 FK 제약을 끄지 않는다.

업무 트랜잭션에서 상태 변경·action·SSE event·job 생성을 함께 commit한다. `actions.seq`와 `stream_events.seq`는 서로 다른 카운터이며 session row lock으로 각각 증가시킨다. phase/status/version/seq는 원자적으로 갱신한다. 리스트 API는 최신 100개와 cursor를 반환한다. 서버는 기획안 본문 합계 40,000자, 검색 query 200자, 청크당 1,500자, 결과 최대 5개로 제한한다.

## 4. 인증과 실행 주체

관리자: seed 이메일/비밀번호 로그인, Argon2id 등 검증된 해시 사용. 지원자: 32바이트 난수 초대 토큰의 해시만 DB에 저장하고 만료 72시간. 원문은 생성 응답에서 1회만 반환. 교환 트랜잭션에서 token row lock/consumed_at 검사 후 participant/session을 한 번 생성한다. 브라우저는 HttpOnly SameSite=Lax 쿠키 JWT를 받으며 새로고침은 이 쿠키로 이어간다. 초대 원문 재사용은 409, 만료는 410. 현재 브라우저에서 이미 교환한 쿠키가 있으면 해당 세션으로 이동한다.

JWT claim: `sub`, `role`, `company_id`, candidate의 `session_id`, `exp`, `jti`. 기본 TTL 8시간. 로그아웃은 쿠키 제거. P0는 같은 브라우저 쿠키 재접속, 다른 기기 복구는 제외한다. 모든 변경 요청에 Origin 검사와 CSRF token을 적용한다. 쿠키는 HTTPS에서 Secure, 로컬 http에서만 development 예외. GET SSE는 credential 쿠키를 사용하고 URL에 토큰을 넣지 않는다.

내부 통신은 서비스 인증 + gateway가 발급한 짧은 scoped capability를 사용한다. claim에는 audience, session_id, run_id, actor, allowed_tools, delegation_id, expiry(최대 120초)를 담는다. capability는 모델 context에 넣지 않는다. MCP 서버가 capability를 검증하고 호출 컨텍스트를 주입한다. body에 session_id가 있으면 claim과 일치해야 한다. business-mcp → gateway도 이 범위를 전달한다. report/observer는 별도 service actor로 public colleague 도구 목록과 분리한다.

## 5. 공개 HTTP API

기본 `/api/v1`. 아래 객체는 필수 필드만 표시했으며 공통 success는 지정한 본문 그대로다. 202 결과는 `run_id` 또는 `report_id`로 추적한다.

| Method / path | 요청 | 응답 / 권한 |
|---|---|---|
| POST `/auth/login` | `{email,password}` | 200 `{user:{id,role},csrf_token}` + 쿠키 / 공개 |
| POST `/auth/exchange` | `{token}` | 200 `{session_id,csrf_token}` + 쿠키 / 공개 |
| POST `/auth/logout` | `{}` | 204 / 로그인 |
| GET `/auth/me` | 없음 | 200 `{id,role,session_id?,csrf_token}` |
| POST `/invites` | `{alias}` | 201 `{invite_id,invite_url,expires_at}` / ADMIN |
| GET `/sessions` | `cursor?` | 200 `{items:[{id,alias,status,report_status}],next_cursor}` / ADMIN |
| GET `/sessions/{sid}` | 없음 | 200 `{session,artifact,tasks,messages,active_run,approvals}` / 소유자 |
| POST `/sessions/{sid}/start` | `{consent:true}` | 200 `{session}`; 중복 start는 기존 응답 / CANDIDATE |
| POST `/sessions/{sid}/messages` | `{client_message_id,channel,content}` | 202 `{message_id,run_id}` / CANDIDATE |
| GET `/sessions/{sid}/documents` | 없음 | 200 `{items:[{id,title,version}]}` / 소유자 |
| GET `/sessions/{sid}/documents/{docId}` | 없음 | 200 `{id,title,version,body}` + 열람 action / 소유자 |
| PATCH `/sessions/{sid}/artifact` | `{base_version,section,content,source_refs:EvidenceRef[]}` | 200 `{artifact}` / CANDIDATE 직접 편집 |
| POST `/sessions/{sid}/split` | `{decision:'ACCEPT'|'ADJUST',assignments:{section:'CANDIDATE'|'COLLEAGUE'|'JOINT'},comment}` | 200 `{split}`; ADJUST 최대 3회, ACCEPT는 마지막 합의안으로만. 확정 시 태스크 담당 반영, 동료 담당 섹션마다 delegation+DELEGATED run 생성 / CANDIDATE |
| POST `/sessions/{sid}/demo/advance` | `{to_event}` | 200 `{fired,elapsed_min}`; 시험 시계 offset 이동 후 도래 이벤트 발생. APP_ENV=development 전용, 지원자 화면 비노출 / ADMIN |
| DELETE `/sessions/{sid}/delegations/{did}` | 없음 | 204, 미실행 승인 폐기·run 취소 / CANDIDATE |
| PATCH `/sessions/{sid}/tasks/{tid}` | `{base_version,status}` | 200 `{task}` / 자기 담당 CANDIDATE |
| POST `/sessions/{sid}/tasks/{tid}/review` | `{decision:'ACCEPT'|'REVISE'|'REJECT',comment,source_refs:EvidenceRef[]}` | 200 `{task}` / CANDIDATE |
| POST `/sessions/{sid}/approvals/{aid}/decision` | `{decision:'APPROVE'|'REJECT'}` | 202 `{run_id,status}` / 해당 세션 CANDIDATE |
| POST `/sessions/{sid}/submit` | `{base_version,summary}` | 202 `{session_status:'SUBMITTED',report_id}` / CANDIDATE |
| GET `/sessions/{sid}/events` | `after_seq?` | 200 SSE / 소유자 |
| GET `/runs/{rid}` | 없음 | 200 `{id,status,error?,result?}` / 소유자 |
| POST `/runs/{rid}/retry` | `{}` | 202 `{run_id}`; FAILED만 가능, 승인과 변경은 새로 생성 / CANDIDATE |
| GET `/sessions/{sid}/debrief` | 없음 | 200 `{occurred_events,not_triggered,recording_notice}` / 소유자, 제출 후 |
| GET `/reports/{sid}` | 없음 | 200 `{status,body?}` / ADMIN |
| POST `/reports/{sid}/retry` | `{}` | 202 `{report_id}` / ADMIN, FAILED만 |
| GET `/health` | 없음 | 200 `{status,db,agent,mcp,mode}` / 로컬 점검 |

직접 편집은 Agent 승인이 필요 없지만 이력·버전 검사는 동일하다. 도구 실행을 요청한 채팅의 response에는 조사 결과나 ‘위임 제안 카드’를 붙일 수 있다. 제안 구조는 `{source_message_id,title,target_section,allowed_tools,filters}`이고 사용자가 확인하기 전에는 delegation·변경이 생성되지 않는다. 어시스턴트는 TEAM과 별도 channel과 run kind이며 read-only 도구만 제공한다.

HTTP 오류: 400 INVALID_REQUEST, 401 UNAUTHENTICATED, 403 FORBIDDEN, 404 NOT_FOUND(타인 세션 포함), 409 VERSION_CONFLICT/RUN_BUSY/ALREADY_USED/APPROVAL_STALE, 410 INVITE_EXPIRED/APPROVAL_EXPIRED, 422 VALIDATION_ERROR, 429 RATE_LIMITED, 503 UPSTREAM_UNAVAILABLE. 오류 본문은 ErrorBody. validation 상세에 내부 secrets/SQL을 포함하지 않는다.

위임 생성의 Idempotency-Key는 브라우저가 UUID로 만들며 action payload에 요청 hash와 응답 ID를 보관한다. DELEGATION_CREATED action의 `(session_id, payload->>'idempotency_key')`에 partial unique index를 둔다. 같은 key와 같은 요청은 기존 결과를 반환하고 다른 요청은 409다. messages의 client_message_id도 같은 방식으로 기존 message/run을 반환한다. cookie 인증/CSRF는 frontend proxy를 경유한 smoke_flow에도 적용한다.

내부 API도 gateway가 계약을 검증하며 브라우저 쿠키만으로 호출할 수 없다.

| Method / internal path | 입력 → 출력 |
|---|---|
| POST `/internal/v1/jobs/claim` | `{worker_id,kinds}` → `{job:null|{id,kind,session_id,run_id,input,lease_until}}`; service 인증, 단일 lease |
| POST `/internal/v1/jobs/{jid}/complete` | `{worker_id,outcome,result?,error?}` → `{status}`; lease 소유자 확인 |
| POST `/internal/v1/runs/{rid}/proposal` | `{interrupt_id,tool_name,args,base_versions,delegation_id}` → `{approval_id,args_hash,expires_at}`; 동일 interrupt 멱등 |
| POST `/internal/v1/runs/{rid}/events` | `{client_event_id,type,payload}` → `{seq}`; event ID 중복 제거 |
| POST `/internal/v1/mcp/{tool_name}` | 모델 입력 + 인증 context → 위 MCP 공통 출력; 서버 검증 후 업무 transaction |
| POST `/internal/v1/reports/{sid}/complete` | `{run_id,source_snapshot,body}` → `{report_id,status}`; 고정 snapshot·근거 검사 |

내부 event 입력의 중복 제거를 위해 stream_events에 `client_event_id text nullable` 및 `(run_id,client_event_id)` unique를 추가한다. worker의 상태/trace 보고 역시 이 경로를 사용하며 agent가 업무 테이블을 직접 수정하지 않는다. claim 응답용 MCP capability는 agent가 해당 run을 시작할 때 service 인증으로 요청하고 gateway가 DB 권한에 맞춰 발급한다(`POST /internal/v1/runs/{rid}/capability`, `{audience}` → `{token,expires_at}`).

## 6. SSE 계약

`id: {session_seq}` / `event: {type}` / `data: {JSON}`. data 공통 필드는 `{event_id,seq,session_id,run_id,occurred_at,payload}`. keepalive는 15초 간격 comment. Last-Event-ID 또는 after_seq 중 큰 값을 검증 후 사용. DB 보관 이벤트를 seq 순서로 재전송하고 client는 seq로 중복 제거한다. proxy 캐시 금지, `text/event-stream`, buffering 금지.

| type | payload |
|---|---|
| RUN_STARTED | `{kind}` |
| TOOL_START | `{tool_call_id,display_name}`; 비공개 args 제외 |
| TOOL_END | `{tool_call_id,outcome,citations}` |
| COLLEAGUE_MESSAGE / MANAGER_EVENT / ASSISTANT_MESSAGE | `{message_id,content,citations}` |
| APPROVAL_REQUIRED | `{approval_id,task_id,tool_name,before,after,expires_at}` |
| TASK_UPDATED | `{task}` |
| ARTIFACT_UPDATED | `{version,changed_sections}` |
| DONE / FAILED | `{status,error_code?}`; run 단위 종료 |
| SESSION_DONE | `{report_id}` |
| REPORT_READY / REPORT_FAILED | `{report_id}`; CANDIDATE에는 내용 없음 |

P0는 완성 메시지만 전송하고 TOKEN 단위 전송은 P1. SSE는 권한에 따라 admin_payload를 필터링한다. 내부 관찰 해석·미발생 이벤트 조건·예산·모델 프롬프트는 지원자 스트림에 보내지 않는다.

## 7. MCP 계약

두 서버 모두 실제 MCP initialize → initialized → tools/list → tools/call을 SDK client로 수행한다. `/mcp`라는 REST 경로만 만들어 MCP라고 부르지 않는다. rag는 resources/templates/list, resources/read도 지원한다. 아래 session/actor context는 인증에서 얻고 모델 입력에는 넣지 않는다.

도구 출력 공통: `{ok:boolean,data:object|null,error:{code,message,retryable}|null,citations:Citation[]}`. SDK CallToolResult의 text content에 JSON 직렬화하고 지원 버전에서는 structuredContent도 같은 객체로 제공한다. 도구 실행의 업무 오류는 `isError:true`, 인자 형식/알 수 없는 도구 같은 프로토콜 오류는 MCP SDK의 JSON-RPC 오류로 전달한다. annotations는 힌트일 뿐 권한 검사의 대체물이 아니다.

교안 72쪽에 따라 변경 도구는 annotations에 `readOnlyHint:false, destructiveHint:true`를 명시한다. 조회 도구는 `readOnlyHint:true, destructiveHint:false`다. MCP client adapter는 업무 오류도 같은 tool_call_id의 LangChain ToolMessage로 모델에 돌려주며, 길이 제한과 민감정보 마스킹을 거친다. 도구 설명에는 목적·인자·단위·제약·오류를 포함한다. 이 metadata만 보고 자동 승인하지 않는다.

### business-mcp

| 도구 | 모델 입력 JSON | data 출력 | 제약 |
|---|---|---|---|
| `get_session_context` | `{}` | `{public_brief,phase,tasks,artifact_version}` | actor에 맞는 공개 DTO만 |
| `get_rejoin_metrics` | `{dimension:'overall'|'group_size',filters:{group_size?:'small'|'medium'|'large'}}` | `{rows:[{segment,label,first_time_participants,rejoined_within_30d,rejoin_rate}],unit,monthly_active_users,source_version}` | filter 값은 seed enum, 임의 SQL 금지 |
| `get_interview_notes` | `{tags:string[],limit:int}` | `{items:[{id,group_size,tags,quote}],sampling_note}` | tags 최대 3, limit 1~8. 01:05 공개 전 NOT_FOUND. 의견 비중 일반화 금지 |
| `update_task_status` | `{task_id,base_version,status:'IN_PROGRESS'|'REVIEW'}` | `{task}` | 동료 담당/위임 task만, 변경별 승인 |
| `patch_artifact_section` | `{task_id,section,base_version,content,citations:Citation[]}` | `{artifact_id,version,revision_id}` | 분담 확정된 동료 담당 섹션(delegation.section_allowlist)만, 승인별 args 고정 |

business-mcp는 각 도구를 gateway `/internal/v1/mcp/{tool_name}`로 전달한다. timeout 5초. 조회 실패 재시도 최대 2회. 변경은 operation_id가 있을 때만 동일 요청 재시도 가능하다. 승인된 변경 tool 호출에는 모델 입력 외에 server context `{approval_id,operation_id,args_hash,capability}`가 붙는다. gateway는 approval 상태·hash·범위·기준 버전을 다시 검사하고 receipt를 transaction에 저장한다. task_status=REVIEW가 Agent 작업 완료이며 최종 DONE 결정은 지원자 review API만 할 수 있다.

### rag-mcp

| 제공 기능 | 입력 | 출력/규칙 |
|---|---|---|
| Tool `search_docs` | `{query:string,document_ids?:string[],top_k:int}` | `{matches:[{document_id,chunk_id,title,version,quote,score}],search_mode:'vector'|'keyword_fallback',embedding_model,index_version}` + citations. top_k 1~5 |
| Resource template | `doc://{scenario_id}/{document_id}` | `{uri,mimeType:'text/markdown',text}`. 문서 버전·제목을 원문 상단에 포함 |

P0 검색은 query를 색인과 같은 model/revision으로 임베딩하고 `1 - cosine_distance`를 score로 반환한다. scenario_id·document_ids·index_version 권한 필터를 적용한 뒤 similarity 내림차순, 동점은 document_id/ordinal로 정렬한다. 색인 없음/모델 불일치는 INDEX_NOT_READY/MODEL_MISMATCH로 실패한다. 원문은 checksum으로 버전을 고정한다. 평가 기준 검색 도구나 비공개 정책 Resource는 공개 Agent에 제공하지 않는다.

개발용 명시적 RAG_MODE=keyword_fallback일 때만 기존 토큰/keyword 일치 검색을 사용한다. search_mode와 health/UI에 fallback을 표시하고 AT-16은 미통과로 남긴다. 무조건 top-k 반환으로 관련 없는 청크를 근거 삼지 않도록 과제 평가셋에서 score 임계값을 고정한다. 문서 없음/필터 결과 0건은 matches=[]로 반환한다. Resource는 모델이 직접 고르는 tool이 아니므로 Host가 source panel 열람 또는 제한된 read_resource adapter로 읽어 context에 주입하고 호출 이력을 남긴다.

MCP 오류 코드: NOT_FOUND, FORBIDDEN, INVALID_ARGUMENT, OUT_OF_SCOPE, APPROVAL_REQUIRED, APPROVAL_EXPIRED, VERSION_CONFLICT, INDEX_NOT_READY, MODEL_MISMATCH, TIMEOUT, RATE_LIMITED, INTERNAL_ERROR. 실패 기록에 run_id/tool_call_id를 연결한다. query 인젝션 또는 문서의 “정책 무시” 지시는 데이터로만 취급하고 허용 도구 목록을 바꾸지 않는다.

## 8. Agent State와 Graph

```python
class WorkState(TypedDict):
    session_id: str
    run_id: str
    task_id: str | None
    kind: str
    phase: str
    source_message_id: str | None
    message_ids: list[str]
    context_summary: dict | None  # text, source_ids, prompt_version
    facts: dict
    tool_results: list[dict]
    citations: list[dict]
    proposed_action: dict | None
    approval_id: str | None
    delegation_id: str | None
    help_id: str
    policy_version: str
    step_count: int
    tool_counts: dict[str, int]
    active_execution_ms: int
    output_rewrite_count: int
    retries: int
    error_code: str | None
```

```text
(구현: services/agent/app/graph.py build())
START → load_context → classify_request → select_help → reason
reason ─┬─ 도구 필요(plan 있음) → call_mcp ─┬─ (live) reason  … 단계 8 / 도구 5 / 같은 도구 3 / 120초 한도 내 반복
        │                                   ├─ 일반 응답 → validate_output → respond → END
        │                                   └─ 위임 작업 → draft_delegation
        ├─ 일반 응답 → validate_output → respond → END
        └─ 위임 작업(DELEGATED) → draft_delegation → persist_proposal → await_approval(interrupt)
                 await_approval ─┬─ APPROVE → execute_write(MCP patch_artifact_section) → respond → END
                                 └─ REJECT / REVISE → record_rejection → respond → END
```

classify_request 의도(코드 규칙, 허용 범위는 코드가 판단): `delegated`(분담·수정 작업 run) · `policy_recheck`(01:30 오류 지적 → 운영 정책 원문 재확인 후 정정) · `revise_request`(채팅 수정·초안 요청 → 실제 재작성 run 생성) · `feedback`(작성 섹션 피드백) · `answer_request`(정답 요구 → 자료 범위 질문) · `investigate`(MCP 조사) · `conversation`.
draft_delegation은 섹션 본문 전용 작성 단계(section-writer 프롬프트)로, 수정 요청이면 섹션 전체 재작성, 지원자 채팅 제안은 필수 반영 검사 후 누락 시 재작성·보정한다.
시나리오 이벤트(00:10 분담 ~ 02:00 자동 제출)는 Graph 노드가 아니라 gateway 시험 시계(`gateway/app/timeline.py`, agent ticker가 2초마다 tick)가 서버에서 발생시킨다(v1.2의 evaluate_conditions/조건부 개입은 폐기).

각 사용자 명령은 별도 run, `thread_id = session_id + ':' + run_id`. session 전체 진행도는 sessions/actions가 소유하고 해당 run의 interrupt는 같은 thread_id와 checkpoint로 재개한다. 같은 채널(팀 채팅/어시스턴트)에 진행 중인 응답 run이 있을 때만 RUN_BUSY를 반환한다. 동료의 백그라운드 섹션 작업이 승인 대기 중이어도 채팅은 계속 가능하다. 지원자 직접 문서 편집과 승인/거절/위임 취소/제출은 계속 가능하며 base_version을 갱신한다.

`classify_request`는 LLM 구조화 출력으로 조사/위임 제안/질문을 선택할 수 있지만 허용 scope·도움 조건·이벤트 발생은 코드가 판단한다. 실패 시 명시적 ‘자료 조사’ 버튼/위임 카드로 동일 기능을 수행한다. 계획 자체를 지원자 대신 완성하는 action은 schema에 존재하지 않는다.

interrupt 전 `persist_proposal` 노드에서 approval을 idempotent하게 생성한다. 다음 노드는 `interrupt({approval_id,...})`만 수행하며 전후에 비멱등 쓰기를 섞지 않는다. 재개는 `Command(resume=decision)`와 같은 thread_id를 사용한다. 승인 대상 args는 사용자가 수정할 수 없고 바뀌면 새 제안·새 승인이 필요하다. interrupt 대기 시간은 120초 run 실행 예산에서 제외하되 approval은 생성 후 10분 만료한다.

승인 결정은 PENDING만 CAS 변경 가능. 재개 시 현재 소유권·delegation·session ACTIVE·base_version·args_hash·만료를 재검사한다. 승인 중 문서 수정은 APPROVAL_STALE로 종료하고 재조사 제안을 돌려준다. 승인 응답 재전송은 같은 결정이면 현재 run 상태를 반환하고 다른 결정이면 409. mutation receipt가 있으면 중복 적용하지 않는다.

task 상태: TODO → IN_PROGRESS → REVIEW → DONE. REVIEW에서 REVISE는 IN_PROGRESS로 되돌리고 새 run, REJECT는 CANCELLED. Agent는 DONE/자기 권한 확대를 할 수 없다. 지원자 task는 TODO→IN_PROGRESS→DONE 직접 변경 가능. 이외 전이는 409. phase REVIEW는 지원자가 검토/제출 준비를 선택한 표시이며 조건부 이벤트를 모두 소모해야 넘어가는 관문이 아니다.

## 9. Harness 8요소

| 요소 | P0 구현 규칙 |
|---|---|
| Instructions | `prompts/colleague-v1.md`, `assistant-v1.md`, `report-v1.md`, `summary-v1.md`로 역할·금지·도구 규칙·출력 형식을 버전 관리. Python 코드에 장문 system prompt 직접 삽입 금지 |
| Tools | run 종류별 allowlist, read/write 분리, session/위임 범위 서버 검증. 도구 결과 1500 tokens 제한·오류 ToolMessage·개인정보 마스킹. 승인 없이 실제 write 금지 |
| Context | 입력 총 6000 tokens, 출력 1200 tokens. 최근 메시지 최대 12개 + public brief + 청크 최대 5개 + 해당 위임. 초과하면 오래된 대화를 출처 ID 포함 800 tokens 이하로 요약하고 재측정, 그래도 초과하면 오래된 검색 청크부터 제외. 비공개 평가 해석·타 세션 내용 제외 |
| State/Memory | PostgreSQL checkpoint, immutable 업무 원문, source refs. 프로세스 재시작 후 승인 대기 run 조회 |
| Agent Loop | 활성 실행 120초, reasoning/tool cycle 최대 8회, 도구 호출 총 5회·같은 도구 최대 3회, 응답 출력 최대 1200 tokens. 한도 초과는 LIMITED 응답과 저장 |
| Guardrails | scope+도움 잠금+approval+버전 검사, 출력 schema와 인용 검증, 판정/정답 생성 차단. 이메일/전화는 trace·외부 prompt 직전 마스킹 |
| Recovery | 429/503/timeout 최초+2회 재시도, 1s/2s jitter·120초 잔여 예산. 다른 모델 전환 없음. 실패 시 명확한 FAILED와 재시도 |
| Observability | P0 LangSmith 연동, 메시지·로그·trace에 같은 trace_id. node/tool/approval/policy/latency/token usage/실패와 trace URL 저장. 비용은 모델 usage×버전 관리 단가로 계산 가능한 때만 추정 표시, 단가 없으면 null. 키 없으면 로컬 로그로 개발 지속하되 AT-17 LangSmith 증빙 미완료. 원문 프롬프트·비밀값은 공개 SSE 제외 |

무한 자동 교정은 금지한다. 출력 검증 실패 시 1회 재작성, 또 실패하면 정적 안전 응답(“확인할 자료 범위를 선택해 주세요”)과 오류 기록. 비즈니스 숫자는 tool 결과 또는 문서 인용에 없는 경우 생성 금지. 같은 검색 키로 세 번 실패하면 다른 수치로 추정하지 않는다. 도움 목록과 정책을 프롬프트로만 통제하지 않는다.

Evaluation은 관측과 별개로 구현한다(교안 69·72쪽). 고정 평가셋에 8요소 각각의 테스트를 연결하고 정책/프롬프트/한도 변경 전후 결과를 JSON으로 저장한다. 같은 오류 주입 스크립트로 반복 가능해야 한다. Context 요약은 사실·원문 ID만 보존하며 지원자의 의도/성격을 추가 추론하지 않는다. 요약 호출도 활성 시간/토큰/비용에 합산한다. 위 6000/1200/1500/800 token 값과 도구 총 5회 상한은 자체 선택이며 교안의 고정 수치라고 주장하지 않는다.

## 10. 제출·리포트·복구

submit은 session row lock → base_version 검사 → SUBMITTED/최종 artifact revision 고정 → 진행 run CANCELLED·승인 EXPIRED·delegation revoked → report row와 REPORT job → SESSION_DONE을 한 transaction에 저장한다. 직전 변경 도구와 경합하면 먼저 lock을 얻은 transaction만 유효 상태에서 실행한다. 재제출은 기존 report_id를 반환하며 새 작업을 만들지 않는다.

report job은 source_snapshot에 message/revision/action/tool/event ID를 고정한다. 사실 지표·발생 기회는 코드로 구성하고 LLM은 설명·가설만 생성한다. 모든 quote는 원문에서 검증하고 맞지 않는 evidence는 제거한다. 항목별 근거가 없으면 상태를 표시한다. LLM 실패 시 규칙 기반 사실 리포트를 만들고 `generation_mode:'RULES_FALLBACK'`를 표시한다. 사실 리포트도 실패하면 FAILED. 생성 시도 총 3회, report_id가 멱등키다.

```json
{
  "schema_version":"2.0","generation_mode":"LLM_WITH_RULES",
  "policy_version":"exam-v1","scenario_id":"moarun-rejoin-v1","submitted_by":"CANDIDATE",
  "timeline":[{"event_id":"T-ERROR","at":"01:30","situation":"동료가 운영 정책과 충돌하는 유료 멤버십 기능을 제안함"}],
  "areas":[{"dimension":"RESPECT_COMMUNICATION","label":"존중·소통","status":"OBSERVED",
            "situations":[{"event_id":"T-ERROR","situation":"…","status":"OBSERVED","at":"01:30"}],
            "facts":[{"text":"팀 채팅에 메시지: “운영 정책에 올해 유료 기능은…”","at":"01:31","refs":[{"kind":"message","id":"…","field":"content","start":0,"end":40,"quote":"…"}]}],
            "interpretation":{"text":"정책 근거를 들어 오류를 전달했을 가능성","label":"INFERENCE"},"limits":"…"}],
  "split_history":[{"kind":"SPLIT_CONFIRMED","assignments":{},"at":"00:12"}],
  "limitations":["단일 가상 과제에서 관찰한 행동이며 성격·채용 성과를 단정하지 않음"]
}
```

위 JSON은 필드 형식 예시다. 실제 OBSERVED 항목 facts는 유효 EvidenceRef 1개 이상이어야 한다. status는 OBSERVED/NO_OPPORTUNITY/INSUFFICIENT_EVIDENCE/NOT_USED. areas는 책임감·존중소통·협력·유연성·AI 활용 5개이며 각 facts에는 이벤트 이후 다음 이벤트 전까지의 실제 지원자 행동과 시각을 담는다. 점수·등급·순위·합불 필드는 없다.

jobs claim은 `FOR UPDATE SKIP LOCKED`로 단일 lease(150초)를 부여한다. 만료 job은 worker가 checkpoint/receipt를 조회하고 재개한다. WAITING_APPROVAL는 job을 DONE으로 바꾸며 승인 API가 같은 run의 job을 QUEUED로 갱신하고 resume 입력을 저장한다. run_id unique job은 새 row를 중복 생성하지 않는다. 시나리오 이벤트는 job이 아니라 agent ticker가 2초마다 호출하는 내부 `POST /internal/v1/timeline/tick`에서 세션 row lock 아래 발생시킨다(세션당 이벤트 1회, 02:00 자동 제출 포함). REPORT job도 전용 REPORT run을 만든다. 각 node의 활성 실행 시간을 checkpoint에 누적하고 승인 대기 시간을 빼서 총 120초 예산을 재개 후에도 유지한다. 프로세스 재시작 시 PENDING 승인은 만료 검사 후 UI에 복원하며 자동 승인하지 않는다. SSE 이벤트도 DB에서 복원한다.

## 11. 품질 속성과 검증 연결 (ISO/IEC 25010 8특성)

| 품질 특성 | 설계 선택 | 검증(evidence/verification.md) |
|---|---|---|
| 기능 적합성 | 입장→분담→조사→섹션 초안·승인→제출→근거 리포트, 시험 시계 이벤트 9개 | AT-01~07, AT-13 · smoke_flow live 44/44 |
| 성능 효율성 | 작은 context(입력 6000/출력 1200 tokens), 조회 상한(top-k 5, 결과 1500 tokens), exact 벡터 검색, 단일 worker | 로컬 seed 기준 일반 저장 응답 1초 이내 목표(LLM 지연 제외) |
| 호환성 | 서비스 간 표준 계약(MCP Streamable HTTP, REST, SSE), 공통 도구 출력 `{ok,data,error,citations}` | smoke_mcp 22/22(SDK initialize/list/call/read) |
| 사용성 | 저장 상태·승인 전후 비교·출처 원문 이동·오류 재시도, DESIGN_GUIDE 토큰·접근성 | AT-15(부분), 화면 캡처 evidence/screens |
| 신뢰성 | PostgreSQL checkpoint, job lease, 멱등 receipt, SSE replay, 섹션 단위 stale 판정 | AT-08(재시작 재개 PASS), AT-09, AT-10(부분) |
| 보안성 | role/session scope, 초대 토큰 hash, CSRF·Origin, 120초 scoped capability, 최소 권한 DB role, 제출 후 재열람 차단 | AT-11, AT-12 |
| 유지보수성 | typed 계약, 시나리오 데이터·정책 분리, 버전 관리 프롬프트, Harness 평가셋 | eval_harness 8/8, 단위·통합 테스트 |
| 이식성 | 서비스별 Dockerfile·Compose, 환경변수 설정, 로컬 임베딩 모델 | Compose 문법 검증(빌드·기동은 NOT_RUN) |

## 12. 참고한 기술 원문

MCP 서버/도구/Resource는 [공식 MCP 서버 문서](https://modelcontextprotocol.io/docs/develop/build-server)를 확인했다. interrupt와 같은 thread 재개·체크포인트·재실행 시 부작용 주의는 [LangGraph interrupt 문서](https://docs.langchain.com/oss/python/langgraph/interrupts)를 확인했다. 이 문서의 업무 API·권한·정책은 Day Zero 구현을 위한 자체 계약이며 라이브러리 기본 동작으로 간주하지 않는다.

과제 기준은 사용자 제공 `AI-Agent Capstone(+MCP).pdf`의 29·33·47~66·69~73쪽이다. 임베딩 모델의 384차원 및 사용 방식은 [모델 배포자 카드](https://huggingface.co/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2)에서 확인했다. 이 모델 선택은 교안 요구가 아닌 마감용 구현 결정이다.

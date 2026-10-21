-- Day Zero schema (ARCHITECTURE §3) — 핏모아 sc-a 턴 기반 협업 시뮬레이션. Applied by alembic revision 0001_fitmoa_initial.
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE companies (id uuid PRIMARY KEY DEFAULT gen_random_uuid(), name text NOT NULL);

CREATE TABLE users (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id uuid NOT NULL REFERENCES companies(id),
  email text NOT NULL UNIQUE,
  password_hash text NOT NULL,
  role text NOT NULL CHECK (role = 'ADMIN')
);

-- definition: data/fitmoa-invite-v1/scenario.json 전체(planted_errors 포함, 지원자 API로는 내보내지 않음)
CREATE TABLE scenarios (
  id text PRIMARY KEY, scenario_key text NOT NULL, version int NOT NULL, title text NOT NULL,
  definition jsonb NOT NULL, fixes jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE participants (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id uuid NOT NULL REFERENCES companies(id),
  alias text NOT NULL,
  session_id uuid UNIQUE
);

-- scenario_state: 턴 엔진 상태(active_event, awaiting, colleague, pushback, split, flags)
CREATE TABLE sessions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id uuid NOT NULL REFERENCES companies(id),
  participant_id uuid NOT NULL REFERENCES participants(id) DEFERRABLE INITIALLY DEFERRED,
  scenario_id text NOT NULL REFERENCES scenarios(id),
  scenario_version int NOT NULL,
  status text NOT NULL DEFAULT 'CREATED' CHECK (status IN ('CREATED','ACTIVE','SUBMITTED')),
  phase text NOT NULL DEFAULT 'BRIEF' CHECK (phase IN ('BRIEF','WORK','CLOSED')),
  consent_at timestamptz, started_at timestamptz, submitted_at timestamptz,
  version int NOT NULL DEFAULT 1,
  turn_count int NOT NULL DEFAULT 0,
  clock_offset_seconds int NOT NULL DEFAULT 0,
  last_action_seq bigint NOT NULL DEFAULT 0,
  last_stream_seq bigint NOT NULL DEFAULT 0,
  scenario_state jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE participants ADD CONSTRAINT participants_session_fk
  FOREIGN KEY (session_id) REFERENCES sessions(id) DEFERRABLE INITIALLY DEFERRED;

CREATE TABLE invites (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id uuid NOT NULL REFERENCES companies(id),
  alias text NOT NULL,
  token_hash text NOT NULL UNIQUE,
  expires_at timestamptz NOT NULL,
  consumed_at timestamptz,
  session_id uuid UNIQUE REFERENCES sessions(id)
);

-- meta.kind: SCENARIO_EVENT(이벤트 고정 대사) | SCENARIO_BRANCH(분기 고정 대사) | REMINDER | 없음(LLM 응답)
CREATE TABLE messages (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id uuid NOT NULL REFERENCES sessions(id),
  channel text NOT NULL CHECK (channel = 'TEAM'),
  actor text NOT NULL CHECK (actor IN ('CANDIDATE','COLLEAGUE','MANAGER','SYSTEM')),
  content text NOT NULL CHECK (char_length(content) <= 8000),
  citations jsonb NOT NULL DEFAULT '[]'::jsonb,
  meta jsonb NOT NULL DEFAULT '{}'::jsonb,
  turn int NOT NULL DEFAULT 0,
  source_run_id uuid,
  client_message_id text,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (session_id, client_message_id)
);

-- 산출물 단위: T1 안내문, T2 FAQ(서윤 초안 2개에서 시작), T3 리워드·일정 표(서윤 초안), T5 푸시(E2), T4 팀장 보고(E4)
CREATE TABLE artifacts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id uuid NOT NULL REFERENCES sessions(id),
  key text NOT NULL,
  title text NOT NULL,
  body text NOT NULL DEFAULT '',
  initial_body text NOT NULL DEFAULT '',
  version int NOT NULL DEFAULT 1,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (session_id, key)
);

CREATE TABLE artifact_revisions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id uuid NOT NULL REFERENCES sessions(id),
  artifact_id uuid NOT NULL REFERENCES artifacts(id),
  version int NOT NULL,
  body_before text NOT NULL,
  body_after text NOT NULL,
  actor text NOT NULL CHECK (actor IN ('CANDIDATE','COLLEAGUE','SYSTEM')),
  run_id uuid,
  turn int NOT NULL DEFAULT 0,
  meta jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (artifact_id, version)
);

CREATE TABLE tasks (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id uuid NOT NULL REFERENCES sessions(id),
  key text NOT NULL,
  title text NOT NULL CHECK (char_length(title) <= 160),
  status text NOT NULL CHECK (status IN ('TODO','IN_PROGRESS','DONE')),
  owner text NOT NULL CHECK (owner IN ('UNASSIGNED','CANDIDATE','COLLEAGUE','SPLIT')),
  eta text CHECK (eta IS NULL OR char_length(eta) <= 20),
  note text,
  version int NOT NULL DEFAULT 1,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (session_id, key)
);

CREATE TABLE runs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id uuid NOT NULL REFERENCES sessions(id),
  thread_id text NOT NULL UNIQUE,
  kind text NOT NULL CHECK (kind IN ('TEAM','REPORT')),
  status text NOT NULL CHECK (status IN ('QUEUED','RUNNING','WAITING_APPROVAL','SUCCEEDED','FAILED','CANCELLED')),
  source_message_id uuid,
  input jsonb NOT NULL DEFAULT '{}'::jsonb,
  result jsonb,
  policy_version text NOT NULL, prompt_version text NOT NULL,
  trace_id text NOT NULL, trace_url text,
  token_usage jsonb NOT NULL DEFAULT '{}'::jsonb,
  error_code text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE approvals (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id uuid NOT NULL REFERENCES sessions(id),
  run_id uuid NOT NULL REFERENCES runs(id),
  interrupt_id text NOT NULL,
  tool_name text NOT NULL,
  args jsonb NOT NULL,
  args_hash text NOT NULL,
  base_versions jsonb NOT NULL,
  before_after jsonb NOT NULL DEFAULT '{}'::jsonb,
  status text NOT NULL CHECK (status IN ('PENDING','APPROVED','REJECTED','EXPIRED','APPLIED')),
  expires_at timestamptz NOT NULL,
  decided_at timestamptz,
  decision_actor_id uuid,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (run_id, interrupt_id)
);

CREATE TABLE mutation_receipts (
  operation_id text PRIMARY KEY,
  session_id uuid NOT NULL REFERENCES sessions(id),
  approval_id uuid NOT NULL UNIQUE REFERENCES approvals(id),
  result jsonb NOT NULL,
  applied_at timestamptz NOT NULL DEFAULT now()
);

-- PUBLIC: 지원자 공유 문서 4개 / INTERNAL: 관찰 코드북(search_criteria 전용)
CREATE TABLE documents (
  id text PRIMARY KEY, scenario_id text NOT NULL REFERENCES scenarios(id),
  version int NOT NULL, title text NOT NULL, body text NOT NULL,
  visibility text NOT NULL CHECK (visibility IN ('PUBLIC','INTERNAL')), checksum text NOT NULL,
  ordinal int NOT NULL DEFAULT 0
);

CREATE TABLE document_chunks (
  id text PRIMARY KEY,
  document_id text NOT NULL REFERENCES documents(id),
  document_version int NOT NULL,
  ordinal int NOT NULL,
  body text NOT NULL CHECK (char_length(body) <= 1500),
  char_start int NOT NULL, char_end int NOT NULL,
  embedding vector(384) NOT NULL,
  embedding_model text NOT NULL,
  embedding_revision text NOT NULL,
  embedding_dimension int NOT NULL CHECK (embedding_dimension = 384),
  index_version text NOT NULL,
  UNIQUE (document_id, document_version, ordinal, index_version)
);

-- 세션당 이벤트 1회. skipped=true면 조건 불충족(E2B) 또는 optional 비활성(E4)으로 건너뜀
CREATE TABLE event_occurrences (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id uuid NOT NULL REFERENCES sessions(id),
  event_id text NOT NULL,
  turn int NOT NULL,
  elapsed_seconds int NOT NULL,
  occurrence_mode text NOT NULL DEFAULT 'on_action' CHECK (occurrence_mode IN ('on_action','forced')),
  skipped boolean NOT NULL DEFAULT false,
  facts jsonb NOT NULL DEFAULT '{}'::jsonb,
  first_message_id uuid,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (session_id, event_id)
);

CREATE TABLE actions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id uuid NOT NULL REFERENCES sessions(id),
  seq bigint NOT NULL, actor text NOT NULL, kind text NOT NULL,
  entity_id text, payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  turn int NOT NULL DEFAULT 0,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (session_id, seq)
);

-- 관찰 기록: 코드북(criteria.md) 코드 + 근거 참조만. 점수·판정 없음
CREATE TABLE observations (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id uuid NOT NULL REFERENCES sessions(id),
  code text NOT NULL,
  competency text NOT NULL CHECK (competency IN ('RESPONSIBILITY','PLANNING','ADAPTABILITY','COLLABORATION','HONESTY')),
  event_id text,
  subject text,
  evidence_ref jsonb NOT NULL DEFAULT '{}'::jsonb,
  note text,
  source text NOT NULL CHECK (source IN ('AGENT','RULES')),
  run_id uuid,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX observations_once ON observations (session_id, code, COALESCE(event_id, ''), COALESCE(subject, ''));

-- 약속 추적: 지원자가 시간·행동을 약속한 문장 → 종료 시 KEPT(RS+2)/BROKEN(RS-2) 판정
CREATE TABLE commitments (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id uuid NOT NULL REFERENCES sessions(id),
  message_id uuid NOT NULL REFERENCES messages(id),
  text text NOT NULL,
  event_id text,
  registered_turn int NOT NULL,
  status text NOT NULL DEFAULT 'OPEN' CHECK (status IN ('OPEN','KEPT','BROKEN')),
  resolution jsonb,
  resolved_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (session_id, message_id)
);

CREATE TABLE tool_calls (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id uuid NOT NULL REFERENCES sessions(id),
  run_id uuid NOT NULL REFERENCES runs(id),
  tool_name text NOT NULL, safe_args jsonb NOT NULL, result_summary jsonb NOT NULL,
  citations jsonb NOT NULL DEFAULT '[]'::jsonb,
  outcome text NOT NULL, duration_ms int NOT NULL DEFAULT 0,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE reports (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id uuid NOT NULL UNIQUE REFERENCES sessions(id),
  status text NOT NULL CHECK (status IN ('PENDING','RUNNING','READY','FAILED')),
  version int NOT NULL DEFAULT 1,
  source_snapshot jsonb NOT NULL,
  body jsonb, attempts int NOT NULL DEFAULT 0, error_code text
);

CREATE TABLE jobs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id uuid NOT NULL REFERENCES sessions(id),
  run_id uuid UNIQUE REFERENCES runs(id),
  dedupe_key text NOT NULL UNIQUE,
  kind text NOT NULL CHECK (kind IN ('AGENT','REPORT')),
  input jsonb NOT NULL DEFAULT '{}'::jsonb,
  status text NOT NULL CHECK (status IN ('QUEUED','LEASED','DONE','FAILED')),
  attempt int NOT NULL DEFAULT 0,
  available_at timestamptz NOT NULL DEFAULT now(),
  lease_until timestamptz, worker_id text,
  last_error text
);

CREATE TABLE stream_events (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id uuid NOT NULL REFERENCES sessions(id),
  seq bigint NOT NULL,
  run_id uuid,
  type text NOT NULL,
  public_payload jsonb NOT NULL,
  admin_payload jsonb,
  client_event_id text,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (session_id, seq),
  UNIQUE (run_id, client_event_id)
);

-- Least-privilege roles (ARCHITECTURE §1)
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'dayzero_rag') THEN
    CREATE ROLE dayzero_rag LOGIN PASSWORD 'local_demo_only'; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'dayzero_checkpoint') THEN
    CREATE ROLE dayzero_checkpoint LOGIN PASSWORD 'local_demo_only'; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'dayzero_indexer') THEN
    CREATE ROLE dayzero_indexer LOGIN PASSWORD 'local_demo_only'; END IF;
END $$;
GRANT SELECT ON documents, document_chunks TO dayzero_rag;
GRANT SELECT ON documents TO dayzero_indexer;
GRANT SELECT, INSERT, UPDATE, DELETE ON document_chunks TO dayzero_indexer;
CREATE SCHEMA IF NOT EXISTS checkpoints AUTHORIZATION dayzero_checkpoint;
ALTER ROLE dayzero_checkpoint SET search_path = checkpoints;

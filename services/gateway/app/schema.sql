-- Day Zero P0 schema (ARCHITECTURE §3). Applied by alembic revision 0001.
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

CREATE TABLE scenarios (
  id text PRIMARY KEY, version int NOT NULL, title text NOT NULL,
  public_brief jsonb NOT NULL, policy_version text NOT NULL
);

CREATE TABLE participants (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id uuid NOT NULL REFERENCES companies(id),
  alias text NOT NULL,
  session_id uuid UNIQUE
);

CREATE TABLE sessions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id uuid NOT NULL REFERENCES companies(id),
  participant_id uuid NOT NULL REFERENCES participants(id) DEFERRABLE INITIALLY DEFERRED,
  scenario_id text NOT NULL REFERENCES scenarios(id),
  scenario_version int NOT NULL,
  status text NOT NULL DEFAULT 'CREATED' CHECK (status IN ('CREATED','ACTIVE','SUBMITTED')),
  phase text NOT NULL DEFAULT 'BRIEF' CHECK (phase IN ('BRIEF','WORK','REVIEW','CLOSED')),
  consent_at timestamptz, started_at timestamptz, submitted_at timestamptz,
  version int NOT NULL DEFAULT 1,
  last_action_seq bigint NOT NULL DEFAULT 0,
  last_stream_seq bigint NOT NULL DEFAULT 0,
  auto_intervention_count int NOT NULL DEFAULT 0,
  policy_state jsonb NOT NULL DEFAULT '{}'::jsonb,
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

CREATE TABLE messages (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id uuid NOT NULL REFERENCES sessions(id),
  channel text NOT NULL CHECK (channel IN ('TEAM','ASSISTANT')),
  actor text NOT NULL CHECK (actor IN ('CANDIDATE','COLLEAGUE','MANAGER','ASSISTANT','SYSTEM')),
  content text NOT NULL CHECK (char_length(content) <= 8000),
  citations jsonb NOT NULL DEFAULT '[]'::jsonb,
  meta jsonb NOT NULL DEFAULT '{}'::jsonb,
  source_run_id uuid,
  client_message_id text,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (session_id, client_message_id)
);

CREATE TABLE artifacts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id uuid NOT NULL UNIQUE REFERENCES sessions(id),
  sections jsonb NOT NULL,
  version int NOT NULL DEFAULT 1
);

CREATE TABLE artifact_revisions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id uuid NOT NULL REFERENCES sessions(id),
  artifact_id uuid NOT NULL REFERENCES artifacts(id),
  version int NOT NULL,
  sections jsonb NOT NULL,
  changed_sections jsonb NOT NULL,
  actor text NOT NULL,
  run_id uuid,
  source_refs jsonb NOT NULL DEFAULT '[]'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (artifact_id, version)
);

CREATE TABLE tasks (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id uuid NOT NULL REFERENCES sessions(id),
  title text NOT NULL CHECK (char_length(title) <= 160),
  status text NOT NULL CHECK (status IN ('TODO','IN_PROGRESS','REVIEW','DONE','CANCELLED')),
  owner text NOT NULL CHECK (owner IN ('CANDIDATE','COLLEAGUE')),
  template_key text,
  target_section text,
  delegation_id uuid,
  result jsonb,
  version int NOT NULL DEFAULT 1,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE delegations (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id uuid NOT NULL REFERENCES sessions(id),
  task_id uuid NOT NULL REFERENCES tasks(id) DEFERRABLE INITIALLY DEFERRED,
  source_message_id uuid NOT NULL REFERENCES messages(id),
  tool_allowlist jsonb NOT NULL,
  section_allowlist jsonb NOT NULL,
  constraints jsonb NOT NULL DEFAULT '{}'::jsonb,
  expires_at timestamptz NOT NULL,
  revoked_at timestamptz,
  version int NOT NULL DEFAULT 1
);
ALTER TABLE tasks ADD CONSTRAINT tasks_delegation_fk
  FOREIGN KEY (delegation_id) REFERENCES delegations(id) DEFERRABLE INITIALLY DEFERRED;

CREATE TABLE runs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id uuid NOT NULL REFERENCES sessions(id),
  thread_id text NOT NULL UNIQUE,
  kind text NOT NULL CHECK (kind IN ('COLLEAGUE','ASSISTANT','DELEGATED','REPORT')),
  status text NOT NULL CHECK (status IN ('QUEUED','RUNNING','WAITING_APPROVAL','SUCCEEDED','FAILED','CANCELLED')),
  source_message_id uuid, task_id uuid,
  input jsonb NOT NULL DEFAULT '{}'::jsonb,
  result jsonb,
  policy_version text NOT NULL, prompt_version text NOT NULL,
  trace_id text NOT NULL, trace_url text,
  token_usage jsonb NOT NULL DEFAULT '{}'::jsonb,
  estimated_cost numeric, pricing_version text,
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
  delegation_id uuid,
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

CREATE TABLE documents (
  id text PRIMARY KEY, scenario_id text NOT NULL REFERENCES scenarios(id),
  version int NOT NULL, title text NOT NULL, body text NOT NULL,
  visibility text NOT NULL CHECK (visibility = 'PUBLIC'), checksum text NOT NULL,
  keywords jsonb NOT NULL DEFAULT '[]'::jsonb
);

CREATE TABLE document_chunks (
  id text PRIMARY KEY,
  document_id text NOT NULL REFERENCES documents(id),
  document_version int NOT NULL,
  ordinal int NOT NULL,
  body text NOT NULL CHECK (char_length(body) <= 1500),
  char_start int NOT NULL, char_end int NOT NULL,
  keywords jsonb NOT NULL DEFAULT '[]'::jsonb,
  embedding vector(384) NOT NULL,
  embedding_model text NOT NULL,
  embedding_revision text NOT NULL,
  embedding_dimension int NOT NULL CHECK (embedding_dimension = 384),
  index_version text NOT NULL,
  UNIQUE (document_id, document_version, ordinal, index_version)
);

CREATE TABLE funnel_facts (
  scenario_id text NOT NULL REFERENCES scenarios(id),
  dataset_version text NOT NULL, period text NOT NULL, device text NOT NULL,
  visitor text NOT NULL, cart_value text NOT NULL,
  cart_sessions int NOT NULL, checkout_sessions int NOT NULL, orders int NOT NULL,
  PRIMARY KEY (scenario_id, dataset_version, period, device, visitor, cart_value),
  CHECK (0 <= orders AND orders <= checkout_sessions AND checkout_sessions <= cart_sessions)
);

CREATE TABLE support_cases (
  id text PRIMARY KEY, scenario_id text NOT NULL REFERENCES scenarios(id),
  device text NOT NULL, visitor text NOT NULL, tags jsonb NOT NULL, quote text NOT NULL
);

CREATE TABLE scenario_events (
  id text PRIMARY KEY, policy_version text NOT NULL, predicate_key text NOT NULL,
  payload jsonb NOT NULL, priority int NOT NULL
);

CREATE TABLE event_occurrences (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id uuid NOT NULL REFERENCES sessions(id),
  event_id text NOT NULL REFERENCES scenario_events(id),
  trigger_action_seq bigint NOT NULL,
  facts jsonb NOT NULL,
  response_message_id uuid,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (session_id, event_id)
);

CREATE TABLE actions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id uuid NOT NULL REFERENCES sessions(id),
  seq bigint NOT NULL, actor text NOT NULL, kind text NOT NULL,
  entity_id text, payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (session_id, seq)
);
CREATE UNIQUE INDEX actions_delegation_idem ON actions (session_id, (payload->>'idempotency_key'))
  WHERE kind = 'DELEGATION_CREATED';

CREATE TABLE tool_calls (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id uuid NOT NULL REFERENCES sessions(id),
  run_id uuid NOT NULL REFERENCES runs(id),
  tool_name text NOT NULL, safe_args jsonb NOT NULL, result_summary jsonb NOT NULL,
  citations jsonb NOT NULL DEFAULT '[]'::jsonb,
  help_id text NOT NULL, policy_version text NOT NULL,
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
  kind text NOT NULL CHECK (kind IN ('AGENT','REPORT','POLICY_CHECK')),
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

-- Least-privilege roles (ARCHITECTURE §1, AGENT_GUIDE §5)
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

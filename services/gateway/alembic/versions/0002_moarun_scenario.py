"""시나리오 교체: commerce-cart-v1(모아마켓) → moarun-rejoin-v1(루프랩 모아런).

- 이전 시나리오의 데모 세션·업무 데이터와 시나리오 seed를 제거한다(관리자 계정·회사는 유지).
- funnel_facts/support_cases → rejoin_facts/interview_notes.
- documents.available_after_min(인터뷰 01:05 공개), scenario_events.at_min(고정 시간 이벤트),
  tasks.owner에 JOINT(공동 담당) 추가.
"""
from alembic import op

revision = "0002_moarun_scenario"
down_revision = "0001_initial"

SQL = """
TRUNCATE stream_events, jobs, reports, tool_calls, actions, event_occurrences, mutation_receipts, approvals, runs,
         delegations, tasks, artifact_revisions, artifacts, messages, invites, participants, sessions,
         document_chunks, documents, scenario_events, funnel_facts, support_cases, scenarios CASCADE;
DO $$ BEGIN
  IF to_regclass('checkpoints.checkpoints') IS NOT NULL THEN
    EXECUTE 'TRUNCATE checkpoints.checkpoints, checkpoints.checkpoint_blobs, checkpoints.checkpoint_writes';
  END IF;
END $$;

DROP TABLE funnel_facts;
DROP TABLE support_cases;

CREATE TABLE rejoin_facts (
  scenario_id text NOT NULL REFERENCES scenarios(id),
  dataset_version text NOT NULL,
  group_size text NOT NULL CHECK (group_size IN ('small','medium','large')),
  first_time_participants int NOT NULL,
  rejoined_within_30d int NOT NULL,
  PRIMARY KEY (scenario_id, dataset_version, group_size),
  CHECK (0 <= rejoined_within_30d AND rejoined_within_30d <= first_time_participants)
);
CREATE TABLE interview_notes (
  id text PRIMARY KEY, scenario_id text NOT NULL REFERENCES scenarios(id),
  group_size text NOT NULL, tags jsonb NOT NULL, quote text NOT NULL
);

ALTER TABLE documents ADD COLUMN available_after_min int NOT NULL DEFAULT 0;
ALTER TABLE scenario_events ADD COLUMN at_min int NOT NULL DEFAULT 0;
ALTER TABLE tasks DROP CONSTRAINT tasks_owner_check;
ALTER TABLE tasks ADD CONSTRAINT tasks_owner_check CHECK (owner IN ('CANDIDATE','COLLEAGUE','JOINT'));
ALTER TABLE event_occurrences ADD COLUMN occurred_at_min numeric;
"""


def upgrade() -> None:
    op.get_bind().exec_driver_sql(SQL)


def downgrade() -> None:
    raise RuntimeError("P0 데모 DB는 downgrade를 지원하지 않습니다")

"""Elapsed wall clock; retain existing sessions and event history."""
from alembic import op
revision = "0002_elapsed_clock"
down_revision = "0001_fitmoa_initial"

def upgrade():
    op.execute("ALTER TABLE sessions ADD COLUMN IF NOT EXISTS clock_offset_seconds int NOT NULL DEFAULT 0")
    old = "virtual" + "_time"
    op.execute(f"ALTER TABLE sessions DROP COLUMN IF EXISTS {old}")
    op.execute(f"ALTER TABLE event_occurrences DROP COLUMN IF EXISTS {old}")
    op.execute("ALTER TABLE event_occurrences ADD COLUMN IF NOT EXISTS elapsed_seconds int NOT NULL DEFAULT 0")
    op.execute("ALTER TABLE event_occurrences ADD COLUMN IF NOT EXISTS occurrence_mode text NOT NULL DEFAULT 'on_action'")

def downgrade():
    raise RuntimeError("Clock history conversion cannot be reversed")

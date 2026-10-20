"""P0 초기 스키마: 업무 테이블, pgvector, 최소 권한 role, checkpoint schema"""
from pathlib import Path

from alembic import op

revision = "0001_initial"
down_revision = None


def upgrade() -> None:
    sql = (Path(__file__).resolve().parents[2] / "app" / "schema.sql").read_text()
    op.get_bind().exec_driver_sql(sql)


def downgrade() -> None:
    raise RuntimeError("P0 데모 DB는 downgrade를 지원하지 않습니다")

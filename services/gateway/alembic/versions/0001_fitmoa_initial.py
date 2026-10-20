"""초기 스키마(핏모아 sc-a): 업무 테이블, 턴 엔진 상태, observations·commitments, pgvector, 최소 권한 role, checkpoint schema.

이전 시나리오 마이그레이션(0001_initial, 0002_moarun_scenario)을 하나로 합쳤다. 데모 DB라 데이터는 보존하지 않는다.
기존 DB는 ./infra/dev-reset-db.sh로 비운 뒤 적용한다.
"""
from pathlib import Path

from alembic import op

revision = "0001_fitmoa_initial"
down_revision = None


def upgrade() -> None:
    sql = (Path(__file__).resolve().parents[2] / "app" / "schema.sql").read_text()
    op.get_bind().exec_driver_sql(sql)


def downgrade() -> None:
    raise RuntimeError("데모 DB는 downgrade를 지원하지 않습니다")

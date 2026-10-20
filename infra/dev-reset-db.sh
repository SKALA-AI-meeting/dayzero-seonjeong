#!/usr/bin/env bash
# 데모 DB를 비우고 새 스키마(0001_fitmoa_initial)·seed·벡터 색인을 다시 만든다. 데이터는 보존하지 않는다.
#   사용: ./infra/dev-down.sh && ./infra/dev-reset-db.sh && ./infra/dev-up.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"; cd "$ROOT"
docker exec dayzero-db psql -U dayzero -d postgres -qc "DROP DATABASE IF EXISTS dayzero WITH (FORCE)" -c "CREATE DATABASE dayzero"
echo "✓ dayzero DB 재생성"
(cd services && uv run alembic upgrade head && uv run python -m scripts.seed && uv run python -m scripts.index_documents)

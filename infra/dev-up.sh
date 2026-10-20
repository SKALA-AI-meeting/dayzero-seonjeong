#!/usr/bin/env bash
# Day Zero 로컬 실행(검증된 방법): DB 컨테이너 + 서비스 5개를 한 번에 띄운다.
#   사용: ./infra/dev-up.sh            (agent fixture 모드, 기본은 .env의 LLM_MODE)
#         LLM_MODE=live ./infra/dev-up.sh  (실제 gpt-4o-mini, OPENAI_API_KEY 필요)
# 이미 떠 있는 서비스(포트 사용 중)는 건너뛴다. 로그: .run/logs/*.log, PID: .run/*.pid
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"; cd "$ROOT"
RUN="$ROOT/.run"; mkdir -p "$RUN/logs"
[ -f .env ] || { echo "❌ .env 가 없습니다. cp .env.example .env 후 비밀값을 설정하세요(README 참고)."; exit 1; }
DB_PORT="${DB_PORT:-5434}"

up_container() { # name image args...
  local name=$1; shift
  if docker ps --format '{{.Names}}' | grep -qx "$name"; then echo "✓ $name 실행 중"; return; fi
  if docker ps -a --format '{{.Names}}' | grep -qx "$name"; then docker start "$name" >/dev/null; else docker run -d --name "$name" "$@" >/dev/null; fi
  echo "✓ $name 시작"
}
listening() { lsof -iTCP:"$1" -sTCP:LISTEN -n -P >/dev/null 2>&1; }

echo "== 1. 인프라 컨테이너 =="
docker info >/dev/null 2>&1 || { echo "❌ Docker가 실행 중이 아닙니다."; exit 1; }
up_container dayzero-db -e POSTGRES_USER=dayzero -e POSTGRES_PASSWORD=local_demo_only -e POSTGRES_DB=dayzero \
  -p "$DB_PORT":5432 -v dayzero_pgdata:/var/lib/postgresql/data pgvector/pgvector:pg17
for i in $(seq 1 30); do docker exec dayzero-db pg_isready -U dayzero >/dev/null 2>&1 && break; sleep 1; done
echo "✓ DB(:$DB_PORT) 준비"

echo "== 2. 의존성·마이그레이션·seed·색인 =="
(cd services && uv sync -q && uv run alembic upgrade head && uv run python -m scripts.seed)
CHUNKS=$(docker exec dayzero-db psql -U dayzero -tAc "select count(*) from document_chunks" 2>/dev/null || echo 0)
if [ "${CHUNKS// /}" = "0" ]; then (cd services && uv run python -m scripts.index_documents); else echo "✓ 벡터 색인 있음($CHUNKS 청크)"; fi
[ -d frontend/node_modules ] || (cd frontend && npm ci --silent)

echo "== 3. 서비스 =="
start() { # name port dir cmd...
  local name=$1 port=$2 dir=$3; shift 3
  if listening "$port"; then echo "✓ $name :$port 이미 실행 중(건너뜀)"; return; fi
  ( cd "$dir" || exit 1
    nohup "$@" < /dev/null > "$RUN/logs/$name.log" 2>&1 &
    echo $! > "$RUN/$name.pid" )
  echo "↑ $name :$port 시작 (로그 .run/logs/$name.log)"
}
start gateway      8000 services uv run uvicorn gateway.app.main:app --host 127.0.0.1 --port 8000
start business-mcp 9101 services uv run python -m business_mcp.server
start rag-mcp      9102 services uv run python -m rag_mcp.server
sleep 4
start agent        8001 services env LLM_MODE="${LLM_MODE:-$(grep -E '^LLM_MODE=' .env | cut -d= -f2)}" uv run uvicorn agent.app.main:app --host 127.0.0.1 --port 8001
start web          3100 frontend npm run dev

echo "== 4. 상태 확인 =="
for i in $(seq 1 40); do curl -sf http://localhost:3100/api/v1/health >/dev/null 2>&1 && break; sleep 1; done
"$ROOT/infra/dev-status.sh"
echo
echo "▶ 관리자: http://localhost:3100/admin/login  (admin@dayzero.local / .env의 SEED_ADMIN_PASSWORD)"
echo "▶ 종료:   ./infra/dev-down.sh"

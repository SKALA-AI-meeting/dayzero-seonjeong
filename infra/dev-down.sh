#!/usr/bin/env bash
# dev-up.sh로 띄운 서비스만 종료한다(다른 프로세스는 건드리지 않음).
#   ./infra/dev-down.sh          서비스만 종료(컨테이너·데이터 유지)
#   ./infra/dev-down.sh --infra  DB 컨테이너도 정지 — 데이터 볼륨은 삭제하지 않음
ROOT="$(cd "$(dirname "$0")/.." && pwd)"; RUN="$ROOT/.run"
for f in "$RUN"/*.pid; do
  [ -f "$f" ] || continue
  pid=$(cat "$f"); name=$(basename "$f" .pid)
  if kill -0 "$pid" 2>/dev/null; then pkill -P "$pid" 2>/dev/null; kill "$pid" 2>/dev/null; echo "■ $name 종료"; fi
  rm -f "$f"
done
if [ "${1:-}" = "--infra" ]; then docker stop dayzero-db >/dev/null 2>&1 && echo "■ DB 컨테이너 정지(데이터 유지)"; fi

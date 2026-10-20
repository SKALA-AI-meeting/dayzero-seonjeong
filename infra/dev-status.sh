#!/usr/bin/env bash
# 서비스·인프라 상태 요약
H=$(curl -s --max-time 5 http://localhost:3100/api/v1/health || echo '{}')
A=$(curl -s --max-time 5 http://localhost:8001/health || echo '{}')
python3 - "$H" "$A" <<'PY'
import json, sys
h = json.loads(sys.argv[1] or "{}"); a = json.loads(sys.argv[2] or "{}")
ok = lambda b: "✓" if b else "✗"
print(f"{ok(h.get('status') == 'ok')} web+gateway   status={h.get('status', 'down')} db={h.get('db', '-')} mode={h.get('mode', '-')}")
print(f"{ok(a.get('status') == 'ok')} agent         model={a.get('model', '-')} langsmith={a.get('langsmith', '-')}")
m = a.get("mcp", {}); print(f"{ok(m.get('business') == 'up' and m.get('rag') == 'up')} MCP           business={m.get('business', '-')} rag={m.get('rag', '-')}")
q = a.get("queue", {}); print(f"{ok(q.get('enabled') and 'counts' in q)} RabbitMQ      {q.get('counts', q)}")
PY

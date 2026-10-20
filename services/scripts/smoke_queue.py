"""대기열(RabbitMQ) 스모크: 정상 처리 / 실패 재시도 3회 → DLQ / 관리자 재생성.

PYTHONPATH=. uv run python -m scripts.smoke_queue   (agent·gateway 실행 중, RABBITMQ_URL 설정)
"""
import json, sys, time, uuid
from urllib.parse import parse_qs, urlparse
import httpx, pika
from shared import mq
from shared.config import settings
from shared.db import one, tx

S = settings(); B = S.app_origin + "/api/v1"; O = {"Origin": S.app_origin}
res = []
def check(n, ok, d=""):
    res.append(ok); print(("PASS " if ok else "FAIL ") + n + (f" — {d}" if d else ""), flush=True)

adm = httpx.Client(base_url=B, headers=O, timeout=30)
adm.headers["X-CSRF-Token"] = adm.post("/auth/login", json={"email": S.seed_admin_email, "password": S.seed_admin_password}).json()["csrf_token"]
health = httpx.get(S.agent_internal_url + "/health").json()
check("agent health에 대기열 활성", health.get("queue", {}).get("enabled") is True, json.dumps(health.get("queue")))

# 1) 정상 처리: 제출 → DB outbox(jobs) → RabbitMQ → 컨슈머 → 리포트 READY
url = adm.post("/invites", json={"alias": "smoke-queue"}).json()["invite_url"]
c = httpx.Client(base_url=B, headers=O, timeout=30)
e = c.post("/auth/exchange", json={"token": parse_qs(urlparse(url).query)["token"][0]}).json(); sid = e["session_id"]; c.headers["X-CSRF-Token"] = e["csrf_token"]
c.post(f"/sessions/{sid}/start", json={"consent": True})
v = c.get(f"/sessions/{sid}").json()["artifact"]["version"]
rid = c.post(f"/sessions/{sid}/submit", json={"base_version": v, "summary": ""}).json()["report_id"]
st = None
for _ in range(40):
    st = adm.get(f"/reports/{sid}").json()["status"]
    if st == "READY": break
    time.sleep(1)
with tx(S.psycopg_dsn) as db:
    job = one(db, "SELECT status, attempt FROM jobs WHERE dedupe_key=%s", (f"report:{rid}",))
check("제출 → outbox job 발행(DONE) → RabbitMQ 처리 → 리포트 READY", st == "READY" and job["status"] == "DONE", f"report={st}, job={job}")

# 2) 실패 재시도: 처리 불가 작업 주입 → 3초 지연 재시도 → 3회 실패 후 DLQ
before = mq.queue_counts()[mq.Q_DLQ]
bad = {"session_id": str(uuid.uuid4()), "report_id": str(uuid.uuid4()), "job_id": "inject"}
mq.publish_report(bad)
t0 = time.time(); after = before
while time.time() - t0 < 30:
    after = mq.queue_counts()[mq.Q_DLQ]
    if after > before: break
    time.sleep(1)
elapsed = round(time.time() - t0, 1)
conn = mq.connect(); ch = conn.channel()
got = None
for _ in range(after):
    m, props, body = ch.basic_get(mq.Q_DLQ)
    if m is None: break
    if json.loads(body)["report_id"] == bad["report_id"]:
        got = (props.headers or {}); ch.basic_ack(m.delivery_tag); break
    ch.basic_nack(m.delivery_tag, requeue=True)
conn.close()
check("실패 작업 재시도 3회 후 DLQ 이동", got is not None and got.get("x-attempt") == mq.MAX_ATTEMPTS,
      f"x-attempt={got and got.get('x-attempt')}, 소요 {elapsed}s(지연 재시도 2회 × 3s), last_error={got and got.get('x-last-error', '')[:60]}")
check("재시도 간 지연(≥6초)", elapsed >= 5.5, f"{elapsed}s")

# 3) 관리자 재생성: FAILED 리포트 → 다시 생성 → outbox 재발행 → READY
with tx(S.psycopg_dsn) as db:
    db.execute("UPDATE reports SET status='FAILED', error_code='QUEUE_MAX_ATTEMPTS' WHERE id=%s", (rid,))
r = adm.post(f"/reports/{sid}/retry", json={})
for _ in range(40):
    st = adm.get(f"/reports/{sid}").json()["status"]
    if st == "READY": break
    time.sleep(1)
check("FAILED 리포트 관리자 재생성 → 큐 재처리 → READY", r.status_code == 202 and st == "READY", f"{r.status_code} {st}")
counts = mq.queue_counts()
check("처리 큐·재시도 큐 잔여 0", counts[mq.Q_REPORT] == 0 and counts[mq.Q_RETRY] == 0, json.dumps(counts))
print(f"\n결과: {sum(res)}/{len(res)} PASS")
sys.exit(0 if all(res) else 1)

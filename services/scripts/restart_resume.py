"""AT-08: 승인 대기 중 agent 재시작 후 같은 승인 결정 → 같은 thread checkpoint에서 재개, 중복 반영 없음.

1단계: uv run python -m scripts.restart_resume prepare   (승인 대기 상태 생성, state 파일 저장)
   → agent 프로세스 재시작
2단계: uv run python -m scripts.restart_resume decide
"""
import json, sys, time
from pathlib import Path
from urllib.parse import parse_qs, urlparse
import httpx
from shared.config import ROOT, settings
from shared.db import all_, one, tx

S = settings(); B = S.app_origin + "/api/v1"; O = {"Origin": S.app_origin}
STATE = ROOT / "evidence" / ".restart_resume_state.local.json"


def prepare():
    adm = httpx.Client(base_url=B, headers=O, timeout=30)
    adm.headers["X-CSRF-Token"] = adm.post("/auth/login", json={"email": S.seed_admin_email, "password": S.seed_admin_password}).json()["csrf_token"]
    url = adm.post("/invites", json={"alias": "smoke-restart"}).json()["invite_url"]
    c = httpx.Client(base_url=B, headers=O, timeout=30)
    e = c.post("/auth/exchange", json={"token": parse_qs(urlparse(url).query)["token"][0]}).json()
    sid = e["session_id"]; c.headers["X-CSRF-Token"] = e["csrf_token"]
    c.post(f"/sessions/{sid}/start", json={"consent": True})
    adm.post(f"/sessions/{sid}/demo/advance", json={"to_event": "T-SPLIT"})
    s = c.get(f"/sessions/{sid}").json()
    c.post(f"/sessions/{sid}/split", json={"decision": "ACCEPT", "assignments": s["split"]["assignments"]})
    for _ in range(120):
        s = c.get(f"/sessions/{sid}").json()
        if len(s["approvals"]) == 2:
            break
        time.sleep(1.5)
    ap = next(a for a in s["approvals"] if a["before_after"]["section"] == "similar_cases")
    with tx(S.psycopg_dsn) as db:
        run = one(db, "SELECT id, thread_id, status FROM runs WHERE id=%s", (ap["run_id"],))
        ck = one(db, "SELECT count(*) AS n FROM checkpoints.checkpoints WHERE thread_id=%s", (run["thread_id"],))
    STATE.write_text(json.dumps({"sid": sid, "approval_id": ap["id"], "run_id": ap["run_id"], "thread_id": run["thread_id"],
                                 "cookies": dict(c.cookies), "csrf": e["csrf_token"], "artifact_version": s["artifact"]["version"]}))
    print(f"prepared: run {run['status']}, checkpoints for thread = {ck['n']}, approval {ap['id'][:8]} PENDING")


def decide():
    st = json.loads(STATE.read_text())
    c = httpx.Client(base_url=B, headers={**O, "X-CSRF-Token": st["csrf"]}, cookies=st["cookies"], timeout=30)
    sid = st["sid"]
    s = c.get(f"/sessions/{sid}").json()
    restored = any(a["id"] == st["approval_id"] for a in s["approvals"])
    r1 = c.post(f"/sessions/{sid}/approvals/{st['approval_id']}/decision", json={"decision": "APPROVE"})
    r2 = c.post(f"/sessions/{sid}/approvals/{st['approval_id']}/decision", json={"decision": "APPROVE"})
    for _ in range(90):
        s = c.get(f"/sessions/{sid}").json()
        if s["artifact"]["sections"]["similar_cases"].strip():
            break
        time.sleep(1.5)
    time.sleep(3)
    with tx(S.psycopg_dsn) as db:
        revs = all_(db, "SELECT version FROM artifact_revisions WHERE session_id=%s AND changed_sections ? 'similar_cases'", (sid,))
        receipts = one(db, "SELECT count(*) AS n FROM mutation_receipts WHERE approval_id=%s", (st["approval_id"],))
        run = one(db, "SELECT status, thread_id FROM runs WHERE id=%s", (st["run_id"],))
    res = {"approval_restored_after_restart": restored, "decision_status": [r1.status_code, r2.status_code],
           "applied": bool(s["artifact"]["sections"]["similar_cases"].strip()), "revisions_for_section": len(revs),
           "mutation_receipts": receipts["n"], "run_status": run["status"], "same_thread": run["thread_id"] == st["thread_id"]}
    ok = restored and res["applied"] and len(revs) == 1 and receipts["n"] == 1 and run["status"] == "SUCCEEDED"
    print(json.dumps(res, ensure_ascii=False)); print("AT-08", "PASS" if ok else "FAIL")
    return ok


if __name__ == "__main__":
    sys.exit(0 if (prepare() if sys.argv[1] == "prepare" else decide()) in (None, True) else 1)

"""승인 interrupt 후 서버 재시작 → 같은 thread checkpoint에서 재개, 중복 반영 없음.

지원자가 서윤에게 PE-1 정정을 요청 → 서윤 수정안 승인 카드(interrupt)에서 멈춘 상태를 만든 뒤 agent를 재시작하고 승인한다.
1단계: uv run python -m scripts.restart_resume prepare   (승인 대기 상태 생성, state 파일 저장)
   → ./infra/dev-down.sh && ./infra/dev-up.sh (agent 포함 전체 재시작)
2단계: uv run python -m scripts.restart_resume decide
"""
import json
import sys
import time
import uuid
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
    c.post(f"/sessions/{sid}/messages", json={"client_message_id": uuid.uuid4().hex, "channel": "TEAM",
                                             "content": "서윤 씨, 표 일정이 11/2 ~ 11/31인데 11월 31일은 없는 날짜예요. 브리프 보고 고쳐주실 수 있을까요?"})
    for _ in range(60):
        s = c.get(f"/sessions/{sid}").json()
        if s["approvals"]:
            break
        time.sleep(1)
    ap = s["approvals"][0]
    with tx(S.psycopg_dsn) as db:
        run = one(db, "SELECT id, thread_id, status FROM runs WHERE id=%s", (ap["run_id"],))
        ck = one(db, "SELECT count(*) AS n FROM checkpoints.checkpoints WHERE thread_id=%s", (run["thread_id"],))
    art = next(a for a in s["artifacts"] if a["key"] == "T3")
    STATE.write_text(json.dumps({"sid": sid, "approval_id": ap["id"], "run_id": ap["run_id"], "thread_id": run["thread_id"],
                                 "cookies": dict(c.cookies), "csrf": e["csrf_token"], "t3_version": art["version"]}))
    print(f"prepared: run {run['status']}, checkpoints for thread = {ck['n']}, approval {ap['id'][:8]} PENDING (T3 v{art['version']})")


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
        if "11/2 ~ 11/15" in next(a for a in s["artifacts"] if a["key"] == "T3")["body"] and not s["active_run"]:
            break
        time.sleep(1)
    time.sleep(2)
    with tx(S.psycopg_dsn) as db:
        revs = all_(db, """SELECT r.version FROM artifact_revisions r JOIN artifacts a ON a.id=r.artifact_id
                           WHERE r.session_id=%s AND a.key='T3' AND r.actor='COLLEAGUE'""", (sid,))
        receipts = one(db, "SELECT count(*) AS n FROM mutation_receipts WHERE approval_id=%s", (st["approval_id"],))
        run = one(db, "SELECT status, thread_id FROM runs WHERE id=%s", (st["run_id"],))
        fixed = one(db, "SELECT count(*) AS n FROM messages WHERE session_id=%s AND content='고쳤어요'", (sid,))
    t3 = next(a for a in s["artifacts"] if a["key"] == "T3")
    res = {"approval_restored_after_restart": restored, "decision_status": [r1.status_code, r2.status_code],
           "applied": "11/2 ~ 11/15" in t3["body"], "t3_version": [st["t3_version"], t3["version"]],
           "colleague_revisions": len(revs), "mutation_receipts": receipts["n"], "fix_reported": fixed["n"],
           "run_status": run["status"], "same_thread": run["thread_id"] == st["thread_id"]}
    ok = restored and res["applied"] and len(revs) == 1 and receipts["n"] == 1 and fixed["n"] == 1 and run["status"] == "SUCCEEDED"
    print(json.dumps(res, ensure_ascii=False)); print("RESTART_RESUME", "PASS" if ok else "FAIL")
    return ok


if __name__ == "__main__":
    sys.exit(0 if (prepare() if sys.argv[1] == "prepare" else decide()) in (None, True) else 1)

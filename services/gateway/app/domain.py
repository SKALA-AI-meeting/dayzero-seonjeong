"""Shared business-transaction helpers. Callers hold a session row lock via `lock_session`."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from shared.db import J, all_, one

from .auth import Principal
from .errors import ApiError


def elapsed_seconds(s: dict, at: datetime | None = None) -> int:
    if not s.get("started_at"):
        return 0
    end = at or s.get("submitted_at") or now()
    return max(0, int((end - s["started_at"]).total_seconds()) + s.get("clock_offset_seconds", 0))


def now() -> datetime:
    return datetime.now(timezone.utc)


def lock_session(c, sid: str, p: Principal | None = None, *, require_active: bool = False) -> dict:
    """Row-lock the session after verifying ownership. Foreign sessions look like 404."""
    try:
        uuid.UUID(str(sid))
    except ValueError:
        raise ApiError(404, "NOT_FOUND", "세션을 찾을 수 없습니다")
    s = one(c, "SELECT * FROM sessions WHERE id=%s FOR UPDATE", (sid,))
    if not s:
        raise ApiError(404, "NOT_FOUND", "세션을 찾을 수 없습니다")
    if p is not None:
        if str(s["company_id"]) != p.company_id:
            raise ApiError(404, "NOT_FOUND", "세션을 찾을 수 없습니다")
        if p.role == "CANDIDATE" and p.session_id != str(s["id"]):
            raise ApiError(404, "NOT_FOUND", "세션을 찾을 수 없습니다")
    if require_active:
        if s["status"] == "SUBMITTED":
            raise ApiError(409, "SESSION_SUBMITTED", "종료된 세션은 변경할 수 없습니다")
        if s["status"] != "ACTIVE":
            raise ApiError(403, "FORBIDDEN", "동의와 시작 이후에 사용할 수 있습니다")
    return s


def read_session(c, sid: str, p: Principal, *, allow_closed: bool = False) -> dict:
    try:
        uuid.UUID(str(sid))
    except ValueError:
        raise ApiError(404, "NOT_FOUND", "세션을 찾을 수 없습니다")
    s = one(c, "SELECT * FROM sessions WHERE id=%s", (sid,))
    if not s or str(s["company_id"]) != p.company_id or (p.role == "CANDIDATE" and p.session_id != str(s["id"])):
        raise ApiError(404, "NOT_FOUND", "세션을 찾을 수 없습니다")
    if p.role == "CANDIDATE" and s["status"] == "SUBMITTED" and not allow_closed:
        # 보안: 종료 후 지원자는 시뮬레이션 내용(산출물·대화·자료)을 다시 볼 수 없다
        raise ApiError(403, "SESSION_CLOSED", "시뮬레이션이 종료되어 내용을 다시 볼 수 없습니다")
    return s


def record_action(c, sid: str, actor: str, kind: str, entity_id: str | None = None,
                  payload: dict | None = None, *, turn: int | None = None) -> int:
    row = one(c, "UPDATE sessions SET last_action_seq=last_action_seq+1 WHERE id=%s RETURNING last_action_seq, turn_count", (sid,))
    seq = row["last_action_seq"]
    c.execute("INSERT INTO actions(session_id,seq,actor,kind,entity_id,payload,turn) VALUES (%s,%s,%s,%s,%s,%s,%s)",
              (sid, seq, actor, kind, entity_id, J(payload or {}), row["turn_count"] if turn is None else turn))
    return seq


def emit(c, sid: str, type_: str, payload: dict, *, run_id: str | None = None,
         admin_payload: dict | None = None, client_event_id: str | None = None) -> int:
    if client_event_id and run_id:
        existing = one(c, "SELECT seq FROM stream_events WHERE run_id=%s AND client_event_id=%s",
                       (run_id, client_event_id))
        if existing:
            return existing["seq"]
    row = one(c, "UPDATE sessions SET last_stream_seq=last_stream_seq+1 WHERE id=%s RETURNING last_stream_seq", (sid,))
    seq = row["last_stream_seq"]
    c.execute("""INSERT INTO stream_events(session_id,seq,run_id,type,public_payload,admin_payload,client_event_id)
                 VALUES (%s,%s,%s,%s,%s,%s,%s)""",
              (sid, seq, run_id, type_, J(payload), J(admin_payload) if admin_payload else None, client_event_id))
    return seq


def enqueue_job(c, sid: str, kind: str, dedupe_key: str, *, run_id: str | None = None,
                input_: dict | None = None) -> None:
    c.execute("""INSERT INTO jobs(session_id,run_id,dedupe_key,kind,input,status)
                 VALUES (%s,%s,%s,%s,%s,'QUEUED') ON CONFLICT (dedupe_key) DO NOTHING""",
              (sid, run_id, dedupe_key, kind, J(input_ or {})))


def create_run(c, sid: str, *, source_message_id: str | None = None, input_: dict | None = None,
               prompt_version: str = "colleague-seoyoon-v1") -> dict:
    run_id = str(uuid.uuid4())
    run = one(c, """INSERT INTO runs(id,session_id,thread_id,kind,status,source_message_id,input,
                     policy_version,prompt_version,trace_id)
                   VALUES (%s,%s,%s,'TEAM','QUEUED',%s,%s,'sc-a-v0.1',%s,%s) RETURNING *""",
              (run_id, sid, f"{sid}:{run_id}", source_message_id, J(input_ or {}), prompt_version, str(uuid.uuid4())))
    enqueue_job(c, sid, "AGENT", f"run:{run_id}", run_id=run_id, input_={"kind": "TEAM"})
    return run


def active_run(c, sid: str) -> dict | None:
    return one(c, """SELECT * FROM runs WHERE session_id=%s AND kind='TEAM'
                     AND status IN ('QUEUED','RUNNING','WAITING_APPROVAL') ORDER BY created_at DESC LIMIT 1""", (sid,))


ACTOR_EVENT = {"MANAGER": "MANAGER_MESSAGE", "COLLEAGUE": "COLLEAGUE_MESSAGE", "SYSTEM": "SYSTEM_NOTICE",
               "CANDIDATE": "CANDIDATE_MESSAGE"}


def insert_message(c, sid: str, actor: str, content: str, *, citations: list | None = None,
                   source_run_id: str | None = None, client_message_id: str | None = None,
                   meta: dict | None = None) -> dict:
    return one(c, """INSERT INTO messages(session_id,channel,actor,content,citations,source_run_id,client_message_id,meta,turn)
                     VALUES (%s,'TEAM',%s,%s,%s,%s,%s,%s,(SELECT turn_count FROM sessions WHERE id=%s)) RETURNING *""",
               (sid, actor, content, J(citations or []), source_run_id, client_message_id, J({**(meta or {}), "elapsed_seconds": elapsed_seconds(one(c, "SELECT * FROM sessions WHERE id=%s", (sid,)))}), sid))


def post_line(c, sid: str, actor: str, content: str, *, meta: dict | None = None, run_id: str | None = None,
              client_event_id: str | None = None) -> dict:
    """Insert a team message and stream it (scenario scripts, reminders, system notices)."""
    m = insert_message(c, sid, actor, content, meta=meta, source_run_id=run_id)
    emit(c, sid, ACTOR_EVENT[actor], {"message_id": str(m["id"]), "content": m["content"], "citations": [],
                                      "meta": m["meta"]}, run_id=run_id, client_event_id=client_event_id,
         admin_payload={"message_id": str(m["id"]), "content": m["content"], "meta": m["meta"]})
    return m


def message_dto(m: dict) -> dict:
    return {"id": str(m["id"]), "channel": m["channel"], "actor": m["actor"], "content": m["content"],
            "citations": m["citations"], "meta": m.get("meta") or {}, "turn": m.get("turn", 0),
            "source_run_id": str(m["source_run_id"]) if m["source_run_id"] else None,
            "created_at": m["created_at"].isoformat()}


def task_dto(t: dict) -> dict:
    return {"id": str(t["id"]), "key": t["key"], "title": t["title"], "status": t["status"], "owner": t["owner"],
            "eta": t["eta"], "note": t["note"], "version": t["version"]}


def artifact_dto(a: dict) -> dict:
    return {"id": str(a["id"]), "key": a["key"], "title": a["title"], "body": a["body"], "version": a["version"]}


def session_dto(s: dict) -> dict:
    return {"id": str(s["id"]), "status": s["status"], "phase": s["phase"], "version": s["version"],
            "turn_count": s["turn_count"], "elapsed_seconds": elapsed_seconds(s),
            "consent_at": s["consent_at"].isoformat() if s["consent_at"] else None,
            "started_at": s["started_at"].isoformat() if s["started_at"] else None,
            "submitted_at": s["submitted_at"].isoformat() if s["submitted_at"] else None,
            "last_stream_seq": s["last_stream_seq"]}


def approval_dto(a: dict) -> dict:
    return {"id": str(a["id"]), "run_id": str(a["run_id"]), "tool_name": a["tool_name"], "args": a["args"],
            "status": a["status"], "expires_at": a["expires_at"].isoformat(), "before_after": a["before_after"]}


def run_dto(r: dict | None) -> dict | None:
    if not r:
        return None
    return {"id": str(r["id"]), "kind": r["kind"], "status": r["status"], "error_code": r["error_code"],
            "result": r["result"], "trace_id": r["trace_id"], "trace_url": r["trace_url"]}


def list_tasks(c, sid: str) -> list[dict]:
    return [task_dto(t) for t in all_(c, "SELECT * FROM tasks WHERE session_id=%s ORDER BY key", (sid,))]


def list_artifacts(c, sid: str) -> list[dict]:
    out = []
    for a in all_(c, "SELECT * FROM artifacts WHERE session_id=%s ORDER BY key", (sid,)):
        dto = artifact_dto(a)
        revision = one(c, "SELECT version,body_before,body_after FROM artifact_revisions WHERE artifact_id=%s AND actor='COLLEAGUE' ORDER BY version DESC LIMIT 1", (a["id"],))
        if revision:
            before, after = revision["body_before"].splitlines(), revision["body_after"].splitlines()
            dto["change"] = {"version": revision["version"], "before": "\n".join(x for x in before if x not in after),
                             "after": "\n".join(x for x in after if x not in before)}
        out.append(dto)
    return out



def to_jsonable(v: Any) -> Any:
    if isinstance(v, (uuid.UUID,)):
        return str(v)
    if isinstance(v, datetime):
        return v.isoformat()
    if isinstance(v, dict):
        return {k: to_jsonable(x) for k, x in v.items()}
    if isinstance(v, list):
        return [to_jsonable(x) for x in v]
    return v


def scenario_def(c, s: dict) -> dict:
    return one(c, "SELECT definition FROM scenarios WHERE id=%s", (s["scenario_id"],))["definition"]


def set_state(c, s: dict, st: dict) -> None:
    c.execute("UPDATE sessions SET scenario_state=%s WHERE id=%s", (J(st), s["id"]))
    s["scenario_state"] = st

"""Server-managed exam timeline (DAYZERO_EXAM_SCENARIO §6, §10).

Event facts and times are fixed; each fires at most once per session (event_occurrences unique).
Scenario events are logged separately from normal AI replies (messages.meta.kind = SCENARIO_EVENT).
"""
from __future__ import annotations

from datetime import timedelta

from shared.config import EXAM_MINUTES
from shared.db import J, all_, one

from .domain import (create_run, elapsed_min, emit, enqueue_job, insert_message, record_action, task_dto)

ACTOR_EVENT = {"MANAGER": "MANAGER_EVENT", "COLLEAGUE": "COLLEAGUE_MESSAGE", "SYSTEM": "SYSTEM_NOTICE"}


def fire_due(c, s: dict) -> list[str]:
    """Fire every not-yet-occurred event whose at_min has passed. Caller holds the session row lock."""
    if s["status"] != "ACTIVE":
        return []
    em = elapsed_min(s)
    occurred = {r["event_id"] for r in all_(c, "SELECT event_id FROM event_occurrences WHERE session_id=%s", (s["id"],))}
    fired = []
    for ev in all_(c, "SELECT * FROM scenario_events WHERE at_min <= %s ORDER BY at_min", (em,)):
        if ev["id"] in occurred:
            continue
        fire(c, s, ev, em)
        fired.append(ev["id"])
        if ev["id"] == "T-END":
            break
    return fired


def fire(c, s: dict, ev: dict, em: float) -> None:
    sid = str(s["id"])
    p = ev["payload"]
    seq = record_action(c, sid, "SYSTEM", "EVENT_TRIGGERED", ev["id"], {"at_min": ev["at_min"], "elapsed_min": round(em, 2)})
    first_msg = None
    for i, m in enumerate(p["messages"]):
        meta = {"kind": "SCENARIO_EVENT", "event_id": ev["id"]}
        if ev["id"] == "T-SPLIT":
            sc = one(c, "SELECT public_brief FROM scenarios WHERE id=%s", (s["scenario_id"],))["public_brief"]
            meta["split_proposal"] = {"assignments": sc["default_split"], "adjustments_used": 0,
                                      "max_adjustments": sc["max_split_adjustments"]}
        msg = insert_message(c, sid, "TEAM", m["actor"], m["content"], meta=meta)
        first_msg = first_msg or msg
        emit(c, sid, ACTOR_EVENT[m["actor"]], {"message_id": str(msg["id"]), "content": msg["content"], "citations": []},
             admin_payload={"message_id": str(msg["id"]), "content": msg["content"], "event_id": ev["id"]},
             client_event_id=None)
    c.execute("""INSERT INTO event_occurrences(session_id,event_id,trigger_action_seq,facts,response_message_id,occurred_at_min)
                 VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
              (sid, ev["id"], seq, J({"kind": p["kind"], "area": p.get("area")}), first_msg["id"] if first_msg else None,
               round(em, 2)))
    st = dict(s.get("policy_state") or {})
    if ev["id"] == "T-SPLIT":
        sc = one(c, "SELECT public_brief FROM scenarios WHERE id=%s", (s["scenario_id"],))["public_brief"]
        st["split"] = {"assignments": sc["default_split"], "adjustments_used": 0, "confirmed": False,
                       "message_id": str(first_msg["id"])}
    if ev["id"] == "T-INTERVIEW":
        emit(c, sid, "DOCUMENTS_UPDATED", {"document_id": p.get("document_id")})
    if ev["id"] == "T-ERROR":
        st["error_open"] = True
        st["error_message_id"] = str(first_msg["id"])
    c.execute("UPDATE sessions SET policy_state=%s WHERE id=%s", (J(st), sid))
    s["policy_state"] = st
    if ev["id"] == "T-END":
        submit_session(c, s, actor="SYSTEM", summary="시험 시간 종료로 자동 제출")


def submit_session(c, s: dict, *, actor: str, summary: str = "") -> str:
    """Freeze artifact, cancel runs/approvals/delegations, create report job. Caller holds row lock."""
    sid = str(s["id"])
    existing = one(c, "SELECT id FROM reports WHERE session_id=%s", (sid,))
    if existing:
        return str(existing["id"])
    art = one(c, "SELECT * FROM artifacts WHERE session_id=%s FOR UPDATE", (sid,))
    final = one(c, "SELECT id FROM artifact_revisions WHERE artifact_id=%s AND version=%s", (art["id"], art["version"]))
    c.execute("UPDATE sessions SET status='SUBMITTED', phase='CLOSED', submitted_at=now(), version=version+1 WHERE id=%s", (sid,))
    runs = all_(c, """UPDATE runs SET status='CANCELLED', updated_at=now() WHERE session_id=%s
                      AND status IN ('QUEUED','RUNNING','WAITING_APPROVAL') RETURNING id""", (sid,))
    for r in runs:
        c.execute("UPDATE jobs SET status='DONE' WHERE run_id=%s AND status IN ('QUEUED','LEASED')", (r["id"],))
    c.execute("UPDATE approvals SET status='EXPIRED' WHERE session_id=%s AND status='PENDING'", (sid,))
    c.execute("UPDATE delegations SET revoked_at=now() WHERE session_id=%s AND revoked_at IS NULL", (sid,))
    seq = record_action(c, sid, actor, "SUBMITTED" if actor == "CANDIDATE" else "AUTO_SUBMITTED", str(art["id"]),
                        {"artifact_version": art["version"], "summary": summary,
                         "empty_sections": [k for k, v in art["sections"].items() if not v.strip()],
                         "elapsed_min": round(elapsed_min(s), 2)})
    snapshot = {"artifact_version": art["version"], "artifact_revision_id": str(final["id"]) if final else None,
                "sections": art["sections"], "last_action_seq": seq, "submitted_by": actor}
    rep = one(c, "INSERT INTO reports(session_id,status,source_snapshot) VALUES (%s,'PENDING',%s) RETURNING id", (sid, J(snapshot)))
    enqueue_job(c, sid, "REPORT", f"report:{rep['id']}", input_={"report_id": str(rep["id"])})
    emit(c, sid, "SESSION_DONE", {"report_id": str(rep["id"])})
    return str(rep["id"])


def apply_split(c, s: dict, assignments: dict, *, actor_id: str) -> list[dict]:
    """Confirm the split: task owners follow assignments; colleague-owned sections start delegated work."""
    sid = str(s["id"])
    st = dict(s["policy_state"])
    split = dict(st["split"])
    split.update({"assignments": assignments, "confirmed": True})
    st["split"] = split
    c.execute("UPDATE sessions SET policy_state=%s WHERE id=%s", (J(st), sid))
    tasks = []
    for key, owner in assignments.items():
        t = one(c, "UPDATE tasks SET owner=%s, version=version+1 WHERE session_id=%s AND template_key=%s RETURNING *",
                (owner, sid, key))
        tasks.append(t)
        emit(c, sid, "TASK_UPDATED", {"task": task_dto(t)})
    for t in tasks:
        if t["owner"] != "COLLEAGUE":
            continue
        d = one(c, """INSERT INTO delegations(session_id,task_id,source_message_id,tool_allowlist,section_allowlist,constraints,expires_at)
                      VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                (sid, t["id"], split["message_id"], J(["get_interview_notes", "get_rejoin_metrics", "search_docs"]),
                 J([t["template_key"]]), J({"split": True}), s["started_at"] + timedelta(minutes=EXAM_MINUTES)))
        t2 = one(c, "UPDATE tasks SET delegation_id=%s, status='IN_PROGRESS', version=version+1 WHERE id=%s RETURNING *",
                 (d["id"], t["id"]))
        create_run(c, sid, "DELEGATED", source_message_id=split["message_id"], task_id=str(t["id"]),
                   input_={"delegation_id": str(d["id"]), "section": t["template_key"]}, prompt_version="colleague-v2")
        emit(c, sid, "TASK_UPDATED", {"task": task_dto(t2)})
    return tasks

"""Candidate workspace API: start, chat, documents, artifact, tasks, SSE."""
from __future__ import annotations

import asyncio
import json
from typing import Literal

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from shared.config import SECTION_IDS, settings
from shared.db import J, all_, one, tx

from ..auth import Principal, candidate, principal
from ..domain import (CANDIDATE_ACTIONS, active_run, approval_dto, artifact_dto, create_run, emit,
                      enqueue_policy_check, insert_message, list_tasks, lock_session, message_dto, now,
                      read_session, record_action, run_dto, session_dto, task_dto)
from ..errors import ApiError

router = APIRouter()
MAX_ARTIFACT_CHARS = 40_000


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class StartIn(Strict):
    consent: Literal[True]


class MessageIn(Strict):
    client_message_id: str = Field(min_length=8, max_length=64)
    channel: Literal["TEAM", "ASSISTANT"]
    content: str = Field(min_length=1, max_length=4000)


class EvidenceRef(Strict):
    kind: Literal["message", "artifact_revision", "action", "tool_call"]
    id: str = Field(max_length=80)
    field: str = Field(max_length=40)
    start: int | None = None
    end: int | None = None
    quote: str | None = Field(default=None, max_length=1500)


class ArtifactPatchIn(Strict):
    base_version: int
    section: Literal["problem", "evidence", "options", "experiment", "risks"]
    content: str = Field(max_length=MAX_ARTIFACT_CHARS)
    source_refs: list[EvidenceRef] = Field(default_factory=list, max_length=20)


class TaskPatchIn(Strict):
    base_version: int
    status: Literal["TODO", "IN_PROGRESS", "REVIEW", "DONE", "CANCELLED"]


def dsn() -> str:
    return settings().psycopg_dsn


def snapshot(c, sid: str, s: dict) -> dict:
    art = one(c, "SELECT * FROM artifacts WHERE session_id=%s", (sid,))
    msgs = all_(c, "SELECT * FROM (SELECT * FROM messages WHERE session_id=%s ORDER BY created_at DESC LIMIT 100) m "
                   "ORDER BY created_at", (sid,))
    approvals = all_(c, "SELECT * FROM approvals WHERE session_id=%s AND status='PENDING' ORDER BY created_at", (sid,))
    brief = one(c, "SELECT public_brief, title FROM scenarios WHERE id=%s", (s["scenario_id"],))
    return {"session": session_dto(s), "artifact": artifact_dto(art) if art else None,
            "tasks": list_tasks(c, sid), "messages": [message_dto(m) for m in msgs],
            "active_run": run_dto(active_run(c, sid)), "approvals": [approval_dto(a) for a in approvals],
            "brief": {"title": brief["title"], **brief["public_brief"]}, "mode": settings().llm_mode}


@router.get("/sessions/{sid}")
def get_session(sid: str, p: Principal = Depends(principal)):
    with tx(dsn()) as c:
        s = read_session(c, sid, p)
        return snapshot(c, sid, s)


@router.post("/sessions/{sid}/start")
def start(sid: str, body: StartIn, p: Principal = Depends(candidate)):
    with tx(dsn()) as c:
        s = lock_session(c, sid, p)
        if s["status"] != "CREATED":
            return {"session": session_dto(s)}
        sc = one(c, "SELECT public_brief FROM scenarios WHERE id=%s", (s["scenario_id"],))["public_brief"]
        c.execute("UPDATE sessions SET status='ACTIVE', phase='WORK', consent_at=now(), started_at=now(), "
                  "version=version+1 WHERE id=%s", (sid,))
        c.execute("INSERT INTO artifacts(session_id,sections) VALUES (%s,%s)",
                  (sid, J({k: "" for k in SECTION_IDS})))
        for t in sc["task_templates"]:
            c.execute("INSERT INTO tasks(session_id,title,status,owner,template_key,target_section) "
                      "VALUES (%s,%s,'TODO','CANDIDATE',%s,%s)", (sid, t["title"], t["key"], t["key"]))
        record_action(c, sid, "CANDIDATE", "CONSENTED", payload={"items": ["observation", "ai_log", "human_judgement",
                                                                         "demo_retention"]})
        kickoff = (f"안녕하세요, 팀장 {sc['manager']}입니다. 오늘 과제를 공유드립니다.\n\n{sc['public_brief']}\n\n"
                   f"자료 패널의 기본 자료 6개를 먼저 확인해 주세요. 동료 {sc['colleague']} 님께 조사와 정리를 "
                   f"부탁할 수 있지만, 문제 정의·우선순위·최종 기획안은 직접 결정해 주세요.")
        m = insert_message(c, sid, "TEAM", "MANAGER", kickoff, meta={"kind": "KICKOFF"})
        emit(c, sid, "MANAGER_EVENT", {"message_id": str(m["id"]), "content": kickoff, "citations": []})
        s = one(c, "SELECT * FROM sessions WHERE id=%s", (sid,))
    return {"session": session_dto(s)}


@router.post("/sessions/{sid}/messages", status_code=202)
def post_message(sid: str, body: MessageIn, p: Principal = Depends(candidate)):
    with tx(dsn()) as c:
        s = lock_session(c, sid, p, require_active=True)
        dup = one(c, "SELECT id, source_run_id FROM messages WHERE session_id=%s AND client_message_id=%s",
                  (sid, body.client_message_id))
        if dup:
            run = one(c, "SELECT id FROM runs WHERE source_message_id=%s", (dup["id"],))
            return {"message_id": str(dup["id"]), "run_id": str(run["id"]) if run else None}
        busy = active_run(c, sid)
        if busy and busy["kind"] != "REPORT":
            raise ApiError(409, "RUN_BUSY", "동료가 다른 요청을 처리 중입니다. 완료 또는 승인 결정 후 다시 보내 주세요")
        m = insert_message(c, sid, body.channel, "CANDIDATE", body.content, client_message_id=body.client_message_id)
        seq = record_action(c, sid, "CANDIDATE", "MESSAGE_SENT", str(m["id"]), {"channel": body.channel})
        kind = "ASSISTANT" if body.channel == "ASSISTANT" else "COLLEAGUE"
        run = create_run(c, sid, kind, source_message_id=str(m["id"]),
                         input_={"message_id": str(m["id"]), "content": body.content, "channel": body.channel},
                         prompt_version="assistant-v1" if kind == "ASSISTANT" else "colleague-v1")
        c.execute("UPDATE messages SET source_run_id=%s WHERE id=%s", (run["id"], m["id"]))
        emit(c, sid, "CANDIDATE_MESSAGE", {"message_id": str(m["id"]), "channel": body.channel,
                                           "content": body.content}, run_id=str(run["id"]))
        if body.channel == "TEAM":
            enqueue_policy_check(c, sid, seq)
    return {"message_id": str(m["id"]), "run_id": str(run["id"])}


@router.get("/sessions/{sid}/documents")
def list_documents(sid: str, p: Principal = Depends(principal)):
    with tx(dsn()) as c:
        s = read_session(c, sid, p)
        if p.role == "CANDIDATE" and s["status"] == "CREATED":
            raise ApiError(403, "FORBIDDEN", "동의와 시작 이후에 사용할 수 있습니다")
        docs = all_(c, "SELECT id,title,version FROM documents WHERE scenario_id=%s ORDER BY id", (s["scenario_id"],))
    return {"items": docs}


@router.get("/sessions/{sid}/documents/{doc_id}")
def get_document(sid: str, doc_id: str, p: Principal = Depends(principal)):
    with tx(dsn()) as c:
        s = lock_session(c, sid, p)
        if p.role == "CANDIDATE" and s["status"] == "CREATED":
            raise ApiError(403, "FORBIDDEN", "동의와 시작 이후에 사용할 수 있습니다")
        d = one(c, "SELECT id,title,version,body FROM documents WHERE id=%s AND scenario_id=%s",
                (doc_id, s["scenario_id"]))
        if not d:
            raise ApiError(404, "NOT_FOUND", "문서를 찾을 수 없습니다")
        if p.role == "CANDIDATE" and s["status"] == "ACTIVE":
            seen = one(c, "SELECT 1 FROM actions WHERE session_id=%s AND kind='DOCUMENT_OPENED' AND entity_id=%s",
                       (sid, doc_id))
            # Repeat opens of the same document are recorded but count as candidate action only once.
            seq = record_action(c, sid, "CANDIDATE", "DOCUMENT_OPENED" if not seen else "DOCUMENT_REOPENED", doc_id,
                                {"version": d["version"]})
            if not seen:
                enqueue_policy_check(c, sid, seq)
    return d


@router.patch("/sessions/{sid}/artifact")
def patch_artifact(sid: str, body: ArtifactPatchIn, p: Principal = Depends(candidate)):
    with tx(dsn()) as c:
        lock_session(c, sid, p, require_active=True)
        art = one(c, "SELECT * FROM artifacts WHERE session_id=%s FOR UPDATE", (sid,))
        if art["version"] != body.base_version:
            raise ApiError(409, "VERSION_CONFLICT", f"다른 변경이 먼저 저장되었습니다(현재 v{art['version']})")
        sections = dict(art["sections"])
        if sections.get(body.section, "") == body.content:
            return {"artifact": artifact_dto(art), "changed": False}
        sections[body.section] = body.content
        if sum(len(v) for v in sections.values()) > MAX_ARTIFACT_CHARS:
            raise ApiError(422, "VALIDATION_ERROR", "기획안 전체 길이는 40,000자를 넘을 수 없습니다")
        was_empty = not (art["sections"].get(body.section) or "").strip()
        new_v = art["version"] + 1
        art = one(c, "UPDATE artifacts SET sections=%s, version=%s WHERE id=%s RETURNING *",
                  (J(sections), new_v, art["id"]))
        rev = one(c, """INSERT INTO artifact_revisions(session_id,artifact_id,version,sections,changed_sections,actor,source_refs)
                        VALUES (%s,%s,%s,%s,%s,'CANDIDATE',%s) RETURNING id""",
                  (sid, art["id"], new_v, J(sections), J([body.section]),
                   J([r.model_dump() for r in body.source_refs])))
        seq = record_action(c, sid, "CANDIDATE", "ARTIFACT_SAVED", str(rev["id"]),
                            {"section": body.section, "version": new_v, "was_empty": was_empty,
                             "length": len(body.content)})
        emit(c, sid, "ARTIFACT_UPDATED", {"version": new_v, "changed_sections": [body.section], "actor": "CANDIDATE"})
        enqueue_policy_check(c, sid, seq)
    return {"artifact": artifact_dto(art), "changed": True}


CANDIDATE_TRANSITIONS = {("TODO", "IN_PROGRESS"), ("IN_PROGRESS", "DONE"), ("TODO", "DONE"),
                         ("IN_PROGRESS", "TODO"), ("DONE", "IN_PROGRESS")}


@router.patch("/sessions/{sid}/tasks/{tid}")
def patch_task(sid: str, tid: str, body: TaskPatchIn, p: Principal = Depends(candidate)):
    with tx(dsn()) as c:
        lock_session(c, sid, p, require_active=True)
        t = one(c, "SELECT * FROM tasks WHERE id=%s AND session_id=%s FOR UPDATE", (tid, sid))
        if not t:
            raise ApiError(404, "NOT_FOUND", "태스크를 찾을 수 없습니다")
        if t["owner"] != "CANDIDATE":
            raise ApiError(403, "FORBIDDEN", "동료 태스크는 검토 API로만 결정할 수 있습니다")
        if t["version"] != body.base_version:
            raise ApiError(409, "VERSION_CONFLICT", "태스크가 이미 변경되었습니다")
        if (t["status"], body.status) not in CANDIDATE_TRANSITIONS:
            raise ApiError(409, "VERSION_CONFLICT", f"허용되지 않는 상태 전이: {t['status']}→{body.status}")
        t = one(c, "UPDATE tasks SET status=%s, version=version+1 WHERE id=%s RETURNING *", (body.status, tid))
        record_action(c, sid, "CANDIDATE", "TASK_STATUS_CHANGED", tid, {"status": body.status})
        emit(c, sid, "TASK_UPDATED", {"task": task_dto(t)})
    return {"task": task_dto(t)}


@router.get("/runs/{rid}")
def get_run(rid: str, p: Principal = Depends(principal)):
    with tx(dsn()) as c:
        r = one(c, "SELECT * FROM runs WHERE id=%s", (rid,))
        if not r:
            raise ApiError(404, "NOT_FOUND", "run을 찾을 수 없습니다")
        read_session(c, str(r["session_id"]), p)
    return {"id": str(r["id"]), "status": r["status"], "error": r["error_code"], "result": r["result"]}


@router.post("/runs/{rid}/retry", status_code=202)
def retry_run(rid: str, p: Principal = Depends(candidate)):
    with tx(dsn()) as c:
        r = one(c, "SELECT * FROM runs WHERE id=%s", (rid,))
        if not r:
            raise ApiError(404, "NOT_FOUND", "run을 찾을 수 없습니다")
        sid = str(r["session_id"])
        lock_session(c, sid, p, require_active=True)
        if r["status"] != "FAILED":
            raise ApiError(409, "RUN_BUSY", "FAILED 상태의 run만 재시도할 수 있습니다")
        if active_run(c, sid):
            raise ApiError(409, "RUN_BUSY", "진행 중인 작업이 있습니다")
        new = create_run(c, sid, r["kind"], source_message_id=str(r["source_message_id"]) if r["source_message_id"] else None,
                         task_id=str(r["task_id"]) if r["task_id"] else None, input_={**r["input"], "retry_of": rid},
                         prompt_version=r["prompt_version"])
        record_action(c, sid, "CANDIDATE", "RUN_RETRIED", str(new["id"]), {"retry_of": rid})
    return {"run_id": str(new["id"])}


# ---- SSE ------------------------------------------------------------------

@router.get("/sessions/{sid}/events")
async def events(sid: str, request: Request, after_seq: int = 0, p: Principal = Depends(principal)):
    with tx(dsn()) as c:
        read_session(c, sid, p)
    last_id = request.headers.get("last-event-id")
    cursor = max(after_seq, int(last_id) if last_id and last_id.isdigit() else 0)
    is_admin = p.role == "ADMIN"

    async def gen():
        nonlocal cursor
        idle = 0.0
        yield "retry: 2000\n\n"
        while True:
            if await request.is_disconnected():
                return
            rows = await asyncio.to_thread(_fetch_events, sid, cursor)
            for r in rows:
                cursor = r["seq"]
                payload = r["admin_payload"] if is_admin and r["admin_payload"] else r["public_payload"]
                data = {"event_id": str(r["id"]), "seq": r["seq"], "session_id": sid,
                        "run_id": str(r["run_id"]) if r["run_id"] else None,
                        "occurred_at": r["created_at"].isoformat(), "type": r["type"], "payload": payload}
                yield f"id: {r['seq']}\nevent: {r['type']}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
            if rows:
                idle = 0.0
            else:
                idle += 0.5
                if idle >= 15:
                    idle = 0.0
                    yield ": keepalive\n\n"
            await asyncio.sleep(0.5)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no",
                                      "Connection": "keep-alive"})


def _fetch_events(sid: str, after: int) -> list[dict]:
    with tx(dsn()) as c:
        return all_(c, "SELECT * FROM stream_events WHERE session_id=%s AND seq>%s ORDER BY seq LIMIT 200", (sid, after))

"""Candidate workspace API: start, chat, shared documents, artifacts, task board, SSE.

턴 = 팀 메시지 / 태스크 변경 / 산출물 저장 / 분업 제안 / 승인 결정 1개(engine.add_turn). 문서 열람은 턴이 아니다.
"""
from __future__ import annotations

import asyncio
import json
from typing import Literal

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from shared.config import settings
from shared.db import J, all_, one, tx

from .. import engine
from ..auth import Principal, candidate, principal
from ..domain import (active_run, approval_dto, artifact_dto, create_run, emit, insert_message, list_artifacts, list_tasks,
                      lock_session, message_dto, read_session, record_action, run_dto, scenario_def, session_dto, task_dto)
from ..errors import ApiError

router = APIRouter()
MAX_ARTIFACT_CHARS = 8_000
# 공유 문서 중 서윤 초안 2개는 세션의 작업본(산출물)을 그대로 보여 준다 — 서윤·지원자의 수정이 바로 보인다.
LIVE_DOCS = {"reward-table": "T3", "faq-draft": "T2"}


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class StartIn(Strict):
    consent: Literal[True]


class MessageIn(Strict):
    client_message_id: str = Field(min_length=8, max_length=64)
    channel: Literal["TEAM"]
    content: str = Field(min_length=1, max_length=4000)
    to: Literal["COLLEAGUE", "MANAGER"] = "COLLEAGUE"


class ArtifactPatchIn(Strict):
    base_version: int
    body: str = Field(max_length=MAX_ARTIFACT_CHARS)


class TaskPatchIn(Strict):
    base_version: int
    status: Literal["TODO", "IN_PROGRESS", "DONE"] | None = None
    owner: Literal["CANDIDATE", "COLLEAGUE"] | None = None
    eta: str | None = Field(default=None, max_length=20)


def dsn() -> str:
    return settings().psycopg_dsn


def snapshot(c, sid: str, s: dict) -> dict:
    msgs = all_(c, "SELECT * FROM (SELECT * FROM messages WHERE session_id=%s ORDER BY created_at DESC LIMIT 200) m "
                   "ORDER BY created_at", (sid,))
    approvals = all_(c, "SELECT * FROM approvals WHERE session_id=%s AND status='PENDING' ORDER BY created_at", (sid,))
    sc = scenario_def(c, s)
    st = s["scenario_state"] or {}
    occ = all_(c, "SELECT event_id, virtual_time, skipped FROM event_occurrences WHERE session_id=%s ORDER BY created_at", (sid,))
    return {"session": session_dto(s), "artifacts": list_artifacts(c, sid),
            "tasks": list_tasks(c, sid), "messages": [message_dto(m) for m in msgs],
            "active_run": run_dto(active_run(c, sid)),
            "approvals": [approval_dto(a) for a in approvals],
            "brief": {"title": sc["title"], "company": sc["company"], "task_summary": sc["task_summary"],
                      "virtual_time": sc["virtual_time"], "characters": {k: {"name": v["name"], "role": v["role"]}
                                                                        for k, v in sc["characters"].items()}},
            "clock": {"virtual_time": s["virtual_time"], "start": sc["virtual_time"]["start"], "deadline": sc["virtual_time"]["deadline"],
                      "turn_count": s["turn_count"]},
            "colleague": {"offline": bool((st.get("colleague") or {}).get("offline"))},
            "events": [o["event_id"] for o in occ if not o["skipped"]],
            "split": engine.public_split(st), "mode": settings().llm_mode}


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
        c.execute("UPDATE sessions SET status='ACTIVE', phase='WORK', consent_at=now(), started_at=now(), "
                  "version=version+1 WHERE id=%s", (sid,))
        record_action(c, sid, "CANDIDATE", "CONSENTED", payload={"items": ["behavior_log", "human_judgement", "demo_retention"]})
        s = one(c, "SELECT * FROM sessions WHERE id=%s", (sid,))
        engine.start_session(c, s)  # 보드·산출물 생성 + E0 스탠드업(팀장 지시 + 서윤 분업 질문)
        s = one(c, "SELECT * FROM sessions WHERE id=%s", (sid,))
    return {"session": session_dto(s)}


@router.post("/sessions/{sid}/messages", status_code=202)
def post_message(sid: str, body: MessageIn, p: Principal = Depends(candidate)):
    with tx(dsn()) as c:
        s = lock_session(c, sid, p, require_active=True)
        dup = one(c, "SELECT id, source_run_id FROM messages WHERE session_id=%s AND client_message_id=%s",
                  (sid, body.client_message_id))
        if dup:
            return {"message_id": str(dup["id"]), "run_id": str(dup["source_run_id"]) if dup["source_run_id"] else None}
        if active_run(c, sid):
            raise ApiError(409, "RUN_BUSY", "답장을 기다리는 중입니다. 답장 또는 승인 결정 후 다시 보내 주세요")
        st = engine.state(s)
        turn = engine.add_turn(c, s, responded=True)
        m = insert_message(c, sid, "CANDIDATE", body.content, client_message_id=body.client_message_id,
                           meta={"to": body.to, "event_id": st.get("active_event")})
        record_action(c, sid, "CANDIDATE", "MESSAGE_SENT", str(m["id"]), {"to": body.to})
        run = create_run(c, sid, source_message_id=str(m["id"]),
                         input_={"type": "message", "message_id": str(m["id"]), "content": body.content, "to": body.to,
                                 "event_id": st.get("active_event"), "turn": turn},
                         prompt_version="manager-junho-v1" if body.to == "MANAGER" else "colleague-seoyoon-v1")
        c.execute("UPDATE messages SET source_run_id=%s WHERE id=%s", (run["id"], m["id"]))
        emit(c, sid, "CANDIDATE_MESSAGE", {"message_id": str(m["id"]), "content": body.content, "to": body.to},
             run_id=str(run["id"]))
    return {"message_id": str(m["id"]), "run_id": str(run["id"])}


@router.get("/sessions/{sid}/documents")
def list_documents(sid: str, p: Principal = Depends(principal)):
    with tx(dsn()) as c:
        s = read_session(c, sid, p)
        if p.role == "CANDIDATE" and s["status"] == "CREATED":
            raise ApiError(403, "FORBIDDEN", "동의와 시작 이후에 사용할 수 있습니다")
        docs = all_(c, "SELECT id, title, version FROM documents WHERE scenario_id=%s AND visibility='PUBLIC' ORDER BY ordinal",
                    (s["scenario_id"],))
    return {"items": [{**d, "live": d["id"] in LIVE_DOCS, "uri": f"doc://sc-a/{d['id']}"} for d in docs]}


@router.get("/sessions/{sid}/documents/{doc_id}")
def get_document(sid: str, doc_id: str, p: Principal = Depends(principal)):
    with tx(dsn()) as c:
        s = lock_session(c, sid, p)
        if p.role == "CANDIDATE" and s["status"] == "CREATED":
            raise ApiError(403, "FORBIDDEN", "동의와 시작 이후에 사용할 수 있습니다")
        if p.role == "CANDIDATE" and s["status"] == "SUBMITTED":
            raise ApiError(403, "SESSION_CLOSED", "시뮬레이션이 종료되어 내용을 다시 볼 수 없습니다")
        d = one(c, "SELECT id,title,version,body FROM documents WHERE id=%s AND scenario_id=%s AND visibility='PUBLIC'",
                (doc_id, s["scenario_id"]))
        if not d:
            raise ApiError(404, "NOT_FOUND", "문서를 찾을 수 없습니다")
        if doc_id in LIVE_DOCS:
            a = one(c, "SELECT body, version FROM artifacts WHERE session_id=%s AND key=%s", (sid, LIVE_DOCS[doc_id]))
            if a:
                d = {**d, "body": a["body"], "version": a["version"], "live_artifact": LIVE_DOCS[doc_id]}
        if p.role == "CANDIDATE" and s["status"] == "ACTIVE":
            seen = one(c, "SELECT 1 FROM actions WHERE session_id=%s AND kind='DOCUMENT_OPENED' AND entity_id=%s", (sid, doc_id))
            record_action(c, sid, "CANDIDATE", "DOCUMENT_OPENED" if not seen else "DOCUMENT_REOPENED", doc_id,
                          {"version": d["version"]})
    return d


@router.patch("/sessions/{sid}/artifacts/{key}")
def patch_artifact(sid: str, key: str, body: ArtifactPatchIn, p: Principal = Depends(candidate)):
    with tx(dsn()) as c:
        s = lock_session(c, sid, p, require_active=True)
        a = one(c, "SELECT * FROM artifacts WHERE session_id=%s AND key=%s FOR UPDATE", (sid, key))
        if not a:
            raise ApiError(404, "NOT_FOUND", "산출물을 찾을 수 없습니다")
        if a["version"] != body.base_version:
            raise ApiError(409, "VERSION_CONFLICT", f"다른 변경이 먼저 저장되었습니다(현재 v{a['version']})")
        if a["body"] == body.body:
            return {"artifact": artifact_dto(a), "changed": False}
        turn = engine.add_turn(c, s)
        before = a["body"]
        a = one(c, "UPDATE artifacts SET body=%s, version=version+1 WHERE id=%s RETURNING *", (body.body, a["id"]))
        rev = one(c, """INSERT INTO artifact_revisions(session_id,artifact_id,version,body_before,body_after,actor,turn)
                        VALUES (%s,%s,%s,%s,%s,'CANDIDATE',%s) RETURNING id""",
                  (sid, a["id"], a["version"], before, body.body, turn))
        record_action(c, sid, "CANDIDATE", "ARTIFACT_SAVED", str(rev["id"]), {"key": key, "version": a["version"]})
        emit(c, sid, "ARTIFACT_UPDATED", {"artifact": artifact_dto(a), "actor": "CANDIDATE"})
        engine.tick(c, s)
    return {"artifact": artifact_dto(a), "changed": True}


@router.patch("/sessions/{sid}/tasks/{key}")
def patch_task(sid: str, key: str, body: TaskPatchIn, p: Principal = Depends(candidate)):
    with tx(dsn()) as c:
        s = lock_session(c, sid, p, require_active=True)
        t = one(c, "SELECT * FROM tasks WHERE session_id=%s AND key=%s FOR UPDATE", (sid, key))
        if not t:
            raise ApiError(404, "NOT_FOUND", "태스크를 찾을 수 없습니다")
        if t["version"] != body.base_version:
            raise ApiError(409, "VERSION_CONFLICT", "태스크가 이미 변경되었습니다")
        changes = {k: v for k, v in body.model_dump().items() if k != "base_version" and v is not None and v != t[k]}
        if not changes:
            return {"task": task_dto(t)}
        engine.add_turn(c, s)
        t = one(c, """UPDATE tasks SET status=COALESCE(%s,status), owner=COALESCE(%s,owner), eta=COALESCE(%s,eta),
                      version=version+1 WHERE id=%s RETURNING *""",
                (changes.get("status"), changes.get("owner"), changes.get("eta"), t["id"]))
        seq = record_action(c, sid, "CANDIDATE", "TASK_UPDATED", key, changes)
        board_rules(c, s, t, changes, seq)
        emit(c, sid, "TASK_UPDATED", {"task": task_dto(t)})
        engine.tick(c, s)
    return {"task": task_dto(t)}


def board_rules(c, s: dict, t: dict, changes: dict, seq: int) -> None:
    """보드 근거 코드: PL+1(E1 전에 담당·예상 시각 기록), PL+2(E2 후 E3 전 계획·보드 갱신)."""
    sid = str(s["id"])
    occ = {o["event_id"]: o for o in all_(c, "SELECT event_id, turn FROM event_occurrences WHERE session_id=%s AND NOT skipped", (sid,))}
    act = one(c, "SELECT id FROM actions WHERE session_id=%s AND seq=%s", (sid, seq))
    ref = {"kind": "action", "id": str(act["id"])}
    if "eta" in changes and "E1" not in occ and t["owner"] in ("CANDIDATE", "SPLIT"):
        engine.observe(c, sid, "PL+1", "E0", ref, f"{t['key']} 예상 완료 {changes['eta']} 기록")
    if "E2" in occ and "E3" not in occ:
        engine.observe(c, sid, "PL+2", "E2", ref, f"변경 후 보드 갱신: {t['key']} {changes}")


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
        new = create_run(c, sid, source_message_id=str(r["source_message_id"]) if r["source_message_id"] else None,
                         input_={**r["input"], "retry_of": rid}, prompt_version=r["prompt_version"])
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

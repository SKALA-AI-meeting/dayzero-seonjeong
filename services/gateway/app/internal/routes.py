"""Internal API for agent worker and business-mcp. Service auth only (ARCHITECTURE §5)."""
from __future__ import annotations

import hashlib
import json
from datetime import timedelta
from typing import Any, Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field

from shared.config import settings
from shared.db import J, all_, one, tx

from ..auth import internal_service, issue_capability, verify_capability
from ..business import ToolError, interview_notes, rejoin_metrics
from ..domain import (artifact_dto, hidden_document_ids, section_sha, emit, insert_message, list_tasks, lock_session, now,
                      record_action, task_dto, to_jsonable)
from ..errors import ApiError

router = APIRouter(dependencies=[Depends(internal_service)])
LEASE = timedelta(seconds=150)
READ_TOOLS = {"get_session_context", "get_rejoin_metrics", "get_interview_notes", "search_docs", "read_resource"}
WRITE_TOOLS = {"update_task_status", "patch_artifact_section"}
MESSAGE_EVENTS = {"COLLEAGUE_MESSAGE": ("TEAM", "COLLEAGUE"), "ASSISTANT_MESSAGE": ("ASSISTANT", "ASSISTANT"),
                  "MANAGER_EVENT": ("TEAM", "MANAGER")}


def dsn() -> str:
    return settings().psycopg_dsn


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


def args_hash(tool: str, args: dict) -> str:
    return hashlib.sha256(json.dumps({"tool": tool, "args": args}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


# ---- jobs -----------------------------------------------------------------

class ClaimIn(Strict):
    worker_id: str
    kinds: list[Literal["AGENT", "REPORT", "POLICY_CHECK"]]


@router.post("/jobs/claim")
def claim(body: ClaimIn):
    with tx(dsn()) as c:
        # One leased job per session at a time (session-level serialization).
        j = one(c, """SELECT j.* FROM jobs j
                      WHERE j.kind = ANY(%s) AND j.available_at <= now()
                        AND (j.status='QUEUED' OR (j.status='LEASED' AND j.lease_until < now()))
                        AND NOT EXISTS (SELECT 1 FROM jobs o WHERE o.session_id=j.session_id AND o.id<>j.id
                                        AND o.status='LEASED' AND o.lease_until >= now())
                      ORDER BY j.available_at FOR UPDATE SKIP LOCKED LIMIT 1""", (body.kinds,))
        if not j:
            return {"job": None}
        lease_until = now() + LEASE
        c.execute("UPDATE jobs SET status='LEASED', lease_until=%s, worker_id=%s, attempt=attempt+1 WHERE id=%s",
                  (lease_until, body.worker_id, j["id"]))
    return {"job": {"id": str(j["id"]), "kind": j["kind"], "session_id": str(j["session_id"]),
                    "run_id": str(j["run_id"]) if j["run_id"] else None, "input": j["input"],
                    "attempt": j["attempt"] + 1, "lease_until": lease_until.isoformat()}}


class CompleteIn(Strict):
    worker_id: str
    outcome: Literal["DONE", "FAILED", "WAITING_APPROVAL"]
    result: dict | None = None
    error: str | None = None


@router.post("/jobs/{jid}/complete")
def complete(jid: str, body: CompleteIn):
    with tx(dsn()) as c:
        j = one(c, "SELECT * FROM jobs WHERE id=%s FOR UPDATE", (jid,))
        if not j or j["worker_id"] != body.worker_id:
            raise ApiError(409, "FORBIDDEN", "lease 소유자가 아닙니다")
        status = "FAILED" if body.outcome == "FAILED" else "DONE"
        c.execute("UPDATE jobs SET status=%s, lease_until=NULL, last_error=%s WHERE id=%s", (status, body.error, jid))
    return {"status": status}


# ---- runs -----------------------------------------------------------------

class CapabilityIn(Strict):
    audience: Literal["business-mcp", "rag-mcp"]
    approval_id: str | None = None


@router.post("/runs/{rid}/capability")
def capability(rid: str, body: CapabilityIn):
    with tx(dsn()) as c:
        r = one(c, "SELECT r.*, s.status AS session_status FROM runs r JOIN sessions s ON s.id=r.session_id WHERE r.id=%s", (rid,))
        if not r or r["status"] not in ("RUNNING", "WAITING_APPROVAL") or r["session_status"] != "ACTIVE":
            raise ApiError(403, "FORBIDDEN", "실행 중인 run이 아닙니다")
        tools = sorted(READ_TOOLS)
        delegation_id = None
        if r["kind"] == "DELEGATED" and r["task_id"]:
            t = one(c, "SELECT delegation_id FROM tasks WHERE id=%s", (r["task_id"],))
            d = one(c, "SELECT * FROM delegations WHERE id=%s AND revoked_at IS NULL AND expires_at>now()",
                    (t["delegation_id"],)) if t and t["delegation_id"] else None
            if d:
                delegation_id = str(d["id"])
                tools = sorted(set(d["tool_allowlist"]) | (WRITE_TOOLS if body.approval_id else set()))
    with tx(dsn()) as c:
        hidden = hidden_document_ids(c, one(c, "SELECT * FROM sessions WHERE id=%s", (r["session_id"],)))
    token, exp = issue_capability(audience=body.audience, session_id=str(r["session_id"]), run_id=rid, hidden_documents=hidden,
                                  actor="COLLEAGUE" if r["kind"] != "ASSISTANT" else "ASSISTANT",
                                  allowed_tools=tools, delegation_id=delegation_id)
    if body.approval_id:
        # bind approval into a write capability
        import jwt
        claims = jwt.decode(token, settings().internal_service_secret, algorithms=["HS256"], audience=body.audience)
        claims["approval_id"] = body.approval_id
        token = jwt.encode(claims, settings().internal_service_secret, algorithm="HS256")
    return {"token": token, "expires_at": exp}


@router.get("/runs/{rid}/context")
def run_context(rid: str):
    with tx(dsn()) as c:
        r = one(c, "SELECT * FROM runs WHERE id=%s", (rid,))
        if not r:
            raise ApiError(404, "NOT_FOUND", "run 없음")
        sid = str(r["session_id"])
        s = one(c, "SELECT * FROM sessions WHERE id=%s", (sid,))
        sc = one(c, "SELECT public_brief FROM scenarios WHERE id=%s", (s["scenario_id"],))["public_brief"]
        channel = "ASSISTANT" if r["kind"] == "ASSISTANT" else "TEAM"
        msgs = all_(c, """SELECT * FROM (SELECT id, actor, content, created_at FROM messages
                          WHERE session_id=%s AND channel=%s ORDER BY created_at DESC LIMIT 60) m ORDER BY created_at""",
                    (sid, channel))
        art = one(c, "SELECT * FROM artifacts WHERE session_id=%s", (sid,))
        task = one(c, "SELECT * FROM tasks WHERE id=%s", (r["task_id"],)) if r["task_id"] else None
        deleg = one(c, "SELECT * FROM delegations WHERE id=%s", (task["delegation_id"],)) if task and task["delegation_id"] else None
        st = s["policy_state"] or {}
        occurred = [o["event_id"] for o in all_(c, "SELECT event_id FROM event_occurrences WHERE session_id=%s", (sid,))]
        pivot = one(c, "SELECT content FROM messages WHERE session_id=%s AND meta->>'event_id'='T-PIVOT' LIMIT 1", (sid,))
        hidden = hidden_document_ids(c, s)
    return to_jsonable({
        "scenario_state": {"error_open": bool(st.get("error_open")), "events": occurred,
                           "interviews_released": "user-interviews" not in hidden,
                           "split_confirmed": bool((st.get("split") or {}).get("confirmed")),
                           "colleague_sections": [t["template_key"] for t in list_tasks(c, sid) if t["owner"] == "COLLEAGUE" and t["template_key"]],
                           "pivot_text": pivot["content"] if pivot else None},
        "run": {"id": rid, "kind": r["kind"], "status": r["status"], "input": r["input"], "trace_id": r["trace_id"],
                "source_message_id": r["source_message_id"], "task_id": r["task_id"], "thread_id": r["thread_id"]},
        "session": {"id": sid, "status": s["status"], "phase": s["phase"]},
        "public_brief": {k: sc[k] for k in ("public_brief", "manager", "colleague", "section_ids")},
        "messages": msgs, "artifact": artifact_dto(art) if art else None,
        "task": task_dto(task) if task else None,
        "delegation": {"id": deleg["id"], "tool_allowlist": deleg["tool_allowlist"],
                       "section_allowlist": deleg["section_allowlist"], "constraints": deleg["constraints"],
                       "revoked": deleg["revoked_at"] is not None, "expires_at": deleg["expires_at"]} if deleg else None,
    })


class RunStateIn(Strict):
    status: Literal["RUNNING", "SUCCEEDED", "FAILED", "WAITING_APPROVAL", "CANCELLED"]
    error_code: str | None = None
    result: dict | None = None
    token_usage: dict | None = None
    trace_url: str | None = None


@router.post("/runs/{rid}/state")
def run_state(rid: str, body: RunStateIn):
    with tx(dsn()) as c:
        r = one(c, "SELECT * FROM runs WHERE id=%s FOR UPDATE", (rid,))
        if not r:
            raise ApiError(404, "NOT_FOUND", "run 없음")
        if r["status"] == "CANCELLED" and body.status != "CANCELLED":
            return {"status": "CANCELLED"}
        c.execute("""UPDATE runs SET status=%s, error_code=COALESCE(%s,error_code), result=COALESCE(%s,result),
                     token_usage=COALESCE(%s,token_usage), trace_url=COALESCE(%s,trace_url), updated_at=now()
                     WHERE id=%s""",
                  (body.status, body.error_code, J(body.result) if body.result else None,
                   J(body.token_usage) if body.token_usage else None, body.trace_url, rid))
        sid = str(r["session_id"])
        if body.status == "RUNNING" and r["status"] == "QUEUED":
            emit(c, sid, "RUN_STARTED", {"kind": r["kind"]}, run_id=rid)
        elif body.status in ("SUCCEEDED", "FAILED", "CANCELLED"):
            if r["kind"] == "DELEGATED" and r["task_id"] and body.status == "SUCCEEDED":
                # 승인해 반영 → 동료 담당 태스크 완료(확인 카드 승인이 곧 수락).
                # 거절 → 진행 중으로 되돌려 지원자가 수정 방향을 남기고 다시 작성 요청할 수 있게 함.
                decision = (body.result or {}).get("decision")
                applied = decision == "APPROVE" and not (body.result or {}).get("error_code")
                if applied:
                    t = one(c, """UPDATE tasks SET status='DONE', version=version+1,
                                  result=COALESCE(result,'{}'::jsonb) || '{"rejected": false}'::jsonb
                                  WHERE id=%s AND owner='COLLEAGUE' AND status IN ('IN_PROGRESS','REVIEW') RETURNING *""", (r["task_id"],))
                    if t:
                        record_action(c, sid, "SYSTEM", "TASK_COMPLETED_BY_APPROVAL", str(t["id"]), {"run_id": rid})
                else:
                    t = one(c, """UPDATE tasks SET status=CASE WHEN owner='COLLEAGUE' THEN 'IN_PROGRESS' ELSE status END, version=version+1,
                                  result=COALESCE(result,'{}'::jsonb) || jsonb_build_object('rejected', true)
                                  WHERE id=%s RETURNING *""", (r["task_id"],))
                if t:
                    emit(c, sid, "TASK_UPDATED", {"task": task_dto(t)}, run_id=rid)
            emit(c, sid, "DONE" if body.status == "SUCCEEDED" else "FAILED",
                 {"status": body.status, "error_code": body.error_code}, run_id=rid,
                 client_event_id=f"terminal:{body.status}")
    return {"status": body.status}


class EventIn(Strict):
    client_event_id: str
    type: str
    payload: dict


@router.post("/runs/{rid}/events")
def run_event(rid: str, body: EventIn):
    with tx(dsn()) as c:
        r = one(c, "SELECT * FROM runs WHERE id=%s", (rid,))
        if not r:
            raise ApiError(404, "NOT_FOUND", "run 없음")
        sid = str(r["session_id"])
        s = lock_session(c, sid)
        if r["status"] == "CANCELLED" or s["status"] == "SUBMITTED":
            return {"seq": None, "dropped": "run cancelled or session submitted"}
        dup = one(c, "SELECT seq FROM stream_events WHERE run_id=%s AND client_event_id=%s", (rid, body.client_event_id))
        if dup:
            return {"seq": dup["seq"]}
        p = dict(body.payload)
        if body.type in MESSAGE_EVENTS:
            channel, actor = MESSAGE_EVENTS[body.type]
            cits = validate_citations(c, p.get("citations") or [], rid)
            meta = {k: p[k] for k in ("limited", "kind") if k in p}
            if meta.get("kind") == "ERROR_CORRECTED":
                st = dict(s["policy_state"] or {})
                st["error_open"] = False
                c.execute("UPDATE sessions SET policy_state=%s WHERE id=%s", (J(st), sid))
                record_action(c, sid, "COLLEAGUE", "ERROR_CORRECTED", str(r["source_message_id"]), {})
            m = insert_message(c, sid, channel, actor, str(p.get("content", ""))[:8000], citations=cits,
                               source_run_id=rid, meta=meta)
            p = {"message_id": str(m["id"]), "content": m["content"], "citations": cits}
        elif body.type == "TOOL_END":
            tc = one(c, """INSERT INTO tool_calls(session_id,run_id,tool_name,safe_args,result_summary,citations,help_id,
                           policy_version,outcome,duration_ms) VALUES (%s,%s,%s,%s,%s,%s,%s,'help-v1',%s,%s) RETURNING id""",
                     (sid, rid, p.get("tool_name"), J(p.get("safe_args") or {}), J(p.get("result_summary") or {}),
                      J(p.get("citations") or []), p.get("help_id", "H2"), p.get("outcome", "ok"),
                      int(p.get("duration_ms", 0))))
            p = {"tool_call_id": str(tc["id"]), "display_name": p.get("tool_name"), "outcome": p.get("outcome"),
                 "citations": p.get("citations") or []}
        elif body.type == "TOOL_START":
            p = {"tool_call_id": p.get("tool_call_id"), "display_name": p.get("tool_name")}
        elif body.type == "TASK_RESULT":
            t = one(c, "UPDATE tasks SET result=%s, version=version+1 WHERE id=%s AND session_id=%s RETURNING *",
                    (J(p.get("result") or {}), r["task_id"], sid))
            body = EventIn(client_event_id=body.client_event_id, type="TASK_UPDATED", payload={})
            p = {"task": task_dto(t)} if t else {}
        else:
            raise ApiError(422, "VALIDATION_ERROR", f"허용되지 않는 이벤트 type: {body.type}")
        seq = emit(c, sid, body.type, p, run_id=rid, client_event_id=body.client_event_id)
    return {"seq": seq, "payload": p}


def validate_citations(c, cits: list, rid: str) -> list:
    """Keep only citations whose quote is a contiguous substring of the cited chunk/document (AT-14)."""
    ok = []
    for ci in cits[:10]:
        if not isinstance(ci, dict) or not ci.get("quote"):
            continue
        q = str(ci["quote"])
        if ci.get("document_id") == "rejoin_facts":
            tc = one(c, "SELECT 1 FROM tool_calls WHERE run_id=%s AND tool_name='get_rejoin_metrics' AND outcome='ok' LIMIT 1", (rid,))
            if tc:
                ok.append({"document_id": "rejoin_facts", "chunk_id": None, "version": 1, "quote": q[:300]})
            continue
        if ci.get("document_id") == "interview_notes":
            row = one(c, "SELECT 1 FROM interview_notes WHERE quote LIKE %s", (f"%{q}%",))
            if row:
                ok.append({"document_id": "user-interviews", "chunk_id": None, "version": 1, "quote": q})
            continue
        if ci.get("chunk_id"):
            row = one(c, "SELECT body, document_version FROM document_chunks WHERE id=%s", (ci["chunk_id"],))
            if row and q in row["body"]:
                ok.append({"document_id": ci.get("document_id"), "chunk_id": ci["chunk_id"],
                           "version": row["document_version"], "quote": q})
                continue
        d = one(c, "SELECT body, version FROM documents WHERE id=%s", (ci.get("document_id"),))
        if d and q in d["body"]:
            ok.append({"document_id": ci["document_id"], "chunk_id": ci.get("chunk_id"), "version": d["version"], "quote": q})
    return ok


# ---- approvals --------------------------------------------------------------

class ProposalIn(Strict):
    interrupt_id: str
    tool_name: Literal["update_task_status", "patch_artifact_section"]
    args: dict
    base_versions: dict
    delegation_id: str | None = None


@router.post("/runs/{rid}/proposal")
def proposal(rid: str, body: ProposalIn):
    with tx(dsn()) as c:
        r = one(c, "SELECT * FROM runs WHERE id=%s FOR UPDATE", (rid,))
        if not r:
            raise ApiError(404, "NOT_FOUND", "run 없음")
        sid = str(r["session_id"])
        s = lock_session(c, sid)
        existing = one(c, "SELECT * FROM approvals WHERE run_id=%s AND interrupt_id=%s", (rid, body.interrupt_id))
        if existing:
            return {"approval_id": str(existing["id"]), "args_hash": existing["args_hash"],
                    "expires_at": existing["expires_at"].isoformat(), "status": existing["status"]}
        if s["status"] != "ACTIVE" or r["status"] == "CANCELLED":
            raise ApiError(409, "APPROVAL_STALE", "세션 또는 run이 종료되었습니다")
        check_scope(c, sid, r, body.tool_name, body.args)
        art = one(c, "SELECT * FROM artifacts WHERE session_id=%s", (sid,))
        if body.tool_name == "patch_artifact_section":
            ba = {"section": body.args["section"], "before": art["sections"].get(body.args["section"], ""),
                  "after": body.args["content"], "task_id": body.args.get("task_id")}
        else:
            t = one(c, "SELECT * FROM tasks WHERE id=%s", (body.args.get("task_id"),))
            ba = {"before": t["status"] if t else "", "after": body.args.get("status"), "task_id": body.args.get("task_id")}
        h = args_hash(body.tool_name, body.args)
        base_versions = dict(body.base_versions)
        if body.tool_name == "patch_artifact_section":
            # 서버가 대상 섹션의 현재 내용 해시를 기록 — 다른 섹션 변경은 이 제안을 무효로 만들지 않는다
            base_versions.update({"section": body.args["section"], "section_sha": section_sha(art["sections"], body.args["section"]),
                                  "artifact": art["version"]})
        a = one(c, """INSERT INTO approvals(session_id,run_id,interrupt_id,tool_name,args,args_hash,base_versions,
                      delegation_id,before_after,status,expires_at)
                      VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,'PENDING',now()+interval '10 minutes') RETURNING *""",
                (sid, rid, body.interrupt_id, body.tool_name, J(body.args), h, J(base_versions),
                 body.delegation_id, J(ba)))
        c.execute("UPDATE runs SET status='WAITING_APPROVAL', updated_at=now() WHERE id=%s", (rid,))
        emit(c, sid, "APPROVAL_REQUIRED", {"approval_id": str(a["id"]), "task_id": body.args.get("task_id"),
                                           "tool_name": body.tool_name, "before": ba.get("before"),
                                           "after": ba.get("after"), "expires_at": a["expires_at"].isoformat()},
             run_id=rid)
    return {"approval_id": str(a["id"]), "args_hash": h, "expires_at": a["expires_at"].isoformat(), "status": "PENDING"}


def check_scope(c, sid: str, run: dict, tool: str, args: dict) -> dict:
    """Delegation scope check: only DELEGATED runs, active delegation, evidence section, own task."""
    if run["kind"] != "DELEGATED" or not run["task_id"]:
        raise ToolError("OUT_OF_SCOPE", "위임된 작업에서만 변경을 제안할 수 있습니다")
    task = one(c, "SELECT * FROM tasks WHERE id=%s AND session_id=%s", (run["task_id"], sid))
    d = one(c, "SELECT * FROM delegations WHERE id=%s", (task["delegation_id"],)) if task and task["delegation_id"] else None
    if not d or d["revoked_at"] or d["expires_at"] < now():
        raise ToolError("OUT_OF_SCOPE", "유효한 위임이 없습니다")
    if str(args.get("task_id")) != str(task["id"]):
        raise ToolError("OUT_OF_SCOPE", "위임된 태스크만 변경할 수 있습니다")
    if tool == "patch_artifact_section" and args.get("section") not in d["section_allowlist"]:
        raise ToolError("OUT_OF_SCOPE", f"위임 범위 밖 섹션입니다: {args.get('section')}")
    if tool == "update_task_status" and args.get("status") not in ("IN_PROGRESS", "REVIEW"):
        raise ToolError("OUT_OF_SCOPE", "동료는 IN_PROGRESS/REVIEW로만 변경할 수 있습니다")
    return d


# ---- MCP tool execution (business-mcp → gateway) ------------------------------

class McpIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    args: dict = Field(default_factory=dict)


@router.post("/mcp/{tool_name}")
def mcp_tool(tool_name: str, body: McpIn, request: Request):
    cap = verify_capability(request.headers.get("x-capability", ""), "business-mcp")
    if tool_name not in cap["allowed_tools"]:
        return tool_err("FORBIDDEN", f"이 run에서 허용되지 않은 도구입니다: {tool_name}")
    sid, rid = cap["session_id"], cap["run_id"]
    if "session_id" in body.args and body.args["session_id"] != sid:
        return tool_err("FORBIDDEN", "session_id가 인증 컨텍스트와 다릅니다")
    try:
        with tx(dsn()) as c:
            s = lock_session(c, sid)
            run = one(c, "SELECT * FROM runs WHERE id=%s", (rid,))
            if s["status"] != "ACTIVE" or not run or run["status"] in ("CANCELLED", "FAILED", "SUCCEEDED"):
                return tool_err("FORBIDDEN", "종료된 세션 또는 run입니다")
            if tool_name == "get_session_context":
                art = one(c, "SELECT version FROM artifacts WHERE session_id=%s", (sid,))
                sc = one(c, "SELECT public_brief FROM scenarios WHERE id=%s", (s["scenario_id"],))["public_brief"]
                data = {"public_brief": sc["public_brief"], "phase": s["phase"],
                        "tasks": [{k: t[k] for k in ("id", "title", "status", "owner")} for t in list_tasks(c, sid)],
                        "artifact_version": art["version"] if art else None}
                return tool_ok(data)
            if tool_name == "get_rejoin_metrics":
                return tool_ok(rejoin_metrics(c, body.args), [{"document_id": "rejoin_facts", "chunk_id": None, "version": 1,
                                                               "quote": f"rejoin-data-v1 {body.args.get('dimension')}"}])
            if tool_name == "get_interview_notes":
                released = "user-interviews" not in hidden_document_ids(c, s)
                data = interview_notes(c, body.args, released=released)
                return tool_ok(data, [{"document_id": "interview_notes", "chunk_id": None, "version": 1, "quote": i["quote"]}
                                      for i in data["items"]])
            if tool_name in WRITE_TOOLS:
                return execute_write(c, sid, run, cap, tool_name, body.args)
        return tool_err("NOT_FOUND", f"알 수 없는 도구: {tool_name}")
    except ToolError as e:
        return tool_err(e.code, e.message, e.retryable)
    except ApiError as e:
        return tool_err(e.code, e.message)


def execute_write(c, sid: str, run: dict, cap: dict, tool: str, args: dict) -> dict:
    approval_id = cap.get("approval_id")
    if not approval_id:
        raise ToolError("APPROVAL_REQUIRED", "승인 없이 변경할 수 없습니다")
    a = one(c, "SELECT * FROM approvals WHERE id=%s AND run_id=%s FOR UPDATE", (approval_id, str(run["id"])))
    if not a:
        raise ToolError("APPROVAL_REQUIRED", "승인을 찾을 수 없습니다")
    receipt = one(c, "SELECT result FROM mutation_receipts WHERE operation_id=%s", (f"op:{approval_id}",))
    if receipt:
        return tool_ok(receipt["result"])
    if a["status"] != "APPROVED":
        raise ToolError("APPROVAL_REQUIRED", f"승인 상태가 아닙니다: {a['status']}")
    if a["expires_at"] < now():
        c.execute("UPDATE approvals SET status='EXPIRED' WHERE id=%s", (approval_id,))
        raise ToolError("APPROVAL_EXPIRED", "승인이 만료되었습니다")
    if a["tool_name"] != tool or a["args_hash"] != args_hash(tool, args):
        raise ToolError("OUT_OF_SCOPE", "승인된 인자와 다른 변경입니다")
    check_scope(c, sid, run, tool, args)
    if tool == "patch_artifact_section":
        art = one(c, "SELECT * FROM artifacts WHERE session_id=%s FOR UPDATE", (sid,))
        if section_sha(art["sections"], args["section"]) != a["base_versions"].get("section_sha"):
            c.execute("UPDATE approvals SET status='EXPIRED' WHERE id=%s", (approval_id,))
            raise ToolError("VERSION_CONFLICT", "승인 대기 중 해당 섹션이 변경되었습니다(APPROVAL_STALE)")
        sections = dict(art["sections"])
        sections[args["section"]] = args["content"]
        new_v = art["version"] + 1
        c.execute("UPDATE artifacts SET sections=%s, version=%s WHERE id=%s", (J(sections), new_v, art["id"]))
        rev = one(c, """INSERT INTO artifact_revisions(session_id,artifact_id,version,sections,changed_sections,actor,run_id,source_refs)
                        VALUES (%s,%s,%s,%s,%s,'COLLEAGUE',%s,%s) RETURNING id""",
                  (sid, art["id"], new_v, J(sections), J([args["section"]]), run["id"], J(args.get("citations") or [])))
        result = {"artifact_id": str(art["id"]), "version": new_v, "revision_id": str(rev["id"])}
        record_action(c, sid, "COLLEAGUE", "ARTIFACT_PATCHED", str(rev["id"]), {"section": args["section"], "approval_id": approval_id})
        emit(c, sid, "ARTIFACT_UPDATED", {"version": new_v, "changed_sections": [args["section"]], "actor": "COLLEAGUE"},
             run_id=str(run["id"]))
    else:
        t = one(c, "SELECT * FROM tasks WHERE id=%s FOR UPDATE", (args["task_id"],))
        if t["version"] != args.get("base_version"):
            raise ToolError("VERSION_CONFLICT", "태스크가 이미 변경되었습니다")
        t = one(c, "UPDATE tasks SET status=%s, version=version+1 WHERE id=%s RETURNING *", (args["status"], t["id"]))
        result = {"task": task_dto(t)}
        emit(c, sid, "TASK_UPDATED", {"task": task_dto(t)}, run_id=str(run["id"]))
    c.execute("UPDATE approvals SET status='APPLIED' WHERE id=%s", (approval_id,))
    c.execute("INSERT INTO mutation_receipts(operation_id,session_id,approval_id,result) VALUES (%s,%s,%s,%s)",
              (f"op:{approval_id}", sid, approval_id, J(result)))
    return tool_ok(result)


def tool_ok(data: Any, citations: list | None = None) -> dict:
    return {"ok": True, "data": to_jsonable(data), "error": None, "citations": citations or []}


def tool_err(code: str, message: str, retryable: bool = False) -> dict:
    return {"ok": False, "data": None, "error": {"code": code, "message": message, "retryable": retryable}, "citations": []}


# ---- exam timeline tick (agent ticker → gateway) -----------------------------------------

@router.post("/timeline/tick")
def timeline_tick():
    from ..timeline import fire_due
    fired: dict[str, list[str]] = {}
    with tx(dsn()) as c:
        ids = [r["id"] for r in all_(c, "SELECT id FROM sessions WHERE status='ACTIVE'")]
    for sid in ids:
        with tx(dsn()) as c:
            s = one(c, "SELECT * FROM sessions WHERE id=%s FOR UPDATE SKIP LOCKED", (sid,))
            if s:
                f = fire_due(c, s)
                if f:
                    fired[str(sid)] = f
    return {"fired": fired}


# ---- report: 5개 관찰 영역 규칙 기반 리포트 (DAYZERO_EXAM_SCENARIO §9) --------------------------

class BuildIn(Strict):
    report_id: str
    mode: Literal["RULES_FALLBACK"]


AREAS = [
    ("RESPONSIBILITY", "책임감", ["T-DELAY", "T-DEADLINE"]),
    ("RESPECT_COMMUNICATION", "존중·소통", ["T-ERROR"]),
    ("COLLABORATION", "협력 태도", ["T-SPLIT", "T-HELP"]),
    ("FLEXIBILITY", "유연성", ["T-PIVOT"]),
]
SITUATION = {
    "T-KICKOFF": "팀장이 과제를 공지하고 동료가 인사함", "T-INTERVIEW": "사용자 인터뷰 요약 자료가 공유됨",
    "T-END": "시험 시간 종료", "T-SPLIT": "동료가 업무 분담안을 제안함", "T-HELP": "동료가 유사 서비스 비교 기준에 대해 도움을 요청함",
    "T-DELAY": "사용자 인터뷰 자료 공유가 15분 지연됨", "T-PIVOT": "팀장이 기획 대상을 3개월 이상 미참여 사용자로 변경함",
    "T-ERROR": "동료가 운영 정책과 충돌하는 유료 멤버십 기능을 제안함", "T-DEADLINE": "팀장이 제출과 진행 상황 보고를 요청함",
}
WINDOW_END = {"T-SPLIT": "T-HELP", "T-HELP": "T-DELAY", "T-DELAY": "T-INTERVIEW", "T-PIVOT": "T-ERROR",
              "T-ERROR": "T-DEADLINE", "T-DEADLINE": "T-END"}
CANDIDATE_KINDS = ("MESSAGE_SENT", "ARTIFACT_SAVED", "TASK_STATUS_CHANGED", "TASK_REVIEWED", "SPLIT_ADJUSTED",
                   "SPLIT_CONFIRMED", "APPROVAL_DECIDED", "DOCUMENT_OPENED", "SUBMITTED")
ACTION_TEXT = {"ARTIFACT_SAVED": "기획안 섹션 저장", "TASK_STATUS_CHANGED": "태스크 상태 변경", "TASK_REVIEWED": "동료 결과 검토",
               "SPLIT_ADJUSTED": "업무 분담 조정 요청", "SPLIT_CONFIRMED": "업무 분담 확정", "APPROVAL_DECIDED": "동료 변경 승인/거절",
               "DOCUMENT_OPENED": "자료 열람", "SUBMITTED": "기획안 제출"}


@router.post("/reports/{sid}/build")
def build_report(sid: str, body: BuildIn):
    with tx(dsn()) as c:
        rep = one(c, "SELECT * FROM reports WHERE id=%s AND session_id=%s FOR UPDATE", (body.report_id, sid))
        if not rep or rep["status"] == "READY":
            return {"status": rep["status"] if rep else "NOT_FOUND"}
        s = one(c, "SELECT * FROM sessions WHERE id=%s", (sid,))
        snap = rep["source_snapshot"]
        occ = {o["event_id"]: o for o in all_(c, "SELECT * FROM event_occurrences WHERE session_id=%s", (sid,))}
        acts = all_(c, "SELECT * FROM actions WHERE session_id=%s AND seq<=%s ORDER BY seq", (sid, snap["last_action_seq"]))
        msgs = {str(m["id"]): m for m in all_(c, "SELECT id, channel, actor, content, created_at FROM messages WHERE session_id=%s", (sid,))}
        tools = all_(c, "SELECT t.id, t.tool_name, t.outcome, t.created_at, r.kind FROM tool_calls t JOIN runs r ON r.id=t.run_id WHERE t.session_id=%s", (sid,))
        def mm(v: float | None) -> str:
            v = int(v or 0)
            return f"{v // 60:02d}:{v % 60:02d}"

        trig_seq = {e: o["trigger_action_seq"] for e, o in occ.items()}

        def window(eid: str) -> list[dict]:
            lo = trig_seq[eid]
            hi = trig_seq.get(WINDOW_END.get(eid, ""), 10**12)
            return [a for a in acts if a["actor"] == "CANDIDATE" and lo < a["seq"] < hi and a["kind"] in CANDIDATE_KINDS]

        def fact(a: dict) -> dict:
            if a["kind"] == "MESSAGE_SENT" and a["entity_id"] in msgs:
                m = msgs[a["entity_id"]]
                q = m["content"][:200]
                return {"text": f"{'어시스턴트에' if m['channel'] == 'ASSISTANT' else '팀 채팅에'} 메시지: “{q}”",
                        "at": mm(a["payload"].get("elapsed_min")) if a["payload"].get("elapsed_min") is not None else None,
                        "refs": [{"kind": "message", "id": a["entity_id"], "field": "content", "start": 0,
                                  "end": len(q), "quote": q}], "created_at": m["created_at"].isoformat()}
            label = ACTION_TEXT.get(a["kind"], a["kind"])
            extra = a["payload"].get("section") or a["entity_id"] if a["kind"] in ("ARTIFACT_SAVED", "DOCUMENT_OPENED") else ""
            return {"text": f"{label}{f' ({extra})' if extra else ''}", "refs": [{"kind": "action", "id": str(a["id"]), "field": "kind",
                    "start": None, "end": None, "quote": None}], "created_at": a["created_at"].isoformat()}

        areas = []
        for key, label, events in AREAS:
            situations, facts, any_occ = [], [], False
            for e in events:
                if e not in occ:
                    situations.append({"event_id": e, "situation": SITUATION[e], "status": "NO_OPPORTUNITY", "at": None})
                    continue
                any_occ = True
                w = window(e)
                situations.append({"event_id": e, "situation": SITUATION[e], "status": "OBSERVED" if w else "INSUFFICIENT_EVIDENCE",
                                   "at": mm(occ[e]["occurred_at_min"])})
                facts += [{**fact(a), "event_id": e} for a in w[:8]]
            status = "NO_OPPORTUNITY" if not any_occ else ("OBSERVED" if facts else "INSUFFICIENT_EVIDENCE")
            areas.append({"dimension": key, "label": label, "status": status, "situations": situations, "facts": facts,
                          "interpretation": None,
                          "limits": {"NO_OPPORTUNITY": "관찰 기회 없음(해당 상황이 발생하기 전에 제출됨)",
                                     "INSUFFICIENT_EVIDENCE": "상황은 발생했으나 관련 행동 근거 부족",
                                     "OBSERVED": "기록된 행동 사실만 정리했으며 의미 해석은 사람 검토가 필요함"}[status]})
        asst = [a for a in acts if a["kind"] == "MESSAGE_SENT" and a["entity_id"] in msgs and msgs[a["entity_id"]]["channel"] == "ASSISTANT"]
        asst_tools = [t for t in tools if t["kind"] == "ASSISTANT"]
        areas.append({"dimension": "AI_UTILIZATION", "label": "AI 활용", "status": "OBSERVED" if asst else "NOT_USED",
                      "situations": [{"event_id": None, "situation": "AI 어시스턴트는 시험 내내 자유롭게 사용할 수 있었음", "status": "OBSERVED" if asst else "NOT_USED", "at": None}],
                      "facts": [fact(a) for a in asst[:10]],
                      "usage": {"assistant_requests": len(asst), "assistant_tool_calls": len(asst_tools)},
                      "interpretation": None,
                      "limits": "사용량만으로 평가하지 않음" if asst else "AI 어시스턴트를 사용하지 않음(부정적 판단 근거 아님)"})
        split_actions = [a for a in acts if a["kind"] in ("SPLIT_ADJUSTED", "SPLIT_CONFIRMED")]
        raw = collect_raw_materials(c, sid, s, snap)
        body_ = {
            "schema_version": "2.0", "generation_mode": "RULES_FALLBACK", "policy_version": "exam-v1", "scenario_id": "moarun-rejoin-v1",
            "submitted_by": snap.get("submitted_by"),
            "timeline": [{"event_id": e, "at": mm(o["occurred_at_min"]), "situation": SITUATION.get(e, e)} for e, o in
                         sorted(occ.items(), key=lambda kv: kv[1]["trigger_action_seq"])],
            "areas": areas,
            "split_history": [{"kind": a["kind"], "assignments": a["payload"].get("assignments"), "at": mm(a["payload"].get("elapsed_min"))}
                              for a in split_actions],
            "final_artifact": {"version": snap["artifact_version"], "empty_sections": [k for k, v in snap["sections"].items() if not v.strip()]},
            **raw,
            "limitations": ["단일 가상 과제에서 관찰한 행동이며 성격·채용 성과를 단정하지 않음",
                            "관찰되지 않은 행동은 추정하지 않음", "점수·등급·순위·합격 여부를 생성하지 않음",
                            "LLM 해석 없이 규칙 기반 사실만 포함(RULES_FALLBACK)"],
        }
        c.execute("UPDATE reports SET status='READY', body=%s, attempts=attempts+1 WHERE id=%s", (J(to_jsonable(body_)), rep["id"]))
        emit(c, sid, "REPORT_READY", {"report_id": str(rep["id"])})
    return {"status": "READY"}



# ---- 채팅 수정 요청 → 실제 섹션 수정 작업 생성 ---------------------------------------------

class FollowupIn(Strict):
    sections: list[str] = Field(min_length=1, max_length=3)
    instruction: str = Field(max_length=2000)


@router.post("/runs/{rid}/followup")
def followup(rid: str, body: FollowupIn):
    """지원자가 채팅으로 동료에게 섹션 수정을 요청하면, 해당 섹션의 실제 재작성 run을 만든다.
    반영은 기존과 같이 확인 카드(승인) 후에만 이루어진다."""
    from shared.config import EXAM_MINUTES, SECTION_IDS
    from ..domain import create_run
    created, skipped = [], []
    with tx(dsn()) as c:
        r = one(c, "SELECT * FROM runs WHERE id=%s", (rid,))
        if not r:
            raise ApiError(404, "NOT_FOUND", "run 없음")
        sid = str(r["session_id"])
        s = lock_session(c, sid)
        if s["status"] != "ACTIVE":
            return {"created": [], "skipped": body.sections}
        for sec in body.sections:
            if sec not in SECTION_IDS:
                continue
            t = one(c, "SELECT * FROM tasks WHERE session_id=%s AND template_key=%s FOR UPDATE", (sid, sec))
            busy = one(c, """SELECT 1 FROM runs WHERE session_id=%s AND task_id=%s AND kind='DELEGATED'
                             AND status IN ('QUEUED','RUNNING','WAITING_APPROVAL')""", (sid, t["id"]))
            if busy:
                skipped.append(sec)
                continue
            d = one(c, "SELECT * FROM delegations WHERE id=%s", (t["delegation_id"],)) if t["delegation_id"] else None
            if not d or d["revoked_at"] or d["expires_at"] < now() or sec not in d["section_allowlist"]:
                d = one(c, """INSERT INTO delegations(session_id,task_id,source_message_id,tool_allowlist,section_allowlist,constraints,expires_at)
                              VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
                        (sid, t["id"], r["source_message_id"], J(["get_interview_notes", "get_rejoin_metrics", "search_docs"]),
                         J([sec]), J({"chat_request": True}), s["started_at"] + timedelta(minutes=EXAM_MINUTES)))
                c.execute("UPDATE tasks SET delegation_id=%s WHERE id=%s", (d["id"], t["id"]))
            if t["owner"] == "COLLEAGUE" and t["status"] in ("REVIEW", "DONE", "TODO"):
                t2 = one(c, "UPDATE tasks SET status='IN_PROGRESS', version=version+1 WHERE id=%s RETURNING *", (t["id"],))
                emit(c, sid, "TASK_UPDATED", {"task": task_dto(t2)}, run_id=rid)
            create_run(c, sid, "DELEGATED", source_message_id=str(r["source_message_id"]) if r["source_message_id"] else None,
                       task_id=str(t["id"]), prompt_version="colleague-v2",
                       input_={"revise_comment": body.instruction, "section": sec, "delegation_id": str(d["id"]), "mode": "rewrite"})
            record_action(c, sid, "COLLEAGUE", "REVISION_STARTED", str(t["id"]), {"section": sec, "via": "chat"})
            created.append(sec)
    return {"created": created, "skipped": skipped}



@router.get("/reports/{sid}/body")
def report_body(sid: str):
    with tx(dsn()) as c:
        rep = one(c, "SELECT body FROM reports WHERE session_id=%s", (sid,))
    if not rep or not rep["body"]:
        raise ApiError(404, "NOT_FOUND", "리포트 없음")
    return {"body": rep["body"]}


class InterpretIn(Strict):
    report_id: str
    interpretations: dict[str, dict] = Field(default_factory=dict)
    observations: list[dict] = Field(default_factory=list)


@router.post("/reports/{sid}/interpret")
def report_interpret(sid: str, body: InterpretIn):
    """LLM 제한 해석을 관찰된 영역에만 병합. 사실·근거는 바꾸지 않는다."""
    with tx(dsn()) as c:
        rep = one(c, "SELECT * FROM reports WHERE id=%s AND session_id=%s FOR UPDATE", (body.report_id, sid))
        if not rep or not rep["body"]:
            raise ApiError(404, "NOT_FOUND", "리포트 없음")
        b = dict(rep["body"])
        n = 0
        for a in b["areas"]:
            it = body.interpretations.get(a["dimension"])
            if it and a["status"] == "OBSERVED":
                a["interpretation"] = {"text": str(it.get("text", ""))[:400], "label": "INFERENCE"}
                if it.get("follow_up"):
                    a["follow_up"] = str(it["follow_up"])[:300]
                n += 1
        if body.observations and b.get("raw"):
            b["raw"]["observations"] = [o for o in b["raw"].get("observations", []) if o.get("source") == "RULES"] + [
                {"area": str(o.get("area", ""))[:20], "source": "AI", "text": str(o.get("text", ""))[:300],
                 "at": str(o.get("at") or "")[:5] or None, "quote": str(o.get("quote") or "")[:200] or None} for o in body.observations[:12]]
            n += 1
        if n:
            b["generation_mode"] = "LLM_WITH_RULES"
            b["limitations"] = [x for x in b["limitations"] if "RULES_FALLBACK" not in x] + [
                "제한된 해석은 AI 추정이며 사실 근거(원문 ID)와 분리해 표시함"]
            c.execute("UPDATE reports SET body=%s, attempts=attempts+1 WHERE id=%s", (J(b), rep["id"]))
    return {"interpreted": n}



class ReportFailedIn(Strict):
    report_id: str
    error: str = ""


@router.post("/reports/{sid}/failed")
def report_failed(sid: str, body: ReportFailedIn):
    """REPORT job 실패 시 리포트를 FAILED로 표시. 관리자 '다시 생성'으로 재시도 가능."""
    with tx(dsn()) as c:
        r = one(c, "UPDATE reports SET status='FAILED', error_code='REPORT_JOB_FAILED', attempts=attempts+1 WHERE id=%s AND session_id=%s AND status<>'READY' RETURNING id",
                (body.report_id, sid))
        if r:
            emit(c, sid, "REPORT_FAILED", {"report_id": body.report_id}, admin_payload={"report_id": body.report_id, "error": body.error[:300]})
    return {"status": "FAILED" if r else "UNCHANGED"}



# ---- 사람이 판단할 원자료(판정 없음) -----------------------------------------------------------

SEC_TITLE = {"problem": "문제 정의와 대상 사용자", "interview_evidence": "사용자 인터뷰 근거", "features": "핵심 기능 제안",
             "similar_cases": "비슷한 서비스 사례", "metrics_timeline": "성공 지표와 출시 일정"}


def collect_raw_materials(c, sid: str, s: dict, snap: dict) -> dict:
    """리포트에 원자료를 빠짐없이 싣는다: 동료 요청과 결과, 확인 카드 결정, 기획안 수정 이력, 어시스턴트 대화 전체."""
    off = float((s["policy_state"] or {}).get("time_offset_min", 0) or 0)
    start = s["started_at"]

    from zoneinfo import ZoneInfo

    def at(ts) -> str:  # 실제 기록 시각(KST). 시연 시간 이동과 무관하게 원문 시각을 그대로 보여 준다
        return ts.astimezone(ZoneInfo("Asia/Seoul")).strftime("%H:%M")

    msgs = all_(c, "SELECT id, channel, actor, content, source_run_id, created_at FROM messages WHERE session_id=%s ORDER BY created_at", (sid,))
    runs = all_(c, "SELECT id, kind, source_message_id, task_id, input, status, created_at FROM runs WHERE session_id=%s", (sid,))
    apprs = all_(c, "SELECT id, run_id, before_after, status, created_at, decided_at FROM approvals WHERE session_id=%s ORDER BY created_at", (sid,))
    decided = {a["entity_id"]: a for a in all_(c, "SELECT entity_id, payload, created_at FROM actions WHERE session_id=%s AND kind='APPROVAL_DECIDED'", (sid,))}
    revs = all_(c, """SELECT r.version, r.actor, r.changed_sections, r.sections, r.created_at, r.run_id FROM artifact_revisions r
                      WHERE r.session_id=%s ORDER BY r.version""", (sid,))
    reviews = all_(c, "SELECT entity_id, payload, created_at FROM actions WHERE session_id=%s AND kind='TASK_REVIEWED' ORDER BY seq", (sid,))
    tasks = {str(t["id"]): t for t in all_(c, "SELECT id, template_key FROM tasks WHERE session_id=%s", (sid,))}

    by_run_reply = {}
    for m in msgs:
        if m["actor"] in ("COLLEAGUE", "ASSISTANT") and m["source_run_id"] and str(m["source_run_id"]) not in by_run_reply:
            by_run_reply[str(m["source_run_id"])] = m
    work_by_msg: dict[str, list] = {}
    for r in runs:
        if r["kind"] == "DELEGATED" and r["source_message_id"]:
            work_by_msg.setdefault(str(r["source_message_id"]), []).append(r)
    appr_by_run = {}
    for a in apprs:
        appr_by_run.setdefault(str(a["run_id"]), []).append(a)

    def card_result(run) -> list[dict]:
        out = []
        for a in appr_by_run.get(str(run["id"]), []):
            d = decided.get(str(a["id"]))
            out.append({"section": SEC_TITLE.get(a["before_after"].get("section"), a["before_after"].get("section")),
                        "status": a["status"], "decision": (d or {}).get("payload", {}).get("decision"),
                        "comment": (d or {}).get("payload", {}).get("comment") or ""})
        return out

    colleague_requests, assistant_log = [], []
    for m in msgs:
        if m["actor"] != "CANDIDATE":
            continue
        reply = by_run_reply.get(str(m["source_run_id"])) if m["source_run_id"] else None
        item = {"message_id": str(m["id"]), "at": at(m["created_at"]), "created_at": m["created_at"].isoformat(),
                "request": m["content"], "reply": reply["content"] if reply else None}
        if m["channel"] == "TEAM":
            work = []
            for r in work_by_msg.get(str(m["id"]), []):
                sec = (r["input"] or {}).get("section") or tasks.get(str(r["task_id"]), {}).get("template_key")
                work.append({"section": SEC_TITLE.get(sec, sec), "run_status": r["status"], "cards": card_result(r)})
            item["work_started"] = work
            colleague_requests.append(item)
        else:
            assistant_log.append(item)

    card_decisions = []
    for a in apprs:
        d = decided.get(str(a["id"]))
        card_decisions.append({"at": at(a["created_at"]), "section": SEC_TITLE.get(a["before_after"].get("section"), "-"),
                               "status": a["status"], "decision": (d or {}).get("payload", {}).get("decision"),
                               "comment": (d or {}).get("payload", {}).get("comment") or "",
                               "draft_preview": (a["before_after"].get("after") or "")[:300]})
    revision_history, prev = [], {}
    for r in revs:
        for sec in r["changed_sections"]:
            before, after = prev.get(sec, ""), (r["sections"] or {}).get(sec, "")
            revision_history.append({"at": at(r["created_at"]), "version": r["version"], "section": SEC_TITLE.get(sec, sec),
                                     "actor": "동료(이도현, 확인 카드 승인 후)" if r["actor"] == "COLLEAGUE" else "지원자",
                                     "chars_before": len(before), "chars_after": len(after), "after_preview": after[:200]})
        prev = dict(r["sections"] or {})
    authorship = {}
    for h in revision_history:
        a = authorship.setdefault(h["section"], {"지원자": 0, "동료": 0, "last": None})
        a["동료" if h["actor"].startswith("동료") else "지원자"] += 1
        a["last"] = h["actor"]
    task_reviews = [{"at": at(rv["created_at"]), "section": SEC_TITLE.get(tasks.get(rv["entity_id"], {}).get("template_key"), "-"),
                     "decision": rv["payload"].get("decision"), "comment": rv["payload"].get("comment", "")} for rv in reviews]
    stats = {"colleague_requests": len(colleague_requests), "assistant_questions": len(assistant_log),
             "cards": len(card_decisions), "cards_approved": sum(1 for x in card_decisions if x["status"] in ("APPROVED", "APPLIED")),
             "cards_rejected": sum(1 for x in card_decisions if x["decision"] == "REJECT"),
             "cards_revise": sum(1 for x in card_decisions if x["decision"] == "REVISE"),
             "revisions_by_candidate": sum(1 for h in revision_history if h["actor"] == "지원자"),
             "revisions_by_colleague": sum(1 for h in revision_history if h["actor"].startswith("동료"))}
    obs = []
    obs.append({"area": "협업", "source": "RULES", "text": f"동료에게 {stats['colleague_requests']}건 요청했고, 확인 카드 {stats['cards']}건 중 승인 {stats['cards_approved']}·"
                f"거절 {stats['cards_rejected']}·재수정 요청 {stats['cards_revise']}건을 결정한 것을 확인함", "at": None, "quote": None})
    obs.append({"area": "작성", "source": "RULES", "text": f"기획안 수정 이력 중 지원자 직접 수정 {stats['revisions_by_candidate']}회, "
                f"동료 초안 반영 {stats['revisions_by_colleague']}회를 확인함", "at": None, "quote": None})
    for x in card_decisions:
        if x["decision"] == "REVISE" and x["comment"]:
            obs.append({"area": "협업", "source": "RULES", "text": f"{x['section']} 확인 카드에서 검토 사항을 남기고 재수정을 요청한 것을 확인함",
                        "at": x["at"], "quote": x["comment"][:200]})
    for t in task_reviews:
        if t["comment"]:
            obs.append({"area": "협업", "source": "RULES", "text": f"{t['section']} 태스크 검토({t['decision']})에서 의견을 남긴 것을 확인함",
                        "at": t["at"], "quote": t["comment"][:200]})
    obs.append({"area": "AI 활용", "source": "RULES", "text": f"AI 어시스턴트에 {stats['assistant_questions']}건 질문한 것을 확인함(사용량만으로 평가하지 않음)",
                "at": None, "quote": None})
    return {"raw": {"stats": stats, "observations": obs, "colleague_requests": colleague_requests, "card_decisions": card_decisions,
                    "task_reviews": task_reviews, "revision_history": revision_history, "section_authorship": authorship,
                    "assistant_log": assistant_log}}

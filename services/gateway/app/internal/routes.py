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
from ..business import ToolError, funnel_metrics, support_cases
from ..domain import (artifact_dto, emit, enqueue_policy_check, insert_message, list_tasks, lock_session, now,
                      record_action, task_dto, to_jsonable)
from ..errors import ApiError

router = APIRouter(dependencies=[Depends(internal_service)])
LEASE = timedelta(seconds=150)
READ_TOOLS = {"get_session_context", "get_funnel_metrics", "get_support_cases", "search_docs", "read_resource"}
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
    token, exp = issue_capability(audience=body.audience, session_id=str(r["session_id"]), run_id=rid,
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
                          WHERE session_id=%s AND channel=%s ORDER BY created_at DESC LIMIT 30) m ORDER BY created_at""",
                    (sid, channel))
        art = one(c, "SELECT * FROM artifacts WHERE session_id=%s", (sid,))
        task = one(c, "SELECT * FROM tasks WHERE id=%s", (r["task_id"],)) if r["task_id"] else None
        deleg = one(c, "SELECT * FROM delegations WHERE id=%s", (task["delegation_id"],)) if task and task["delegation_id"] else None
    return to_jsonable({
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
                # 위임 작업 종료(승인 반영 또는 거절) → 지원자 검토 대기. DONE은 지원자 review만 결정.
                t = one(c, "UPDATE tasks SET status='REVIEW', version=version+1 WHERE id=%s AND status='IN_PROGRESS' RETURNING *",
                        (r["task_id"],))
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
            meta = {k: p[k] for k in ("delegation_proposal", "limited", "kind") if k in p}
            if "delegation_proposal" in meta and meta["delegation_proposal"]:
                meta["delegation_proposal"]["source_message_id"] = str(r["source_message_id"])
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
        if ci.get("document_id") == "funnel_facts":
            tc = one(c, "SELECT 1 FROM tool_calls WHERE run_id=%s AND tool_name='get_funnel_metrics' AND outcome='ok' LIMIT 1", (rid,))
            if tc:
                ok.append({"document_id": "funnel_facts", "chunk_id": None, "version": 1, "quote": q[:300]})
            continue
        if ci.get("document_id") == "support_cases":
            row = one(c, "SELECT 1 FROM support_cases WHERE quote LIKE %s", (f"%{q}%",))
            if row:
                ok.append({"document_id": "customer-research", "chunk_id": None, "version": 1, "quote": q})
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
        a = one(c, """INSERT INTO approvals(session_id,run_id,interrupt_id,tool_name,args,args_hash,base_versions,
                      delegation_id,before_after,status,expires_at)
                      VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,'PENDING',now()+interval '10 minutes') RETURNING *""",
                (sid, rid, body.interrupt_id, body.tool_name, J(body.args), h, J(body.base_versions),
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
            if tool_name == "get_funnel_metrics":
                return tool_ok(funnel_metrics(c, body.args), [{"document_id": "funnel_facts", "chunk_id": None, "version": 1,
                                                               "quote": f"cart-data-v1 {body.args.get('period')}/{body.args.get('dimension')}"}])
            if tool_name == "get_support_cases":
                data = support_cases(c, body.args)
                return tool_ok(data, [{"document_id": "support_cases", "chunk_id": None, "version": 1, "quote": i["quote"]}
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
        if art["version"] != a["base_versions"].get("artifact"):
            c.execute("UPDATE approvals SET status='EXPIRED' WHERE id=%s", (approval_id,))
            raise ToolError("VERSION_CONFLICT", "승인 대기 중 기획안이 변경되었습니다(APPROVAL_STALE)")
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


# ---- conditional intervention (POLICY_CHECK job) -----------------------------------------

class PolicyIn(Strict):
    trigger_action_seq: int


@router.post("/sessions/{sid}/policy-check")
def policy_check(sid: str, body: PolicyIn):
    from shared import policies as P
    with tx(dsn()) as c:
        s = lock_session(c, sid)
        if s["status"] != "ACTIVE":
            return {"decision": "SKIPPED_INACTIVE"}
        st = dict(s["policy_state"] or {})
        checked = int(st.get("checked_seq", 0))
        pending = list(st.get("pending", []))
        occurred = {r["event_id"] for r in all_(c, "SELECT event_id FROM event_occurrences WHERE session_id=%s", (sid,))}
        events = {e["id"]: e for e in all_(c, "SELECT * FROM scenario_events")}
        new_actions = all_(c, "SELECT * FROM actions WHERE session_id=%s AND seq>%s AND actor='CANDIDATE' ORDER BY seq", (sid, checked))
        for a in new_actions:
            rev = None
            if a["kind"] == "ARTIFACT_SAVED" and a["entity_id"]:
                row = one(c, "SELECT sections FROM artifact_revisions WHERE id=%s", (a["entity_id"],))
                rev = row["sections"] if row else None
            seg = bool(one(c, """SELECT 1 FROM tool_calls WHERE session_id=%s AND tool_name='get_funnel_metrics' AND outcome='ok'
                                 AND safe_args->>'dimension' <> 'overall' AND created_at <= %s LIMIT 1""", (sid, a["created_at"])))
            ev = P.detect(a, revision_sections=rev, segment_metric_before=seg,
                          review=a["payload"] if a["kind"] == "TASK_REVIEWED" else None)
            if ev and ev not in occurred and all(p["event_id"] != ev for p in pending):
                pending.append({"event_id": ev, "trigger_action_seq": a["seq"],
                                "facts": {"action_kind": a["kind"], "section": a["payload"].get("section")}})
        last_seq = int(st.get("last_intervention_seq", 0))
        since = one(c, "SELECT count(*)::int AS n FROM actions WHERE session_id=%s AND seq>%s AND kind = ANY(%s)",
                    (sid, last_seq, list(P.CANDIDATE_ACTIONS)))["n"]
        cand, decision = P.choose(pending, occurred, {k: v["priority"] for k, v in events.items()},
                                  s["auto_intervention_count"], since, last_seq > 0)
        st["checked_seq"] = max([checked] + [a["seq"] for a in new_actions])
        if cand:
            record_action(c, sid, "SYSTEM", "POLICY_DECISION", cand["event_id"], {"decision": decision, **cand})
        if decision == "EMIT":
            e = events[cand["event_id"]]
            m = insert_message(c, sid, "TEAM", "COLLEAGUE", e["payload"]["message"],
                               meta={"kind": "INTERVENTION", "event_id": cand["event_id"], "help_id": "H1"})
            c.execute("""INSERT INTO event_occurrences(session_id,event_id,trigger_action_seq,facts,response_message_id)
                         VALUES (%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
                      (sid, cand["event_id"], cand["trigger_action_seq"], J(cand["facts"]), m["id"]))
            c.execute("UPDATE sessions SET auto_intervention_count=auto_intervention_count+1 WHERE id=%s", (sid,))
            emit(c, sid, "COLLEAGUE_MESSAGE", {"message_id": str(m["id"]), "content": m["content"], "citations": []},
                 admin_payload={"message_id": str(m["id"]), "content": m["content"], "event_id": cand["event_id"]})
            pending = [p for p in pending if p["event_id"] != cand["event_id"]]
            st["last_intervention_seq"] = one(c, "SELECT last_action_seq FROM sessions WHERE id=%s", (sid,))["last_action_seq"]
        elif decision == "SUPPRESSED_BUDGET":
            pending = [p for p in pending if p["event_id"] != cand["event_id"]]
        st["pending"] = pending
        c.execute("UPDATE sessions SET policy_state=%s WHERE id=%s", (J(st), sid))
    return {"decision": decision, "event_id": cand["event_id"] if cand else None}


# ---- report (M4 최소 구현: 규칙 기반 사실 리포트) -----------------------------------------

class BuildIn(Strict):
    report_id: str
    mode: Literal["RULES_FALLBACK"]


@router.post("/reports/{sid}/build")
def build_report(sid: str, body: BuildIn):
    with tx(dsn()) as c:
        rep = one(c, "SELECT * FROM reports WHERE id=%s AND session_id=%s FOR UPDATE", (body.report_id, sid))
        if not rep or rep["status"] == "READY":
            return {"status": rep["status"] if rep else "NOT_FOUND"}
        snap = rep["source_snapshot"]
        acts = all_(c, "SELECT id, seq, kind, entity_id, payload FROM actions WHERE session_id=%s AND seq<=%s ORDER BY seq",
                    (sid, snap["last_action_seq"]))
        tools = all_(c, "SELECT id, tool_name, help_id, outcome FROM tool_calls WHERE session_id=%s", (sid,))
        occ = all_(c, "SELECT event_id, trigger_action_seq FROM event_occurrences WHERE session_id=%s", (sid,))
        cand_msgs = [a for a in acts if a["kind"] == "MESSAGE_SENT"]

        def ref(a):
            return {"kind": "action", "id": str(a["id"]), "field": "kind", "start": None, "end": None, "quote": None}

        def item(dim, facts, opportunity=True, used=True):
            if not used:
                return {"dimension": dim, "status": "NOT_USED", "facts": [], "interpretation": None, "limits": "사용하지 않음"}
            if not opportunity:
                return {"dimension": dim, "status": "NO_OPPORTUNITY", "facts": [], "interpretation": None, "limits": "관찰 기회 없음"}
            if not facts:
                return {"dimension": dim, "status": "INSUFFICIENT_EVIDENCE", "facts": [], "interpretation": None, "limits": "관련 행동 근거 부족"}
            return {"dimension": dim, "status": "OBSERVED", "facts": facts, "interpretation": None,
                    "limits": "자동 검출은 기록된 사실에 한정되며 의미 해석은 사람 검토가 필요함"}

        k = lambda kind: [a for a in acts if a["kind"] == kind]  # noqa: E731
        opened = k("DOCUMENT_OPENED")
        saves = k("ARTIFACT_SAVED")
        reviews = k("TASK_REVIEWED")
        delegs = k("DELEGATION_CREATED")
        decisions = k("APPROVAL_DECIDED")
        ai_used = bool(cand_msgs or delegs)
        body_ = {
            "schema_version": "1.0", "generation_mode": "RULES_FALLBACK", "policy_version": "help-v1", "scenario_version": 1,
            "opportunities": [{"event_id": o["event_id"], "status": "TRIGGERED", "trigger_action_seq": o["trigger_action_seq"]} for o in occ]
                             + [{"event_id": e, "status": "NOT_TRIGGERED", "trigger_action_seq": None}
                                for e in ("E-CONSTRAINT", "E-VERIFY", "E-SEGMENT") if e not in {o["event_id"] for o in occ}],
            "behavior": [
                item("RESPONSIBILITY", [{"text": f"기획안 섹션을 직접 저장함({a['payload'].get('section')})", "refs": [ref(a)]} for a in saves][:5]),
                item("COMMUNICATION", [{"text": "팀 채팅에 메시지를 보냄", "refs": [ref(a)]} for a in cand_msgs][:5]),
                item("COLLABORATION", [{"text": "동료에게 조사를 위임함", "refs": [ref(a)]} for a in delegs]
                     + [{"text": f"변경 제안에 {a['payload'].get('decision')} 결정함", "refs": [ref(a)]} for a in decisions], used=True),
                item("FLEXIBILITY", [{"text": f"동료 결과를 {a['payload'].get('decision')} 처리함", "refs": [ref(a)]} for a in reviews],
                     opportunity=bool(reviews) or bool(delegs)),
                item("AI_UTILIZATION", [{"text": "AI 동료/어시스턴트에 요청함", "refs": [ref(a)]} for a in cand_msgs][:5], used=ai_used),
            ],
            "work_approach": [
                item("PROBLEM_DEFINITION", [{"text": "problem 섹션을 작성함", "refs": [ref(a)]} for a in saves if a["payload"].get("section") == "problem"][:3]),
                item("EVIDENCE_GATHERING", [{"text": f"자료 열람: {a['entity_id']}", "refs": [ref(a)]} for a in opened][:6]),
                item("OPTION_PRIORITIZATION", [{"text": "options 섹션을 작성함", "refs": [ref(a)]} for a in saves if a["payload"].get("section") == "options"][:3]),
                item("VALIDATION_PLAN", [{"text": "experiment 섹션을 작성함", "refs": [ref(a)]} for a in saves if a["payload"].get("section") == "experiment"][:3]),
                item("REVISION", [{"text": f"동료 결과 검토({a['payload'].get('decision')})", "refs": [ref(a)]} for a in reviews][:3],
                     opportunity=bool(reviews) or bool(delegs)),
            ],
            "help_delivered": [{"help_id": h, "tool_call_ids": [str(t["id"]) for t in tools if t["help_id"] == h]}
                               for h in sorted({t["help_id"] for t in tools})],
            "empty_sections": [s for s, v in snap["sections"].items() if not v.strip()],
            "limitations": ["단일 가상 과제에서 관찰한 행동이며 성격·채용 성과를 단정하지 않음",
                            "LLM 해석 없이 규칙 기반 사실만 포함(RULES_FALLBACK)"],
        }
        c.execute("UPDATE reports SET status='READY', body=%s, attempts=attempts+1 WHERE id=%s", (J(body_), rep["id"]))
        emit(c, sid, "REPORT_READY", {"report_id": str(rep["id"])})
    return {"status": "READY"}

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
from shared.scenario import public_definition, contextual_targets, claim_kind, targets_in

from ..domain import elapsed_seconds

from .. import engine
from ..auth import internal_service, issue_capability, verify_capability
from ..business import ToolError, get_next_event, get_planted_error, get_scenario, record_observation, session_context
from ..domain import (artifact_dto, emit, insert_message, lock_session, now, post_line, record_action, scenario_def,
                      set_state, task_dto, to_jsonable)
from ..errors import ApiError
from ..report import build_report_body

router = APIRouter(dependencies=[Depends(internal_service)])
LEASE = timedelta(seconds=150)
READ_TOOLS = {"get_session_context", "get_scenario", "get_next_event", "get_planted_error",
              "search_docs", "search_criteria", "read_resource", "read_artifact", "edit_own_artifact"}
LOG_TOOLS = {"record_observation"}  # 변경이지만 승인 불필요(관찰 기록만, 업무 산출물은 바꾸지 않음)
WRITE_TOOLS = {"update_task_status", "suggest_candidate_edit"}  # 승인 필요
MESSAGE_EVENTS = {"COLLEAGUE_MESSAGE": "COLLEAGUE", "MANAGER_MESSAGE": "MANAGER", "SYSTEM_NOTICE": "SYSTEM"}
COLLEAGUE_ARTIFACTS = {"T2", "T3"}  # 서윤 초안에서 시작한 산출물(서윤이 승인 후 고칠 수 있는 범위)


def dsn() -> str:
    return settings().psycopg_dsn


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


def args_hash(tool: str, args: dict) -> str:
    return hashlib.sha256(json.dumps({"tool": tool, "args": args}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


# ---- jobs -----------------------------------------------------------------

class ClaimIn(Strict):
    worker_id: str
    kinds: list[Literal["AGENT", "REPORT"]]


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
    tools = sorted(READ_TOOLS | LOG_TOOLS | (WRITE_TOOLS if body.approval_id else set()))
    token, exp = issue_capability(audience=body.audience, session_id=str(r["session_id"]), run_id=rid,
                                  actor="COLLEAGUE", allowed_tools=tools, delegation_id=None)
    import jwt
    claims = jwt.decode(token, settings().internal_service_secret, algorithms=["HS256"], audience=body.audience)
    with tx(dsn()) as c:
        msgs = all_(c, "SELECT actor, content FROM (SELECT actor, content, created_at FROM messages WHERE session_id=%s ORDER BY created_at DESC LIMIT 6) m ORDER BY created_at", (r["session_id"],))
    text = (r["input"] or {}).get("content", "")
    claims["allow_brief"] = bool(contextual_targets(text, msgs) or claim_kind(text) == "WRONG")
    if body.approval_id:
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
        sc = scenario_def(c, s)
        st = engine.state(s)
        ev_id = (r["input"] or {}).get("event_id") or st.get("active_event")
        ev = next((e for e in public_definition(sc)["events"] if e["id"] == ev_id), None)
        msgs = all_(c, """SELECT * FROM (SELECT id, actor, content, meta, turn, created_at FROM messages
                          WHERE session_id=%s ORDER BY created_at DESC LIMIT 40) m ORDER BY created_at""", (sid,))
        tasks = {t["key"]: t for t in all_(c, "SELECT * FROM tasks WHERE session_id=%s", (sid,))}
        arts = all_(c, "SELECT * FROM artifacts WHERE session_id=%s ORDER BY key", (sid,))
        occ = all_(c, "SELECT event_id, turn, skipped FROM event_occurrences WHERE session_id=%s ORDER BY created_at", (sid,))
        pb = st.get("pushback") or {}
        allow = {"E0": not pb.get("E0") and ev_id == "E0", "E2": not pb.get("E2") and ev_id in ("E2", "E2B")}
        revs = all_(c, """SELECT a.key, r.actor, r.turn FROM artifact_revisions r JOIN artifacts a ON a.id=r.artifact_id
                          WHERE r.session_id=%s ORDER BY r.created_at""", (sid,))
        part = one(c, "SELECT alias FROM participants WHERE id=%s", (s["participant_id"],))
    return to_jsonable({
        "candidate_alias": part["alias"] if part else "지원자",
        "run": {"id": rid, "kind": r["kind"], "status": r["status"], "input": r["input"], "trace_id": r["trace_id"],
                "source_message_id": r["source_message_id"], "thread_id": r["thread_id"]},
        "session": {"id": sid, "status": s["status"], "turn_count": s["turn_count"], "elapsed_seconds": elapsed_seconds(s)},
        "state": {k: st.get(k) for k in ("active_event", "awaiting", "colleague", "pushback", "pushback_pending",
                                          "e2_asked_colleague", "e4", "manager_answered", "split")},
        "event": ev, "allow_pushback": allow,
        "feedback_rules": sc["characters"]["colleague"]["feedback_rules"],
        "characters": {k: {"name": v["name"], "role": v["role"], "traits": v["traits"]} for k, v in sc["characters"].items()},
        "task_summary": sc["task_summary"],
        "messages": msgs,
        "artifacts": [{"key": a["key"], "title": a["title"], "body": a["body"], "version": a["version"],
                       "owner": (tasks.get(a["key"]) or {}).get("owner")} for a in arts],
        "tasks": [task_dto(t) for t in tasks.values()],
        "events": occ, "revisions": revs,
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
            emit(c, sid, "DONE" if body.status == "SUCCEEDED" else "FAILED",
                 {"status": body.status, "error_code": body.error_code}, run_id=rid,
                 client_event_id=f"terminal:{body.status}")
            # 메시지 턴의 이벤트 발생·무응답 처리는 응답(승인 카드 포함)이 끝난 뒤 — 대화 순서 유지,
            # 승인 대기 중에는 새 이벤트(예: E3 서윤 이탈)를 일으키지 않는다
            s = lock_session(c, sid)
            engine.tick(c, s)
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
            return {"seq": None, "dropped": "run cancelled or session ended"}
        dup = one(c, "SELECT seq FROM stream_events WHERE run_id=%s AND client_event_id=%s", (rid, body.client_event_id))
        if dup:
            return {"seq": dup["seq"]}
        p = dict(body.payload)
        if body.type in MESSAGE_EVENTS:
            meta = {k: p[k] for k in ("kind", "event_id", "label", "limited") if k in p}
            m = insert_message(c, sid, MESSAGE_EVENTS[body.type], str(p.get("content", ""))[:8000],
                               citations=p.get("citations") or [], source_run_id=rid, meta=meta)
            p = {"message_id": str(m["id"]), "content": m["content"], "citations": m["citations"], "meta": meta}
        elif body.type == "TOOL_END":
            tc = one(c, """INSERT INTO tool_calls(session_id,run_id,tool_name,safe_args,result_summary,citations,outcome,duration_ms)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                     (sid, rid, p.get("tool_name"), J(p.get("safe_args") or {}), J(p.get("result_summary") or {}),
                      J(p.get("citations") or []), p.get("outcome", "ok"), int(p.get("duration_ms", 0))))
            p = {"tool_call_id": str(tc["id"]), "display_name": p.get("tool_name"), "outcome": p.get("outcome")}
        elif body.type == "TOOL_START":
            p = {"tool_call_id": p.get("tool_call_id"), "display_name": p.get("tool_name")}
        else:
            raise ApiError(422, "VALIDATION_ERROR", f"허용되지 않는 이벤트 type: {body.type}")
        seq = emit(c, sid, body.type, p, run_id=rid, client_event_id=body.client_event_id)
    return {"seq": seq, "payload": p}


# ---- branch effects (agent → gateway 턴 엔진 상태) ----------------------------------------------

class SplitEffect(Strict):
    label: str
    confirm: bool
    proposal: dict


class BranchIn(Strict):
    event_id: str | None = None
    label: str
    pushback_used: Literal["E0", "E2"] | None = None
    pushback_pending: dict | None = None
    clear_pushback_pending: bool = False
    e2_asked_colleague: bool = False
    e2b_accepted: bool = False
    commitment: dict | None = None
    colleague_reply_used: bool = False
    manager_answered: str | None = None
    e4_stage: Literal["FOLLOW_UP", "DONE"] | None = None
    end_session: bool = False
    split: SplitEffect | None = None


@router.post("/runs/{rid}/branch")
def branch(rid: str, body: BranchIn):
    """분기 결과가 바꾸는 세션 상태만 반영한다(반문 1회 플래그, E2B 조건, 약속 등록, 오프라인 답장 소진, 분업 확정, E4 종료)."""
    with tx(dsn()) as c:
        r = one(c, "SELECT * FROM runs WHERE id=%s", (rid,))
        if not r:
            raise ApiError(404, "NOT_FOUND", "run 없음")
        sid = str(r["session_id"])
        s = lock_session(c, sid)
        if s["status"] != "ACTIVE" or r["status"] == "CANCELLED":
            return {"applied": False}
        st = engine.state(s)
        if body.pushback_used:
            st["pushback"] = {**(st.get("pushback") or {}), body.pushback_used: True}
        if body.pushback_pending is not None:
            st["pushback_pending"] = body.pushback_pending
        if body.clear_pushback_pending:
            st["pushback_pending"] = None
        if body.e2_asked_colleague:
            st["e2_asked_colleague"] = True
        if body.e2b_accepted:
            st["e2b_accepted"] = True
        if body.colleague_reply_used:
            col = dict(st.get("colleague") or {})
            col["offline_replies_left"] = max(0, int(col.get("offline_replies_left", 0)) - 1)
            st["colleague"] = col
        if body.manager_answered:
            st["manager_answered"] = sorted(set(st.get("manager_answered") or []) | {body.manager_answered})
        if body.e4_stage:
            st["e4"] = {"stage": body.e4_stage}
        set_state(c, s, st)
        if body.commitment and r["source_message_id"]:
            c.execute("""INSERT INTO commitments(session_id,message_id,text,event_id,registered_turn)
                         VALUES (%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
                      (sid, r["source_message_id"], str(body.commitment.get("text", ""))[:500], body.event_id, s["turn_count"]))
        record_action(c, sid, "COLLEAGUE", "BRANCH", body.event_id, {"label": body.label, "run_id": rid})
        if body.split:
            if body.split.confirm:
                engine.confirm_split(c, s, body.split.proposal, label=body.split.label)
            else:
                st = engine.state(s)
                st["split"] = {**st["split"], "proposal": body.split.proposal, "last_label": body.split.label}
                set_state(c, s, st)
                emit(c, sid, "SPLIT_UPDATED", {"split": engine.public_split(st)})
    return {"applied": True}


# ---- approvals --------------------------------------------------------------

class ProposalIn(Strict):
    interrupt_id: str
    tool_name: Literal["update_task_status", "suggest_candidate_edit"]
    args: dict
    base_versions: dict


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
        if body.tool_name == "suggest_candidate_edit":
            a = one(c, "SELECT * FROM artifacts WHERE session_id=%s AND key=%s", (sid, body.args["artifact_key"]))
            ba = {"artifact_key": a["key"], "title": a["title"], "before": a["body"], "after": body.args["content"],
                  "targets": body.args.get("targets", [])}
            base_versions = {"artifact_version": a["version"]}
        else:
            t = one(c, "SELECT * FROM tasks WHERE session_id=%s AND key=%s", (sid, body.args.get("task_key")))
            ba = {"task_key": t["key"], "before": t["status"], "after": body.args.get("status")}
            base_versions = {"task_version": t["version"]}
        h = args_hash(body.tool_name, body.args)
        a = one(c, """INSERT INTO approvals(session_id,run_id,interrupt_id,tool_name,args,args_hash,base_versions,
                      before_after,status,expires_at)
                      VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'PENDING',now()+interval '15 minutes') RETURNING *""",
                (sid, rid, body.interrupt_id, body.tool_name, J(body.args), h, J(base_versions), J(ba)))
        c.execute("UPDATE runs SET status='WAITING_APPROVAL', updated_at=now() WHERE id=%s", (rid,))
        emit(c, sid, "APPROVAL_REQUIRED", {"approval_id": str(a["id"]), "tool_name": body.tool_name, **ba,
                                           "expires_at": a["expires_at"].isoformat()}, run_id=rid)
    return {"approval_id": str(a["id"]), "args_hash": h, "expires_at": a["expires_at"].isoformat(), "status": "PENDING"}


def is_review_request(run: dict) -> bool:
    import re
    text = (run.get("input") or {}).get("content", "")
    return bool(re.search(r"검토|리뷰|봐\s*주|봐주|확인해\s*주|확인\s*부탁", text) and
                re.search(r"제|제가|내|T1|T5|안내문|푸시|공지", text, re.I))


def check_scope(c, sid: str, run: dict, tool: str, args: dict) -> None:
    """서윤은 지원자의 정정 요청(메시지)으로 시작된 run에서만, 자기 초안 산출물(T2·T3)·자기 태스크만 고칠 수 있다."""
    if run["kind"] != "TEAM" or not run["source_message_id"]:
        raise ToolError("OUT_OF_SCOPE", "지원자 요청으로 시작된 작업에서만 변경을 제안할 수 있습니다")
    if tool in ("suggest_candidate_edit", "edit_own_artifact"):
        task = one(c, "SELECT owner FROM tasks WHERE session_id=%s AND key=%s", (sid, args.get("artifact_key")))
        if not task:
            raise ToolError("NOT_FOUND", "산출물이 없습니다")
        if tool == "edit_own_artifact" and task["owner"] not in ("COLLEAGUE", "SPLIT"):
            raise ToolError("OUT_OF_SCOPE", "서윤 담당 문서만 바로 수정할 수 있습니다")
        if tool == "suggest_candidate_edit":
            if not is_review_request(run):
                raise ToolError("OUT_OF_SCOPE", "지원자의 검토 요청이 필요합니다")
            read = one(c, "SELECT 1 FROM actions WHERE session_id=%s AND kind='ARTIFACT_READ' AND payload->>'run_id'=%s AND payload->>'key'=%s", (sid, str(run["id"]), args.get("artifact_key")))
            if not read:
                raise ToolError("OUT_OF_SCOPE", "실제 문서를 먼저 읽어야 합니다")
        if tool == "suggest_candidate_edit" and task["owner"] not in ("CANDIDATE", "SPLIT"):
            raise ToolError("OUT_OF_SCOPE", "지원자 담당 문서의 검토 수정안만 제안할 수 있습니다")
    elif tool == "update_task_status":
        t = one(c, "SELECT owner FROM tasks WHERE session_id=%s AND key=%s", (sid, args.get("task_key")))
        if not t:
            raise ToolError("NOT_FOUND", "태스크가 없습니다")
        if t["owner"] != "COLLEAGUE":
            raise ToolError("OUT_OF_SCOPE", "서윤 담당 태스크만 변경할 수 있습니다")
        if args.get("status") not in ("IN_PROGRESS", "DONE"):
            raise ToolError("OUT_OF_SCOPE", "IN_PROGRESS/DONE으로만 변경할 수 있습니다")


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
            if tool_name == "read_artifact":
                a = one(c, "SELECT * FROM artifacts WHERE session_id=%s AND key=%s", (sid, body.args.get("artifact_key")))
                if not a:
                    raise ToolError("NOT_FOUND", "산출물이 없습니다")
                task = one(c, "SELECT owner FROM tasks WHERE session_id=%s AND key=%s", (sid, a["key"]))
                if task and task["owner"] in ("CANDIDATE", "SPLIT") and not is_review_request(run):
                    raise ToolError("OUT_OF_SCOPE", "지원자 문서 검토 요청이 없습니다")
                record_action(c, sid, "COLLEAGUE", "ARTIFACT_READ", str(a["id"]), {"run_id": rid, "key": a["key"]})
                return tool_ok(artifact_dto(a))
            if tool_name == "edit_own_artifact":
                return edit_own(c, s, run, body.args)
            if tool_name == "get_session_context":
                return tool_ok(session_context(c, s))
            if tool_name == "get_scenario":
                return tool_ok(get_scenario(c, s))
            if tool_name == "get_next_event":
                return tool_ok(get_next_event(c, s))
            if tool_name == "get_planted_error":
                return tool_ok(get_planted_error(c, s, body.args))
            if tool_name == "record_observation":
                return tool_ok(record_observation(c, s, run, body.args))
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
    if tool == "suggest_candidate_edit":
        art = one(c, "SELECT * FROM artifacts WHERE session_id=%s AND key=%s FOR UPDATE", (sid, args["artifact_key"]))
        if art["version"] != a["base_versions"].get("artifact_version"):
            c.execute("UPDATE approvals SET status='EXPIRED' WHERE id=%s", (approval_id,))
            raise ToolError("VERSION_CONFLICT", "승인 대기 중 산출물이 변경되었습니다(APPROVAL_STALE)")
        before = art["body"]
        art = one(c, "UPDATE artifacts SET body=%s, version=version+1 WHERE id=%s RETURNING *", (args["content"], art["id"]))
        turn = one(c, "SELECT turn_count FROM sessions WHERE id=%s", (sid,))["turn_count"]
        rev = one(c, """INSERT INTO artifact_revisions(session_id,artifact_id,version,body_before,body_after,actor,run_id,turn,meta)
                        VALUES (%s,%s,%s,%s,%s,'COLLEAGUE',%s,%s,%s) RETURNING id""",
                  (sid, art["id"], art["version"], before, args["content"], run["id"], turn,
                   J({"targets": args.get("targets", []), "approval_id": approval_id})))
        result = {"artifact_key": art["key"], "version": art["version"], "revision_id": str(rev["id"])}
        record_action(c, sid, "COLLEAGUE", "ARTIFACT_PATCHED", str(rev["id"]), {"key": art["key"], "approval_id": approval_id,
                                                                                "targets": args.get("targets", [])})
        emit(c, sid, "ARTIFACT_UPDATED", {"artifact": artifact_dto(art), "actor": "COLLEAGUE"}, run_id=str(run["id"]))
    else:
        t = one(c, "SELECT * FROM tasks WHERE session_id=%s AND key=%s FOR UPDATE", (sid, args["task_key"]))
        if t["version"] != args.get("base_version"):
            raise ToolError("VERSION_CONFLICT", "태스크가 이미 변경되었습니다")
        t = one(c, "UPDATE tasks SET status=%s, version=version+1 WHERE id=%s RETURNING *", (args["status"], t["id"]))
        result = {"task": task_dto(t)}
        emit(c, sid, "TASK_UPDATED", {"task": task_dto(t)}, run_id=str(run["id"]))
    c.execute("UPDATE approvals SET status='APPLIED' WHERE id=%s", (approval_id,))
    c.execute("INSERT INTO mutation_receipts(operation_id,session_id,approval_id,result) VALUES (%s,%s,%s,%s)",
              (f"op:{approval_id}", sid, approval_id, J(result)))
    return tool_ok(result)


def edit_own(c, s: dict, run: dict, args: dict) -> dict:
    from shared.scenario import contradicts_brief
    sid = str(s["id"])
    check_scope(c, sid, run, "edit_own_artifact", args)
    art = one(c, "SELECT * FROM artifacts WHERE session_id=%s AND key=%s FOR UPDATE", (sid, args["artifact_key"]))
    # A replay after a crash returns the committed mutation without adding another version.
    existing = one(c, "SELECT id, version FROM artifact_revisions WHERE artifact_id=%s AND run_id=%s AND version=%s",
                   (art["id"], run["id"], args["base_version"]+1))
    if existing:
        return tool_ok({"artifact_key": art["key"], "version": existing["version"], "revision_id": str(existing["id"]), "replayed": True})
    if art["version"] != args["base_version"]:
        raise ToolError("VERSION_CONFLICT", "작업본이 변경되었습니다")
    msgs = all_(c, "SELECT actor, content FROM (SELECT actor, content, created_at FROM messages WHERE session_id=%s ORDER BY created_at DESC LIMIT 6) m ORDER BY created_at", (sid,))
    request_text = (run.get("input") or {}).get("content", "")
    if claim_kind(request_text) == "WRONG":
        raise ToolError("CONTRADICTS_BRIEF", "브리프에 맞는 내용을 틀렸다고 지적했습니다")
    requested = contextual_targets(request_text, msgs)
    targets = args.get("targets") or []
    if not targets or (requested and any(x not in requested for x in targets)):
        raise ToolError("OUT_OF_SCOPE", "요청받지 않은 대상을 수정할 수 없습니다")
    expected = art["body"]
    defs = one(c, "SELECT fixes FROM scenarios WHERE id=%s", (s["scenario_id"],))["fixes"]
    for target in targets:
        for op in defs.get(target, []):
            if op.get("artifact") != art["key"]:
                continue
            if op["op"] == "replace":
                expected = expected.replace(op["find"], op["replace"])
            elif op["op"] == "insert_before" and op["text"].strip() not in expected:
                idx = expected.find(op["anchor"])
                expected = expected[:idx] + op["text"] + expected[idx:] if idx >= 0 else expected.rstrip("\n") + "\n" + op["text"].strip() + "\n"
    if expected != args["content"]:
        raise ToolError("OUT_OF_SCOPE", "요청 대상 외의 변경은 허용되지 않습니다")
    if contradicts_brief(art["body"], args["content"], scenario_def(c, s)):
        raise ToolError("CONTRADICTS_BRIEF", "브리프와 어긋나는 수정입니다")
    if art["body"] == args["content"]:
        return tool_ok({"artifact_key": art["key"], "version": art["version"], "changed": False})
    before = art["body"]
    art = one(c, "UPDATE artifacts SET body=%s, version=version+1 WHERE id=%s RETURNING *", (args["content"], art["id"]))
    rev = one(c, """INSERT INTO artifact_revisions(session_id,artifact_id,version,body_before,body_after,actor,run_id,turn,meta)
                    VALUES (%s,%s,%s,%s,%s,'COLLEAGUE',%s,%s,%s) RETURNING id""",
              (sid, art["id"], art["version"], before, art["body"], run["id"], s["turn_count"],
               J({"targets": args.get("targets", []), "elapsed_seconds": elapsed_seconds(s), "event_id": engine.state(s).get("active_event")})))
    record_action(c, sid, "COLLEAGUE", "ARTIFACT_PATCHED", str(rev["id"]), {"key": art["key"], "run_id": str(run["id"])})
    emit(c, sid, "ARTIFACT_UPDATED", {"artifact": artifact_dto(art), "actor": "COLLEAGUE", "before": before, "after": art["body"]}, run_id=str(run["id"]))
    return tool_ok({"artifact_key": art["key"], "version": art["version"], "revision_id": str(rev["id"]), "before": before, "after": art["body"]})


def tool_ok(data: Any, citations: list | None = None) -> dict:
    return {"ok": True, "data": to_jsonable(data), "error": None, "citations": citations or []}


def tool_err(code: str, message: str, retryable: bool = False) -> dict:
    return {"ok": False, "data": None, "error": {"code": code, "message": message, "retryable": retryable}, "citations": []}


# ---- report (REPORT job → gateway) ----------------------------------------------------------

class BuildIn(Strict):
    report_id: str
    hold: bool = False  # True면 본문만 저장(RUNNING)하고 회사 조항 연결(/criteria) 뒤에 READY


@router.post("/reports/{sid}/build")
def build_report(sid: str, body: BuildIn):
    with tx(dsn()) as c:
        rep = one(c, "SELECT * FROM reports WHERE id=%s AND session_id=%s FOR UPDATE", (body.report_id, sid))
        if not rep or rep["status"] == "READY":
            return {"status": rep["status"] if rep else "NOT_FOUND"}
        s = one(c, "SELECT * FROM sessions WHERE id=%s", (sid,))
        report = build_report_body(c, s, rep["source_snapshot"])
        status = "RUNNING" if body.hold else "READY"
        c.execute("UPDATE reports SET status=%s, body=%s, attempts=attempts+1 WHERE id=%s", (status, J(to_jsonable(report)), rep["id"]))
        if status == "READY":
            emit(c, sid, "REPORT_READY", {"report_id": str(rep["id"])})
    return {"status": status}


@router.get("/reports/{sid}/body")
def report_body(sid: str):
    with tx(dsn()) as c:
        rep = one(c, "SELECT body FROM reports WHERE session_id=%s", (sid,))
    if not rep or not rep["body"]:
        raise ApiError(404, "NOT_FOUND", "리포트 없음")
    return {"body": rep["body"]}


class CriterionLink(Strict):
    competency: str
    index: int
    criterion: dict


class CriteriaIn(Strict):
    report_id: str
    company_id: str
    company_name: str | None = None
    links: list[CriterionLink] = Field(default_factory=list)
    error: str | None = None


@router.post("/reports/{sid}/criteria")
def report_criteria(sid: str, body: CriteriaIn):
    """관찰 코드마다 회사 조항(company-mcp search_criteria 상위 1개)을 linked_criterion으로 붙이고 READY.
    연결은 근거 첨부일 뿐 판정이 아니다. 조항 원문(quote)은 바꾸지 않는다. 검색 유사도(score)는 지원자 점수로 오해될 수 있어 저장하지 않는다."""
    with tx(dsn()) as c:
        rep = one(c, "SELECT * FROM reports WHERE id=%s AND session_id=%s FOR UPDATE", (body.report_id, sid))
        if not rep or not rep["body"]:
            raise ApiError(404, "NOT_FOUND", "리포트 없음")
        b = dict(rep["body"])
        comps = {cp["key"]: cp for cp in b["competencies"]}
        n = 0
        for ln in body.links:
            obs = comps.get(ln.competency, {}).get("observations", [])
            cr = ln.criterion
            if 0 <= ln.index < len(obs) and cr.get("quote"):
                doc = cr.get("doc_title") or cr.get("doc_id")
                obs[ln.index]["linked_criterion"] = {
                    **{k: cr.get(k) for k in ("company_id", "company_name", "doc_id", "doc_title", "section", "title", "quote", "uri")},
                    "text": f"이 행동은 귀사 「{doc}」 {cr.get('section')} '{cr.get('title')}' 조항과 관련됩니다"}
                n += 1
        b["company"] = {"company_id": body.company_id, "company_name": body.company_name, "linked": n,
                        "status": "UNAVAILABLE" if body.error else "LINKED", "error": (body.error or None) and body.error[:200],
                        "note": "회사 조항 연결은 근거 첨부이며 좋다·나쁘다 판정이 아닙니다"}
        c.execute("UPDATE reports SET status='READY', body=%s WHERE id=%s", (J(b), rep["id"]))
        emit(c, sid, "REPORT_READY", {"report_id": str(rep["id"])})
    return {"linked": n}


class SummaryIn(Strict):
    report_id: str
    summaries: dict[str, str] = Field(default_factory=dict)


@router.post("/reports/{sid}/summaries")
def report_summaries(sid: str, body: SummaryIn):
    """(live) 역량별 근거 요약 1문장을 관찰된 역량에만 병합. 코드·근거는 바꾸지 않는다."""
    with tx(dsn()) as c:
        rep = one(c, "SELECT * FROM reports WHERE id=%s AND session_id=%s FOR UPDATE", (body.report_id, sid))
        if not rep or not rep["body"]:
            raise ApiError(404, "NOT_FOUND", "리포트 없음")
        b = dict(rep["body"])
        n = 0
        for comp in b["competencies"]:
            text = body.summaries.get(comp["key"])
            if text and comp["status"] == "OBSERVED":
                comp["evidence_summary"] = {"text": text[:300], "label": "AI 요약(근거 원문 확인 필요)"}
                n += 1
        if n:
            b["generation_mode"] = "RULES_WITH_AI_SUMMARY"
            c.execute("UPDATE reports SET body=%s WHERE id=%s", (J(b), rep["id"]))
    return {"merged": n}


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

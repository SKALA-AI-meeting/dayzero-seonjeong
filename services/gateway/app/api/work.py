"""Delegation, review, approval decision, submit, debrief, admin report API."""
from __future__ import annotations

import hashlib
import json
from datetime import timedelta
from typing import Literal

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, ConfigDict, Field

from shared.config import settings
from shared.db import J, all_, one, tx

from ..auth import Principal, admin, candidate, principal
from ..domain import (active_run, create_run, emit, enqueue_job, enqueue_policy_check, lock_session, now,
                      read_session, record_action, task_dto)
from ..errors import ApiError
from .sessions import EvidenceRef

router = APIRouter()
READ_TOOLS = ["get_funnel_metrics", "get_support_cases", "search_docs"]
FILTER_ENUMS = {"device": {"mobile", "desktop"}, "visitor": {"new", "returning"}, "cart_value": {"low", "high"}}


def dsn() -> str:
    return settings().psycopg_dsn


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DelegationIn(Strict):
    source_message_id: str
    title: str = Field(min_length=1, max_length=160)
    target_section: Literal["evidence"]
    allowed_tools: list[str] = Field(min_length=1, max_length=3)
    filters: dict[str, str] = Field(default_factory=dict)


@router.post("/sessions/{sid}/delegations", status_code=201)
def create_delegation(sid: str, body: DelegationIn, idempotency_key: str = Header(min_length=8, max_length=64),
                      p: Principal = Depends(candidate)):
    req_hash = hashlib.sha256(json.dumps(body.model_dump(), sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    with tx(dsn()) as c:
        lock_session(c, sid, p, require_active=True)
        prev = one(c, "SELECT payload FROM actions WHERE session_id=%s AND kind='DELEGATION_CREATED' AND payload->>'idempotency_key'=%s",
                   (sid, idempotency_key))
        if prev:
            if prev["payload"]["request_hash"] != req_hash:
                raise ApiError(409, "ALREADY_USED", "같은 Idempotency-Key로 다른 요청을 보낼 수 없습니다")
            return prev["payload"]["response"]
        if set(body.allowed_tools) - set(READ_TOOLS):
            raise ApiError(422, "VALIDATION_ERROR", "위임에는 조사 도구만 선택할 수 있습니다")
        for k, v in body.filters.items():
            if k not in FILTER_ENUMS or v not in FILTER_ENUMS[k]:
                raise ApiError(422, "VALIDATION_ERROR", f"허용되지 않는 조사 범위: {k}={v}")
        src = one(c, "SELECT id FROM messages WHERE id=%s AND session_id=%s", (body.source_message_id, sid))
        if not src:
            raise ApiError(404, "NOT_FOUND", "원본 메시지를 찾을 수 없습니다")
        busy = active_run(c, sid)
        if busy:
            raise ApiError(409, "RUN_BUSY", "진행 중인 동료 작업이 끝난 뒤 위임할 수 있습니다")
        t = one(c, """INSERT INTO tasks(session_id,title,status,owner,target_section) VALUES (%s,%s,'IN_PROGRESS','COLLEAGUE','evidence')
                      RETURNING *""", (sid, body.title))
        d = one(c, """INSERT INTO delegations(session_id,task_id,source_message_id,tool_allowlist,section_allowlist,constraints,expires_at)
                      VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
                (sid, t["id"], body.source_message_id, J(sorted(body.allowed_tools)), J(["evidence"]),
                 J({"filters": body.filters}), now() + timedelta(minutes=30)))
        t = one(c, "UPDATE tasks SET delegation_id=%s WHERE id=%s RETURNING *", (d["id"], t["id"]))
        run = create_run(c, sid, "DELEGATED", source_message_id=body.source_message_id, task_id=str(t["id"]),
                         input_={"delegation_id": str(d["id"]), "filters": body.filters}, prompt_version="colleague-v1")
        resp = {"delegation": {"id": str(d["id"]), "task_id": str(t["id"]), "tool_allowlist": d["tool_allowlist"],
                               "section_allowlist": d["section_allowlist"], "expires_at": d["expires_at"].isoformat()},
                "task": task_dto(t), "run_id": str(run["id"])}
        seq = record_action(c, sid, "CANDIDATE", "DELEGATION_CREATED", str(d["id"]),
                            {"idempotency_key": idempotency_key, "request_hash": req_hash, "response": resp,
                             "source_message_id": body.source_message_id, "filters": body.filters})
        emit(c, sid, "TASK_UPDATED", {"task": task_dto(t)}, run_id=str(run["id"]))
        enqueue_policy_check(c, sid, seq)
    return resp


@router.delete("/sessions/{sid}/delegations/{did}", status_code=204)
def revoke_delegation(sid: str, did: str, p: Principal = Depends(candidate)):
    with tx(dsn()) as c:
        lock_session(c, sid, p, require_active=True)
        d = one(c, "SELECT * FROM delegations WHERE id=%s AND session_id=%s FOR UPDATE", (did, sid))
        if not d:
            raise ApiError(404, "NOT_FOUND", "위임을 찾을 수 없습니다")
        c.execute("UPDATE delegations SET revoked_at=now(), version=version+1 WHERE id=%s", (did,))
        c.execute("UPDATE approvals SET status='EXPIRED' WHERE delegation_id=%s AND status='PENDING'", (did,))
        runs = all_(c, "UPDATE runs SET status='CANCELLED', updated_at=now() WHERE task_id=%s AND status IN ('QUEUED','RUNNING','WAITING_APPROVAL') RETURNING id",
                    (d["task_id"],))
        t = one(c, "UPDATE tasks SET status='CANCELLED', version=version+1 WHERE id=%s RETURNING *", (d["task_id"],))
        for r in runs:
            c.execute("UPDATE jobs SET status='DONE' WHERE run_id=%s AND status='QUEUED'", (r["id"],))
            emit(c, sid, "DONE", {"status": "CANCELLED"}, run_id=str(r["id"]))
        record_action(c, sid, "CANDIDATE", "DELEGATION_REVOKED", did, {})
        emit(c, sid, "TASK_UPDATED", {"task": task_dto(t)})
    return None


class ReviewIn(Strict):
    decision: Literal["ACCEPT", "REVISE", "REJECT"]
    comment: str = Field(default="", max_length=2000)
    source_refs: list[EvidenceRef] = Field(default_factory=list, max_length=20)


@router.post("/sessions/{sid}/tasks/{tid}/review")
def review_task(sid: str, tid: str, body: ReviewIn, p: Principal = Depends(candidate)):
    with tx(dsn()) as c:
        lock_session(c, sid, p, require_active=True)
        t = one(c, "SELECT * FROM tasks WHERE id=%s AND session_id=%s FOR UPDATE", (tid, sid))
        if not t:
            raise ApiError(404, "NOT_FOUND", "태스크를 찾을 수 없습니다")
        if t["owner"] != "COLLEAGUE" or t["status"] != "REVIEW":
            raise ApiError(409, "VERSION_CONFLICT", "검토 대기 중인 동료 태스크만 검토할 수 있습니다")
        new_status = {"ACCEPT": "DONE", "REVISE": "IN_PROGRESS", "REJECT": "CANCELLED"}[body.decision]
        run_id = None
        if body.decision == "REVISE":
            d = one(c, "SELECT * FROM delegations WHERE id=%s", (t["delegation_id"],))
            if not d or d["revoked_at"] or d["expires_at"] < now():
                raise ApiError(409, "APPROVAL_EXPIRED", "위임이 만료되어 수정 요청을 할 수 없습니다. 새로 위임해 주세요")
            if active_run(c, sid):
                raise ApiError(409, "RUN_BUSY", "진행 중인 동료 작업이 있습니다")
        t = one(c, "UPDATE tasks SET status=%s, version=version+1 WHERE id=%s RETURNING *", (new_status, tid))
        refs = [r.model_dump() for r in body.source_refs]
        seq = record_action(c, sid, "CANDIDATE", "TASK_REVIEWED", tid,
                            {"decision": body.decision, "comment": body.comment, "source_refs": refs, "owner": "COLLEAGUE"})
        if body.decision == "REVISE":
            run = create_run(c, sid, "DELEGATED", task_id=tid, source_message_id=None,
                             input_={"revise_comment": body.comment, "delegation_id": str(t["delegation_id"])})
            run_id = str(run["id"])
        emit(c, sid, "TASK_UPDATED", {"task": task_dto(t)}, run_id=run_id)
        enqueue_policy_check(c, sid, seq)
    return {"task": task_dto(t), "run_id": run_id}


class DecisionIn(Strict):
    decision: Literal["APPROVE", "REJECT"]


@router.post("/sessions/{sid}/approvals/{aid}/decision", status_code=202)
def decide(sid: str, aid: str, body: DecisionIn, p: Principal = Depends(candidate)):
    with tx(dsn()) as c:
        lock_session(c, sid, p, require_active=True)
        a = one(c, "SELECT * FROM approvals WHERE id=%s AND session_id=%s FOR UPDATE", (aid, sid))
        if not a:
            raise ApiError(404, "NOT_FOUND", "승인 요청을 찾을 수 없습니다")
        want = "APPROVED" if body.decision == "APPROVE" else "REJECTED"
        run = one(c, "SELECT * FROM runs WHERE id=%s", (a["run_id"],))
        if a["status"] != "PENDING":
            if a["status"] == want or (want == "APPROVED" and a["status"] == "APPLIED"):
                return {"run_id": str(run["id"]), "status": run["status"]}  # 같은 결정 재전송
            if a["status"] == "EXPIRED":
                raise ApiError(410, "APPROVAL_EXPIRED", "만료되었거나 무효화된 승인 요청입니다")
            raise ApiError(409, "APPROVAL_STALE", "이미 다른 결정이 저장되었습니다")
        if a["expires_at"] < now():
            c.execute("UPDATE approvals SET status='EXPIRED' WHERE id=%s", (aid,))
            raise ApiError(410, "APPROVAL_EXPIRED", "승인 요청이 만료되었습니다")
        d = one(c, "SELECT * FROM delegations WHERE id=%s", (a["delegation_id"],)) if a["delegation_id"] else None
        if want == "APPROVED" and (not d or d["revoked_at"] or d["expires_at"] < now()):
            c.execute("UPDATE approvals SET status='EXPIRED' WHERE id=%s", (aid,))
            raise ApiError(410, "APPROVAL_EXPIRED", "위임이 취소되었거나 만료되었습니다")
        if want == "APPROVED":
            art = one(c, "SELECT version FROM artifacts WHERE session_id=%s", (sid,))
            if art["version"] != a["base_versions"].get("artifact"):
                c.execute("UPDATE approvals SET status='EXPIRED' WHERE id=%s", (aid,))
                want = "REJECTED_STALE"
        c.execute("UPDATE approvals SET status=%s, decided_at=now(), decision_actor_id=%s WHERE id=%s",
                  ("APPROVED" if want == "APPROVED" else ("REJECTED" if want == "REJECTED" else "EXPIRED"), p.sub, aid))
        resume = "APPROVE" if want == "APPROVED" else "REJECT"
        c.execute("UPDATE runs SET status='QUEUED', updated_at=now() WHERE id=%s", (run["id"],))
        c.execute("UPDATE jobs SET status='QUEUED', available_at=now(), lease_until=NULL, input=input || %s WHERE run_id=%s",
                  (J({"resume": resume, "approval_id": aid}), run["id"]))
        seq = record_action(c, sid, "CANDIDATE", "APPROVAL_DECIDED", aid, {"decision": body.decision, "stale": want == "REJECTED_STALE"})
        emit(c, sid, "APPROVAL_DECIDED", {"approval_id": aid, "decision": body.decision, "stale": want == "REJECTED_STALE"},
             run_id=str(run["id"]))
        enqueue_policy_check(c, sid, seq)
    if want == "REJECTED_STALE":
        raise ApiError(409, "APPROVAL_STALE", "승인 대기 중 기획안이 변경되어 이 제안은 무효가 되었습니다. 변경 없이 종료합니다")
    return {"run_id": str(run["id"]), "status": "QUEUED"}


class SubmitIn(Strict):
    base_version: int
    summary: str = Field(default="", max_length=2000)


@router.post("/sessions/{sid}/submit", status_code=202)
def submit(sid: str, body: SubmitIn, p: Principal = Depends(candidate)):
    with tx(dsn()) as c:
        s = lock_session(c, sid, p)
        if s["status"] == "SUBMITTED":
            r = one(c, "SELECT id FROM reports WHERE session_id=%s", (sid,))
            return {"session_status": "SUBMITTED", "report_id": str(r["id"])}
        if s["status"] != "ACTIVE":
            raise ApiError(403, "FORBIDDEN", "시작하지 않은 세션입니다")
        art = one(c, "SELECT * FROM artifacts WHERE session_id=%s FOR UPDATE", (sid,))
        if art["version"] != body.base_version:
            raise ApiError(409, "VERSION_CONFLICT", "제출 전에 저장되지 않은 변경이 있습니다. 최신 기획안을 확인해 주세요")
        final = one(c, "SELECT id FROM artifact_revisions WHERE artifact_id=%s AND version=%s", (art["id"], art["version"]))
        c.execute("UPDATE sessions SET status='SUBMITTED', phase='CLOSED', submitted_at=now(), version=version+1 WHERE id=%s", (sid,))
        runs = all_(c, "UPDATE runs SET status='CANCELLED', updated_at=now() WHERE session_id=%s AND status IN ('QUEUED','RUNNING','WAITING_APPROVAL') RETURNING id", (sid,))
        for r in runs:
            c.execute("UPDATE jobs SET status='DONE' WHERE run_id=%s AND status IN ('QUEUED','LEASED')", (r["id"],))
        c.execute("UPDATE approvals SET status='EXPIRED' WHERE session_id=%s AND status='PENDING'", (sid,))
        c.execute("UPDATE delegations SET revoked_at=now() WHERE session_id=%s AND revoked_at IS NULL", (sid,))
        seq = record_action(c, sid, "CANDIDATE", "SUBMITTED", str(art["id"]),
                            {"artifact_version": art["version"], "empty_sections": [k for k, v in art["sections"].items() if not v.strip()],
                             "summary": body.summary})
        snapshot = {"artifact_version": art["version"], "artifact_revision_id": str(final["id"]) if final else None,
                    "sections": art["sections"], "last_action_seq": seq,
                    "message_ids": [str(m["id"]) for m in all_(c, "SELECT id FROM messages WHERE session_id=%s ORDER BY created_at", (sid,))],
                    "tool_call_ids": [str(t["id"]) for t in all_(c, "SELECT id FROM tool_calls WHERE session_id=%s", (sid,))]}
        rep = one(c, "INSERT INTO reports(session_id,status,source_snapshot) VALUES (%s,'PENDING',%s) RETURNING id", (sid, J(snapshot)))
        enqueue_job(c, sid, "REPORT", f"report:{rep['id']}", input_={"report_id": str(rep["id"])})
        emit(c, sid, "SESSION_DONE", {"report_id": str(rep["id"])})
    return {"session_status": "SUBMITTED", "report_id": str(rep["id"])}


EVENT_DESC = {
    "E-CONSTRAINT": "기획안 대안에 운영 정책과 관련된 표현이 저장되었을 때 확인 질문을 드리는 상황",
    "E-VERIFY": "동료 조사 결과를 대조 자료 없이 수락했을 때 확인을 요청하는 상황",
    "E-SEGMENT": "세그먼트 조사 전에 문제 정의를 처음 저장했을 때 조사 범위를 묻는 상황",
}


@router.get("/sessions/{sid}/debrief")
def debrief(sid: str, p: Principal = Depends(principal)):
    with tx(dsn()) as c:
        s = read_session(c, sid, p)
        if s["status"] != "SUBMITTED":
            raise ApiError(403, "FORBIDDEN", "제출 후에 확인할 수 있습니다")
        occ = all_(c, "SELECT event_id, created_at FROM event_occurrences WHERE session_id=%s ORDER BY created_at", (sid,))
        helps = all_(c, "SELECT help_id, count(*)::int AS n FROM tool_calls WHERE session_id=%s GROUP BY help_id", (sid,))
    occurred = {o["event_id"] for o in occ}
    return {"occurred_events": [{"event_id": o["event_id"], "description": EVENT_DESC[o["event_id"]],
                                 "occurred_at": o["created_at"].isoformat()} for o in occ],
            "not_triggered": [{"event_id": e, "description": d, "status": "조건 미충족"} for e, d in EVENT_DESC.items() if e not in occurred],
            "help_delivered": helps,
            "recording_notice": ("이번 과제에서는 메시지, 자료 열람, 도구 사용, 위임·승인, 기획안 수정 같은 실제 행동이 기록되었습니다. "
                                 "동료의 확인 질문은 진행 상황에 따라 조건이 맞을 때만 나타나며, 나타나지 않은 상황은 평가에 불리하게 쓰이지 않습니다. "
                                 "리포트는 점수나 합격 여부를 판정하지 않고, 최종 판단은 사람이 합니다.")}


@router.get("/reports/{sid}")
def get_report(sid: str, p: Principal = Depends(admin)):
    with tx(dsn()) as c:
        read_session(c, sid, p)
        r = one(c, "SELECT * FROM reports WHERE session_id=%s", (sid,))
        if not r:
            raise ApiError(404, "NOT_FOUND", "리포트가 없습니다")
    return {"status": r["status"], "body": r["body"], "report_id": str(r["id"]), "error_code": r["error_code"]}


@router.post("/reports/{sid}/retry", status_code=202)
def retry_report(sid: str, p: Principal = Depends(admin)):
    with tx(dsn()) as c:
        read_session(c, sid, p)
        r = one(c, "SELECT * FROM reports WHERE session_id=%s FOR UPDATE", (sid,))
        if not r or r["status"] != "FAILED":
            raise ApiError(409, "VERSION_CONFLICT", "FAILED 리포트만 재시도할 수 있습니다")
        c.execute("UPDATE reports SET status='PENDING', attempts=0, error_code=NULL WHERE id=%s", (r["id"],))
        c.execute("UPDATE jobs SET status='QUEUED', available_at=now(), attempt=0 WHERE dedupe_key=%s", (f"report:{r['id']}",))
    return {"report_id": str(r["id"])}

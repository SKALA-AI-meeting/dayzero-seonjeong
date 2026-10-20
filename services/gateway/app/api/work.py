"""Delegation, review, approval decision, submit, debrief, admin report API."""
from __future__ import annotations

import hashlib
import json
from datetime import timedelta
from typing import Literal

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, ConfigDict, Field

from shared.config import SECTION_IDS, settings
from shared.db import J, all_, one, tx

from ..auth import Principal, admin, candidate, principal
from ..domain import (active_run, create_run, elapsed_min, section_sha, emit, insert_message, lock_session, now, read_session,
                      record_action, task_dto)
from ..timeline import apply_split, fire_due, submit_session
from ..errors import ApiError
from .sessions import EvidenceRef

router = APIRouter()
OWNERS = {"CANDIDATE", "COLLEAGUE", "JOINT"}


def dsn() -> str:
    return settings().psycopg_dsn


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SplitIn(Strict):
    decision: Literal["ACCEPT", "ADJUST"]
    assignments: dict[str, Literal["CANDIDATE", "COLLEAGUE", "JOINT"]]
    comment: str = Field(default="", max_length=1000)


@router.post("/sessions/{sid}/split")
def split(sid: str, body: SplitIn, p: Principal = Depends(candidate)):
    """업무 분담 수락/조정(DAYZERO_EXAM_SCENARIO §6 00:10). 조정은 최대 3회, 확정 시 태스크 보드 반영."""
    with tx(dsn()) as c:
        s = lock_session(c, sid, p, require_active=True)
        st = dict(s["policy_state"] or {})
        sp = st.get("split")
        if not sp:
            raise ApiError(409, "VERSION_CONFLICT", "아직 업무 분담 제안이 없습니다")
        if sp["confirmed"]:
            raise ApiError(409, "VERSION_CONFLICT", "업무 분담이 이미 확정되었습니다")
        if set(body.assignments) != set(SECTION_IDS):
            raise ApiError(422, "VALIDATION_ERROR", "5개 섹션의 담당을 모두 지정해 주세요")
        sc = one(c, "SELECT public_brief FROM scenarios WHERE id=%s", (s["scenario_id"],))["public_brief"]
        if body.decision == "ADJUST":
            if sp["adjustments_used"] >= sc["max_split_adjustments"]:
                raise ApiError(409, "LIMIT_REACHED", "분담 조정은 최대 3회까지 가능합니다. 현재 안으로 확정해 주세요")
            sp = {**sp, "assignments": body.assignments, "adjustments_used": sp["adjustments_used"] + 1}
            st["split"] = sp
            c.execute("UPDATE sessions SET policy_state=%s WHERE id=%s", (J(st), sid))
            record_action(c, sid, "CANDIDATE", "SPLIT_ADJUSTED", sp["message_id"],
                          {"assignments": body.assignments, "comment": body.comment, "count": sp["adjustments_used"],
                           "elapsed_min": round(elapsed_min(s), 2)})
            names = {"CANDIDATE": "지원자님", "COLLEAGUE": "저", "JOINT": "같이"}
            titles = {t["key"]: t["title"] for t in sc["task_templates"]}
            lines = "\n".join(f"- {titles[k]}: {names[v]}" for k, v in body.assignments.items())
            left = sc["max_split_adjustments"] - sp["adjustments_used"]
            text = (f"네, 말씀해 주신 대로 조정해 볼게요.\n{lines}\n"
                    + ("이대로 괜찮으시면 확정해 주세요." if left == 0 else f"더 바꾸고 싶은 부분이 있으면 말씀해 주세요(조정 {left}회 남음)."))
            m = insert_message(c, sid, "TEAM", "COLLEAGUE", text,
                               meta={"kind": "SPLIT_RESPONSE", "split_proposal": {"assignments": body.assignments,
                                                                                  "adjustments_used": sp["adjustments_used"],
                                                                                  "max_adjustments": sc["max_split_adjustments"]}})
            emit(c, sid, "COLLEAGUE_MESSAGE", {"message_id": str(m["id"]), "content": text, "citations": []})
            return {"split": {k: sp[k] for k in ("assignments", "adjustments_used", "confirmed")}}
        if body.assignments != sp["assignments"]:
            raise ApiError(409, "VERSION_CONFLICT", "확정은 마지막으로 합의한 분담안으로만 할 수 있습니다. 바꾸려면 조정을 요청해 주세요")
        st["split"] = {**sp, "confirmed": True}
        s["policy_state"] = st
        record_action(c, sid, "CANDIDATE", "SPLIT_CONFIRMED", sp["message_id"],
                      {"assignments": body.assignments, "adjustments_used": sp["adjustments_used"],
                       "elapsed_min": round(elapsed_min(s), 2)})
        apply_split(c, s, body.assignments, actor_id=p.sub)
        text = "좋아요, 이 분담으로 진행할게요. 제가 맡은 부분은 자료를 확인해서 초안을 만든 뒤 문서에 넣기 전에 확인 요청드릴게요."
        m = insert_message(c, sid, "TEAM", "COLLEAGUE", text, meta={"kind": "SPLIT_RESPONSE"})
        emit(c, sid, "COLLEAGUE_MESSAGE", {"message_id": str(m["id"]), "content": text, "citations": []})
    return {"split": {"assignments": body.assignments, "adjustments_used": sp["adjustments_used"], "confirmed": True}}


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
        ok_state = t["status"] == "REVIEW" or (body.decision == "REVISE" and t["status"] in ("IN_PROGRESS", "DONE") and t["delegation_id"])
        if not ok_state:
            raise ApiError(409, "VERSION_CONFLICT", "검토 대기 중인 동료 태스크만 검토할 수 있습니다")
        new_status = {"ACCEPT": "DONE", "REVISE": "IN_PROGRESS", "REJECT": "CANCELLED"}[body.decision]
        if t["owner"] != "COLLEAGUE" and body.decision == "REVISE":
            new_status = t["status"]
        run_id = None
        if body.decision == "REVISE":
            d = one(c, "SELECT * FROM delegations WHERE id=%s", (t["delegation_id"],))
            if not d or d["revoked_at"] or d["expires_at"] < now():
                raise ApiError(409, "APPROVAL_EXPIRED", "위임이 만료되어 수정 요청을 할 수 없습니다. 채팅으로 동료에게 다시 요청해 주세요")
            if one(c, """SELECT 1 FROM runs WHERE session_id=%s AND task_id=%s AND status IN ('QUEUED','RUNNING','WAITING_APPROVAL')""",
                   (sid, tid)):
                raise ApiError(409, "RUN_BUSY", "이 태스크는 이미 동료가 작업 중입니다")
        t = one(c, "UPDATE tasks SET status=%s, version=version+1 WHERE id=%s RETURNING *", (new_status, tid))
        refs = [r.model_dump() for r in body.source_refs]
        record_action(c, sid, "CANDIDATE", "TASK_REVIEWED", tid,
                            {"decision": body.decision, "comment": body.comment, "source_refs": refs, "owner": "COLLEAGUE"})
        if body.decision == "REVISE":
            run = create_run(c, sid, "DELEGATED", task_id=tid, source_message_id=None, prompt_version="colleague-v2",
                             input_={"revise_comment": body.comment or "검토 후 수정 요청", "delegation_id": str(t["delegation_id"]),
                                     "section": t["template_key"], "mode": "rewrite"})
            run_id = str(run["id"])
        emit(c, sid, "TASK_UPDATED", {"task": task_dto(t)}, run_id=run_id)
    return {"task": task_dto(t), "run_id": run_id}


class DecisionIn(Strict):
    decision: Literal["APPROVE", "REJECT", "REVISE"]
    comment: str = Field(default="", max_length=2000)


@router.post("/sessions/{sid}/approvals/{aid}/decision", status_code=202)
def decide(sid: str, aid: str, body: DecisionIn, p: Principal = Depends(candidate)):
    with tx(dsn()) as c:
        lock_session(c, sid, p, require_active=True)
        a = one(c, "SELECT * FROM approvals WHERE id=%s AND session_id=%s FOR UPDATE", (aid, sid))
        if not a:
            raise ApiError(404, "NOT_FOUND", "승인 요청을 찾을 수 없습니다")
        if body.decision == "REVISE" and not body.comment.strip():
            raise ApiError(422, "VALIDATION_ERROR", "재수정 요청에는 검토 사항을 적어 주세요")
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
        if want == "APPROVED" and a["tool_name"] == "patch_artifact_section":
            art = one(c, "SELECT sections FROM artifacts WHERE session_id=%s", (sid,))
            if section_sha(art["sections"], a["args"]["section"]) != a["base_versions"].get("section_sha"):
                c.execute("UPDATE approvals SET status='EXPIRED' WHERE id=%s", (aid,))
                want = "REJECTED_STALE"
        c.execute("UPDATE approvals SET status=%s, decided_at=now(), decision_actor_id=%s WHERE id=%s",
                  ("APPROVED" if want == "APPROVED" else ("REJECTED" if want == "REJECTED" else "EXPIRED"), p.sub, aid))
        resume = "APPROVE" if want == "APPROVED" else ("REVISE" if body.decision == "REVISE" else "REJECT")
        c.execute("UPDATE runs SET status='QUEUED', updated_at=now() WHERE id=%s", (run["id"],))
        c.execute("UPDATE jobs SET status='QUEUED', available_at=now(), lease_until=NULL, input=input || %s WHERE run_id=%s",
                  (J({"resume": resume, "approval_id": aid}), run["id"]))
        record_action(c, sid, "CANDIDATE", "APPROVAL_DECIDED", aid, {"decision": body.decision, "stale": want == "REJECTED_STALE",
                                                                    "comment": body.comment})
        if body.decision == "REVISE" and want != "REJECTED_STALE" and a["args"].get("task_id"):
            # 현재 초안은 반영하지 않고, 검토 사항을 반영한 재작성 run을 이어서 생성(같은 세션 job 순서대로 실행)
            create_run(c, sid, "DELEGATED", task_id=str(a["args"]["task_id"]), source_message_id=None, prompt_version="colleague-v2",
                       input_={"revise_comment": body.comment, "section": a["args"].get("section"), "mode": "rewrite",
                               "delegation_id": str(a["delegation_id"]) if a["delegation_id"] else None, "revise_of_approval": aid})
        emit(c, sid, "APPROVAL_DECIDED", {"approval_id": aid, "decision": body.decision, "stale": want == "REJECTED_STALE"},
             run_id=str(run["id"]))
    if want == "REJECTED_STALE":
        raise ApiError(409, "APPROVAL_STALE", "확인 대기 중에 이 섹션 내용이 바뀌어 초안을 넣지 않았습니다. 필요하면 태스크에서 수정 요청해 주세요")
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
        art = one(c, "SELECT version FROM artifacts WHERE session_id=%s", (sid,))
        if art["version"] != body.base_version:
            raise ApiError(409, "VERSION_CONFLICT", "제출 전에 저장되지 않은 변경이 있습니다. 최신 기획안을 확인해 주세요")
        report_id = submit_session(c, s, actor="CANDIDATE", summary=body.summary)
    return {"session_status": "SUBMITTED", "report_id": report_id}


EVENT_DESC = {
    "T-SPLIT": ("00:10", "이도현 님이 업무 분담안을 제안했습니다. 수락하거나 다시 나눌 수 있었습니다."),
    "T-HELP": ("00:30", "이도현 님이 유사 서비스 사례의 비교 기준에 대해 도움을 요청했습니다. 응답 방식은 자유였습니다."),
    "T-DELAY": ("00:50", "사용자 인터뷰 요약 자료의 공유가 15분 지연되었습니다. 자료는 실제로 01:05까지 열람할 수 없었습니다."),
    "T-INTERVIEW": ("01:05", "사용자 인터뷰 요약 자료가 공유되었습니다."),
    "T-PIVOT": ("01:10", "팀장님이 기획 대상을 '3개월 이상 모임에 참여하지 않은 사용자'로 변경했습니다. 마감 시간은 그대로였습니다."),
    "T-ERROR": ("01:30", "이도현 님이 운영 정책(올해 유료 기능 출시 불가)과 충돌하는 유료 멤버십 기능을 제안했습니다. "
                         "이는 미리 설계된 상황이었습니다."),
    "T-DEADLINE": ("01:50", "팀장님이 기획안 제출과 진행 상황 보고를 요청했습니다."),
}


@router.get("/sessions/{sid}/debrief")
def debrief(sid: str, p: Principal = Depends(principal)):
    """제출 후 지원자에게는 종료 안내만 제공한다(시험 내용·연출 상황 비공개)."""
    with tx(dsn()) as c:
        s = read_session(c, sid, p, allow_closed=True)
        if s["status"] != "SUBMITTED":
            raise ApiError(403, "FORBIDDEN", "제출 후에 확인할 수 있습니다")
    return {"status": "SUBMITTED", "submitted_at": s["submitted_at"].isoformat() if s["submitted_at"] else None,
            "message": "기획안이 제출되었습니다. 오늘 시험 수고하셨습니다."}


class AdvanceIn(Strict):
    to_event: str


@router.post("/sessions/{sid}/demo/advance")
def demo_advance(sid: str, body: AdvanceIn, p: Principal = Depends(admin)):
    """시연 전용 시간 이동(관리자, APP_ENV=development). 지원자 화면에는 노출하지 않는다."""
    if settings().app_env != "development":
        raise ApiError(404, "NOT_FOUND", "사용할 수 없는 기능입니다")
    with tx(dsn()) as c:
        s = lock_session(c, sid, p, require_active=True)
        ev = one(c, "SELECT at_min FROM scenario_events WHERE id=%s", (body.to_event,))
        if not ev:
            raise ApiError(404, "NOT_FOUND", "이벤트를 찾을 수 없습니다")
        st = dict(s["policy_state"] or {})
        real = elapsed_min({**s, "policy_state": {}})
        st["time_offset_min"] = max(float(st.get("time_offset_min", 0)), ev["at_min"] - real + 0.01)
        c.execute("UPDATE sessions SET policy_state=%s WHERE id=%s", (J(st), sid))
        s["policy_state"] = st
        record_action(c, sid, "SYSTEM", "DEMO_TIME_ADVANCED", body.to_event, {"offset_min": st["time_offset_min"]})
        fired = fire_due(c, s)
    return {"fired": fired, "elapsed_min": round(elapsed_min(s), 2)}


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

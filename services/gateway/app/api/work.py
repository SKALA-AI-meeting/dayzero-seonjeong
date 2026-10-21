"""E0 split proposal, approval decision, end of work, debrief + reflection, demo advance, admin report API."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from shared.config import settings
from shared.db import J, one, tx

from .. import engine
from ..auth import Principal, admin, candidate, principal
from ..domain import (active_run, create_run, emit, lock_session, now, read_session, record_action, scenario_def,
                      set_state, elapsed_seconds)
from ..errors import ApiError

router = APIRouter()


def dsn() -> str:
    return settings().psycopg_dsn


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SplitProposal(Strict):
    T1: Literal["CANDIDATE", "COLLEAGUE"]
    T3: Literal["CANDIDATE", "COLLEAGUE"]
    faq_candidate: int = Field(ge=0, le=5)


class SplitIn(Strict):
    proposal: SplitProposal
    comment: str = Field(default="", max_length=1000)


@router.post("/sessions/{sid}/split", status_code=202)
def split(sid: str, body: SplitIn, p: Principal = Depends(candidate)):
    """E0 분업 제안(SplitCard). 협상 최대 3라운드, 넘기면 기본 분업으로 확정. 분기·반문은 agent negotiate 노드가 정한다."""
    with tx(dsn()) as c:
        s = lock_session(c, sid, p, require_active=True)
        st = engine.state(s)
        sp = st.get("split")
        if not sp:
            raise ApiError(409, "VERSION_CONFLICT", "아직 분업 논의가 시작되지 않았습니다")
        if sp["confirmed"]:
            raise ApiError(409, "VERSION_CONFLICT", "분업이 이미 확정되었습니다")
        if active_run(c, sid):
            raise ApiError(409, "RUN_BUSY", "답장을 기다리는 중입니다")
        sc = scenario_def(c, s)
        max_rounds = next(e for e in sc["events"] if e["id"] == "E0")["negotiate"]["max_rounds"]
        proposal = body.proposal.model_dump()
        turn = engine.add_turn(c, s)
        sp = {**sp, "rounds": sp["rounds"] + 1}
        st = engine.state(s)
        st["split"] = sp
        if (st.get("awaiting") or {}).get("event_id") == "E0":  # 분업 제안은 E0 응답이다(무응답 카운트 재시작)
            st["awaiting"] = {"event_id": "E0", "since_seconds": elapsed_seconds(s), "reminded": False}
        set_state(c, s, st)
        seq = record_action(c, sid, "CANDIDATE", "SPLIT_PROPOSED", sp.get("message_id"),
                            {"proposal": proposal, "round": sp["rounds"], "comment": body.comment})
        action_id = str(one(c, "SELECT id FROM actions WHERE session_id=%s AND seq=%s", (sid, seq))["id"])
        if sp["rounds"] > max_rounds:
            engine.confirm_split(c, s, engine.default_split(sc), label="DEFAULT_FALLBACK", sc=sc)
            engine.tick(c, s)
            return {"split": engine.public_split(engine.state(s)), "run_id": None}
        run = create_run(c, sid, input_={"type": "split", "proposal": proposal, "round": sp["rounds"], "comment": body.comment,
                                         "event_id": "E0", "turn": turn, "action_id": action_id})
    return {"split": engine.public_split(st), "run_id": str(run["id"])}


class DecisionIn(Strict):
    decision: Literal["APPROVE", "REJECT"]
    comment: str = Field(default="", max_length=2000)


@router.post("/sessions/{sid}/approvals/{aid}/decision", status_code=202)
def decide(sid: str, aid: str, body: DecisionIn, p: Principal = Depends(candidate)):
    """서윤 수정안 승인/거절 → 같은 thread의 interrupt를 재개(resume)한다."""
    with tx(dsn()) as c:
        s = lock_session(c, sid, p, require_active=True)
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
        art = one(c, "SELECT version FROM artifacts WHERE session_id=%s AND key=%s", (sid, a["args"].get("artifact_key")))
        stale = want == "APPROVED" and a["tool_name"] == "suggest_candidate_edit" and (
            not art or art["version"] != a["base_versions"].get("artifact_version"))
        status = "EXPIRED" if stale else want
        c.execute("UPDATE approvals SET status=%s, decided_at=now(), decision_actor_id=%s WHERE id=%s", (status, p.sub, aid))
        resume = "APPROVE" if status == "APPROVED" else "REJECT"
        c.execute("UPDATE runs SET status='QUEUED', updated_at=now() WHERE id=%s", (run["id"],))
        c.execute("UPDATE jobs SET status='QUEUED', available_at=now(), lease_until=NULL, input=input || %s WHERE run_id=%s",
                  (J({"resume": resume, "approval_id": aid, "stale": stale}), run["id"]))
        engine.add_turn(c, s)
        record_action(c, sid, "CANDIDATE", "APPROVAL_DECIDED", aid, {"decision": body.decision, "stale": stale,
                                                                    "comment": body.comment})
        emit(c, sid, "APPROVAL_DECIDED", {"approval_id": aid, "decision": body.decision, "stale": stale}, run_id=str(run["id"]))
    if stale:
        raise ApiError(409, "APPROVAL_STALE", "확인 대기 중에 산출물이 바뀌어 수정안을 넣지 않았습니다. 필요하면 서윤에게 다시 요청해 주세요")
    return {"run_id": str(run["id"]), "status": "QUEUED"}


class SubmitIn(Strict):
    summary: str = Field(default="", max_length=2000)


@router.post("/sessions/{sid}/submit", status_code=202)
def submit(sid: str, body: SubmitIn, p: Principal = Depends(candidate)):
    """업무 종료(지원자). E4 이후 자동 종료되기도 한다."""
    with tx(dsn()) as c:
        s = lock_session(c, sid, p)
        if s["status"] == "SUBMITTED":
            r = one(c, "SELECT id FROM reports WHERE session_id=%s", (sid,))
            return {"session_status": "SUBMITTED", "report_id": str(r["id"])}
        if s["status"] != "ACTIVE":
            raise ApiError(403, "FORBIDDEN", "시작하지 않은 세션입니다")
        report_id = engine.end_session(c, s, actor="CANDIDATE", summary=body.summary)
    return {"session_status": "SUBMITTED", "report_id": report_id}


@router.get("/sessions/{sid}/debrief")
def debrief(sid: str, p: Principal = Depends(principal)):
    """종료 후 디브리핑: 서윤의 실수와 일정 변경은 의도된 연출이었음을 알리고 소감을 받는다."""
    with tx(dsn()) as c:
        s = read_session(c, sid, p, allow_closed=True)
        if s["status"] != "SUBMITTED":
            raise ApiError(403, "FORBIDDEN", "종료 후에 확인할 수 있습니다")
        sc = scenario_def(c, s)
        refl = one(c, "SELECT payload FROM actions WHERE session_id=%s AND kind='REFLECTION' ORDER BY seq DESC LIMIT 1", (sid,))
    return {"status": "SUBMITTED", "submitted_at": s["submitted_at"].isoformat() if s["submitted_at"] else None,
            "message": sc["debrief"], "reflection": (refl or {}).get("payload", {}).get("text")}


class ReflectionIn(Strict):
    text: str = Field(min_length=1, max_length=2000)


@router.post("/sessions/{sid}/debrief/reflection")
def reflection(sid: str, body: ReflectionIn, p: Principal = Depends(candidate)):
    with tx(dsn()) as c:
        s = read_session(c, sid, p, allow_closed=True)
        if s["status"] != "SUBMITTED":
            raise ApiError(403, "FORBIDDEN", "종료 후에 남길 수 있습니다")
        if one(c, "SELECT 1 FROM actions WHERE session_id=%s AND kind='REFLECTION'", (sid,)):
            raise ApiError(409, "ALREADY_SUBMITTED", "소감은 한 번만 남길 수 있습니다")
        record_action(c, sid, "CANDIDATE", "REFLECTION", None, {"text": body.text})
    return {"saved": True}


@router.post("/sessions/{sid}/demo/advance")
def demo_advance(sid: str, p: Principal = Depends(admin)):
    """Development only: advance the exam clock to the next event opening."""
    if settings().app_env != "development":
        raise ApiError(404, "NOT_FOUND", "사용할 수 없는 기능입니다")
    with tx(dsn()) as c:
        s = lock_session(c, sid, p, require_active=True)
        sc = scenario_def(c, s)
        occ = engine.occurred(c, sid)
        windows = [(e, engine.event_window(e, occ)) for e in sc["events"] if e["id"] not in occ]
        nxt = next(((e, w) for e, w in windows if w), None)
        if not nxt:
            raise ApiError(409, "VERSION_CONFLICT", "남은 이벤트가 없습니다")
        ev, window = nxt
        delta = max(0, window[0] - elapsed_seconds(s))
        c.execute("UPDATE sessions SET clock_offset_seconds=clock_offset_seconds+%s WHERE id=%s", (delta, sid))
        s["clock_offset_seconds"] += delta
        record_action(c, sid, "SYSTEM", "DEMO_ADVANCED", ev["id"], {"elapsed_seconds": elapsed_seconds(s)})
        fired = engine.tick(c, s)
    return {"fired": fired, "elapsed_seconds": elapsed_seconds(s)}


@router.get("/reports/{sid}")
def get_report(sid: str, p: Principal = Depends(admin)):
    with tx(dsn()) as c:
        read_session(c, sid, p)
        r = one(c, "SELECT * FROM reports WHERE session_id=%s", (sid,))
        if not r:
            raise ApiError(404, "NOT_FOUND", "리포트가 없습니다")
        refl = one(c, "SELECT payload FROM actions WHERE session_id=%s AND kind='REFLECTION' ORDER BY seq DESC LIMIT 1", (sid,))
    body = dict(r["body"]) if r["body"] else None
    if body is not None:  # 소감은 리포트 생성 뒤에 남을 수 있어 조회 시 병합
        body["reflection"] = (refl or {}).get("payload", {}).get("text")
    return {"status": r["status"], "body": body, "report_id": str(r["id"]), "error_code": r["error_code"]}


class RetryIn(Strict):
    company_id: str | None = None


@router.get("/companies")
def companies(p: Principal = Depends(admin)):
    """리포트 회사 기준 선택지(설정 COMPANY_MCP_URLS의 company_id). URL은 노출하지 않는다."""
    s = settings()
    return {"items": [{"company_id": k} for k in s.company_mcp_urls], "default": s.default_company_id}


@router.post("/reports/{sid}/retry", status_code=202)
def retry_report(sid: str, body: RetryIn | None = None, p: Principal = Depends(admin)):
    """FAILED 리포트 재시도. company_id를 주면 READY 리포트도 그 회사 기준으로 다시 생성한다(관찰 코드·근거는 같음)."""
    from ..report import company_target
    company_id = body.company_id if body else None
    target = company_target(company_id) if company_id else {}
    if company_id and not target:
        raise ApiError(400, "INVALID_ARGUMENT", "설정되지 않은 회사입니다")
    with tx(dsn()) as c:
        read_session(c, sid, p)
        r = one(c, "SELECT * FROM reports WHERE session_id=%s FOR UPDATE", (sid,))
        if not r or not (r["status"] == "FAILED" or (company_id and r["status"] == "READY")):
            raise ApiError(409, "VERSION_CONFLICT", "FAILED 리포트만 재시도할 수 있습니다(회사 기준 변경은 READY도 가능)")
        c.execute("UPDATE reports SET status='PENDING', attempts=0, error_code=NULL WHERE id=%s", (r["id"],))
        c.execute("UPDATE jobs SET status='QUEUED', available_at=now(), attempt=0, input=input || %s WHERE dedupe_key=%s",
                  (J(target), f"report:{r['id']}"))
    return {"report_id": str(r["id"]), **({"company_id": target["company_id"]} if target else {})}

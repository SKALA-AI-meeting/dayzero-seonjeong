"""dayzero-mcp용 평가자 근거 조회 API(읽기 전용). 서비스 인증 + 평가자 토큰(DAYZERO_MCP_TOKEN) 둘 다 필요.

READY 리포트 본문에서만 읽는다. 적합/부적합 판정, 탈락자 목록, 점수·순위는 만들지 않는다.
"""
from __future__ import annotations

import hmac

from fastapi import APIRouter, Depends, Query, Request

from shared.config import settings
from shared.db import all_, one, tx

from ..auth import internal_service
from ..errors import ApiError

NOTICE = "근거 조회용 도구입니다. 합격·탈락 결정은 평가자가 합니다."


def evaluator(request: Request) -> None:
    token = request.headers.get("x-evaluator-token", "")
    expected = settings().dayzero_mcp_token
    if not expected or not token or not hmac.compare_digest(token, expected):
        raise ApiError(401, "UNAUTHORIZED", "평가자 토큰이 없거나 올바르지 않습니다")


router = APIRouter(prefix="/dayzero", dependencies=[Depends(internal_service), Depends(evaluator)])


def dsn() -> str:
    return settings().psycopg_dsn


@router.get("/candidates")
def candidates_by_behavior(code: str = Query(min_length=2, max_length=12), event_id: str | None = Query(None, max_length=8),
                           limit: int = Query(20, ge=1, le=50)):
    """관찰 코드가 나온 지원자 + 각자의 근거 원문·경과 시간. 정렬은 세션 종료 시각(최근 순)이며 순위가 아니다."""
    with tx(dsn()) as c:
        rows = all_(c, """SELECT s.id, s.submitted_at, pa.alias, r.body FROM reports r JOIN sessions s ON s.id=r.session_id
                          JOIN participants pa ON pa.id=s.participant_id
                          WHERE r.status='READY' AND EXISTS (SELECT 1 FROM observations o WHERE o.session_id=s.id AND o.code=%s)
                          ORDER BY s.submitted_at DESC NULLS LAST""", (code,))
    items = []
    for r in rows:
        ev = []
        for comp in r["body"]["competencies"]:
            for o in comp["observations"]:
                if o["code"] != code or (event_id and o["event_id"] != event_id):
                    continue
                e = o["evidence"] or {}
                ev.append({"competency": comp["label"], "event_id": o["event_id"], "subject": o["subject"],
                           "llm_estimated": bool(o.get("estimated")), "evidence_kind": e.get("kind"),
                           "quote": e.get("quote") or "\n".join(e.get("diff") or []) or o.get("note"),
                           "actor": e.get("actor"), "elapsed_seconds": e.get("elapsed_seconds"), "turn": e.get("turn"),
                           "linked_criterion": (o.get("linked_criterion") or {}).get("text")})
        if ev:  # event_id는 리포트 본문 기준으로 거른다(근거 턴으로 채운 이벤트 포함)
            items.append({"session_id": str(r["id"]), "alias": r["alias"],
                          "submitted_at": r["submitted_at"].isoformat() if r["submitted_at"] else None, "evidence": ev})
        if len(items) >= limit:
            break
    return {"code": code, "event_id": event_id, "count": len(items), "items": items, "notice": NOTICE}


@router.get("/reports/{sid}")
def candidate_report(sid: str):
    """한 명의 리포트 원문(역량 카드·근거·연결된 회사 조항·LLM 추정 표시). 대화 원문 전체(raw)는 빼고 근거만 담는다."""
    with tx(dsn()) as c:
        r = one(c, """SELECT r.status, r.body, pa.alias FROM reports r JOIN sessions s ON s.id=r.session_id
                      JOIN participants pa ON pa.id=s.participant_id WHERE r.session_id::text=%s""", (sid,))
    if not r or r["status"] != "READY" or not r["body"]:
        raise ApiError(404, "NOT_FOUND", "READY 리포트가 없습니다")
    b = r["body"]
    keep = ("scenario_title", "generation_mode", "ended_by", "turn_count", "elapsed_seconds", "timeline", "competencies",
            "planted_errors", "e2_change", "commitments", "final_board", "company", "limitations")
    return {"session_id": sid, "alias": r["alias"], **{k: b.get(k) for k in keep}, "notice": NOTICE}

"""Business tool logic owned by the gateway (business-mcp forwards here). docs/SCENARIO_SC_A.md 8장 MCP 연결.

get_planted_error는 Agent 판정·수정 전용이다. 결과는 confidential로 표시하고, agent는 이 결과를 서윤 프롬프트나
지원자에게 보내는 메시지에 넣지 않는다(graph.validate_output의 정답 누설 가드).
"""
from __future__ import annotations

from shared.db import all_, one
from shared.scenario import codebook, public_definition

from .domain import elapsed_seconds

from .engine import observe, state


class ToolError(Exception):
    def __init__(self, code: str, message: str, retryable: bool = False):
        self.code, self.message, self.retryable = code, message, retryable


def session_context(c, s: dict) -> dict:
    sid = str(s["id"])
    st = state(s)
    tasks = all_(c, "SELECT key, title, status, owner, eta, note, version FROM tasks WHERE session_id=%s ORDER BY key", (sid,))
    arts = all_(c, "SELECT key, title, version, length(body) AS chars FROM artifacts WHERE session_id=%s ORDER BY key", (sid,))
    occ = all_(c, "SELECT event_id, turn, elapsed_seconds, skipped FROM event_occurrences WHERE session_id=%s ORDER BY created_at", (sid,))
    return {"turn_count": s["turn_count"], "elapsed_seconds": elapsed_seconds(s), "phase": s["phase"],
            "active_event": st.get("active_event"), "colleague": st.get("colleague"),
            "split_confirmed": bool((st.get("split") or {}).get("confirmed")),
            "tasks": tasks, "artifacts": arts, "events": occ}


def get_scenario(c, s: dict) -> dict:
    sc = one(c, "SELECT definition FROM scenarios WHERE id=%s", (s["scenario_id"],))["definition"]
    return public_definition(sc)


def get_next_event(c, s: dict) -> dict:
    sc = one(c, "SELECT definition FROM scenarios WHERE id=%s", (s["scenario_id"],))["definition"]
    done = {o["event_id"] for o in all_(c, "SELECT event_id FROM event_occurrences WHERE session_id=%s", (s["id"],))}
    nxt = next((e for e in sc["events"] if e["id"] not in done), None)
    st = state(s)
    out = {"turn_count": s["turn_count"], "active_event": st.get("active_event"), "awaiting": st.get("awaiting"), "next": None}
    if nxt:
        at = nxt["trigger"].get("at")
        out["next"] = {"id": nxt["id"], "type": nxt["type"], "trigger": nxt["trigger"], "elapsed_seconds": elapsed_seconds(s),
                       "turns_until": None if at is None else max(0, at - s["turn_count"]),
                       "optional": bool(nxt.get("optional"))}
    return out


def get_planted_error(c, s: dict, args: dict) -> dict:
    sc = one(c, "SELECT definition, fixes FROM scenarios WHERE id=%s", (s["scenario_id"],))
    ids = args.get("error_ids") or []
    known = {p["id"]: p for p in sc["definition"]["planted_errors"]}
    known_fix = sc["fixes"]
    if any(i not in known and i != "E2-CHANGE" for i in ids):
        raise ToolError("NOT_FOUND", f"알 수 없는 오류 ID: {[i for i in ids if i not in known and i != 'E2-CHANGE']}")
    items = []
    for i in ids or list(known):
        base = dict(known.get(i) or {"id": i, "doc": "doc://sc-a/brief", "where": "E2 changed_fact",
                                     "correct": (next(e for e in sc["definition"]["events"] if e["id"] == "E2").get("changed_fact") or {}).get("value")})
        base["fix"] = known_fix.get(i, [])
        items.append(base)
    return {"confidential": True, "usage": "Agent 판정·수정 전용. 서윤 발화·지원자 응답에 포함 금지", "items": items}


def record_observation(c, s: dict, run: dict, args: dict) -> dict:
    code = args.get("code")
    if code not in codebook():
        raise ToolError("INVALID_ARGUMENT", f"코드북에 없는 코드입니다: {code}")
    ev = args.get("evidence_ref") or {}
    sid = str(s["id"])
    if ev.get("kind") == "message":
        if not one(c, "SELECT 1 FROM messages WHERE id::text=%s AND session_id=%s", (str(ev.get("id")), sid)):
            raise ToolError("NOT_FOUND", "근거 메시지가 이 세션에 없습니다")
    elif ev.get("kind") == "revision":
        if not one(c, "SELECT 1 FROM artifact_revisions WHERE id::text=%s AND session_id=%s", (str(ev.get("id")), sid)):
            raise ToolError("NOT_FOUND", "근거 수정 이력이 이 세션에 없습니다")
    elif ev.get("kind") == "action":
        if not one(c, "SELECT 1 FROM actions WHERE id::text=%s AND session_id=%s", (str(ev.get("id")), sid)):
            raise ToolError("NOT_FOUND", "근거 행동 기록이 이 세션에 없습니다")
    else:
        raise ToolError("INVALID_ARGUMENT", "evidence_ref.kind는 message|revision|action입니다")
    created = observe(c, sid, code, args.get("event_id"), {"kind": ev["kind"], "id": str(ev["id"])}, str(args.get("note") or ""),
                      subject=args.get("subject"), source="AGENT", run_id=str(run["id"]))
    return {"recorded": created, "code": code, "competency": codebook()[code]["competency"]}

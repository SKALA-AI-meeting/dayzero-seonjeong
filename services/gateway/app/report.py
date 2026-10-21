"""관찰 리포트 본문(규칙 기반, docs/SCENARIO_SC_A.md 6장). 판정·점수·순위 없음.

5역량별로 관찰 코드 + 근거 원문 + 발생 이벤트를 모은다.
- 코드가 없고 관련 이벤트가 발생했으면 '관찰 기회 부족', 관련 이벤트가 하나도 발생하지 않았으면 '관찰 기회 없음'.
- CO·N1만 있고 CO+5가 없으면 '동료에게 수정을 요청한 장면 없음'을 사실로만 적는다.
"""
from __future__ import annotations

import difflib
from zoneinfo import ZoneInfo

from shared.config import settings
from shared.db import all_, one
from shared.scenario import COMPETENCIES, COMPETENCY_EVENTS, COMPETENCY_LABEL, codebook

KST = ZoneInfo("Asia/Seoul")
STATUS_LABEL = {"OBSERVED": "관찰됨", "INSUFFICIENT": "관찰 기회 부족", "NO_OPPORTUNITY": "관찰 기회 없음"}
ACTOR_LABEL = {"CANDIDATE": "지원자", "COLLEAGUE": "한서윤(AI 동료)", "MANAGER": "박준호 팀장", "SYSTEM": "시스템"}


def company_target(company_id: str | None = None) -> dict:
    """리포트 job 입력용 회사 기준: company_id → company-mcp URL(설정 COMPANY_MCP_URLS). 없으면 빈 dict(조항 연결 생략)."""
    s = settings()
    cid = company_id or s.default_company_id
    url = s.company_mcp_urls.get(cid)
    return {"company_id": cid, "company_mcp_url": url} if url else {}


def _diff(before: str, after: str) -> list[str]:
    return [ln for ln in difflib.unified_diff(before.splitlines(), after.splitlines(), lineterm="", n=0)
            if ln and not ln.startswith(("---", "+++", "@@"))][:20]


def build_report_body(c, s: dict, snap: dict) -> dict:
    sid = str(s["id"])
    sc = one(c, "SELECT definition FROM scenarios WHERE id=%s", (s["scenario_id"],))["definition"]
    cb = codebook()
    occ = all_(c, "SELECT * FROM event_occurrences WHERE session_id=%s ORDER BY created_at", (sid,))
    fired = {o["event_id"]: o for o in occ if not o["skipped"]}
    msgs = all_(c, "SELECT id, actor, content, meta, turn, created_at FROM messages WHERE session_id=%s ORDER BY created_at", (sid,))
    by_msg = {str(m["id"]): m for m in msgs}
    revs = all_(c, """SELECT r.id, r.actor, r.version, r.body_before, r.body_after, r.turn, r.meta, r.created_at, a.key, a.title
                      FROM artifact_revisions r JOIN artifacts a ON a.id=r.artifact_id WHERE r.session_id=%s ORDER BY r.created_at""", (sid,))
    by_rev = {str(r["id"]): r for r in revs}
    acts = {str(a["id"]): a for a in all_(c, "SELECT id, kind, entity_id, payload, turn FROM actions WHERE session_id=%s", (sid,))}
    obs = all_(c, "SELECT * FROM observations WHERE session_id=%s ORDER BY created_at", (sid,))
    st = s["scenario_state"] or {}

    # 지원자 행동이 턴 N을 만들고 그 턴에 이벤트가 발생하므로, 턴 N의 행동은 '턴 N 이전에 발생한' 마지막 이벤트 시점이다(E0는 턴 0)
    def vt_at(turn: int) -> str:
        return next((o["virtual_time"] for o in reversed(occ) if not o["skipped"] and (o["turn"] < (turn or 0) or o["turn"] == 0)), "09:00")

    def event_at(turn: int | None) -> str | None:  # 그 턴 시점의 활성 이벤트
        return next((o["event_id"] for o in reversed(occ) if not o["skipped"] and (o["turn"] < (turn or 0) or o["turn"] == 0)), None)

    def event_of(o: dict, ev: dict) -> str | None:
        """기록된 이벤트가 없으면(이전 세션의 종료 시 규칙 판정) 근거가 생긴 턴 기준으로 채운다."""
        return o["event_id"] or (event_at(ev["turn"]) if ev.get("turn") is not None and ev.get("kind") in ("message", "revision") else None)

    def evidence(ref: dict) -> dict:
        kind, rid = ref.get("kind"), str(ref.get("id"))
        if kind == "message" and rid in by_msg:
            m = by_msg[rid]
            return {"kind": "message", "id": rid, "actor": ACTOR_LABEL[m["actor"]], "quote": m["content"][:400], "turn": m["turn"],
                    "virtual_time": vt_at(m["turn"]), "at": m["created_at"].astimezone(KST).strftime("%H:%M")}
        if kind == "revision" and rid in by_rev:
            r = by_rev[rid]
            return {"kind": "revision", "id": rid, "actor": ACTOR_LABEL[r["actor"]], "artifact": f"{r['key']} {r['title']}",
                    "diff": _diff(r["body_before"], r["body_after"]), "turn": r["turn"], "virtual_time": vt_at(r["turn"])}
        if kind == "action" and rid in acts:
            a = acts[rid]
            return {"kind": "action", "id": rid, "action": a["kind"], "entity": a["entity_id"], "payload": a["payload"], "turn": a["turn"]}
        return {"kind": kind, "id": rid}

    competencies = []
    for comp in COMPETENCIES:
        items = [o for o in obs if o["competency"] == comp]
        related = [e for e in COMPETENCY_EVENTS[comp] if e in fired]
        status = "OBSERVED" if items else ("INSUFFICIENT" if related else "NO_OPPORTUNITY")
        notes = []
        if comp == "COLLABORATION" and (st.get("report_flags") or {}).get("co_n1_without_co5"):
            notes.append("동료에게 수정을 요청한 장면 없음")
        competencies.append({
            "key": comp, "label": COMPETENCY_LABEL[comp], "status": status, "status_label": STATUS_LABEL[status],
            "related_events": [{"event_id": e, "virtual_time": fired[e]["virtual_time"], "turn": fired[e]["turn"]} for e in related],
            "observations": [{"code": o["code"], "definition": cb[o["code"]]["definition"], "polarity":
                              "neutral" if "·N" in o["code"] else ("positive" if "+" in o["code"] else "caution"),
                              "event_id": event_of(o, ev), "subject": o["subject"], "note": (o["note"] or "").replace("[LLM 추정] ", ""),
                              "source": o["source"], "estimated": o["source"] == "AGENT" and (o["note"] or "").startswith("[LLM 추정]"),
                              "evidence": ev} for o in items for ev in [evidence(o["evidence_ref"] or {})]],
            "notes": notes,
        })

    planted = []
    for pe in sc["planted_errors"]:
        removed = next((r for r in revs if pe["wrong"] in r["body_before"] and pe["wrong"] not in r["body_after"]), None)
        planted.append({"id": pe["id"], "where": f"{pe['doc']} {pe['where']}", "difficulty": pe["difficulty"],
                        "fixed": bool(removed), "fixed_by": ACTOR_LABEL[removed["actor"]] if removed else None,
                        "codes": sorted({o["code"] for o in obs if o["subject"] == pe["id"]})})
    commitments = [{"text": cm["text"], "status": cm["status"], "event_id": cm["event_id"], "registered_turn": cm["registered_turn"]}
                   for cm in all_(c, "SELECT * FROM commitments WHERE session_id=%s ORDER BY created_at", (sid,))]
    approvals = [{"artifact": a["before_after"].get("title") or a["before_after"].get("task_key"), "targets": a["before_after"].get("targets", []),
                  "status": a["status"], "diff": _diff(a["before_after"].get("before") or "", a["before_after"].get("after") or "")}
                 for a in all_(c, "SELECT * FROM approvals WHERE session_id=%s ORDER BY created_at", (sid,))]
    refl = one(c, "SELECT payload FROM actions WHERE session_id=%s AND kind='REFLECTION' ORDER BY seq DESC LIMIT 1", (sid,))
    tasks = all_(c, "SELECT key, title, status, owner, eta, note FROM tasks WHERE session_id=%s ORDER BY key", (sid,))
    return {
        "schema_version": "3.0", "generation_mode": "RULES", "scenario_id": sc["scenario_id"], "scenario_title": sc["title"],
        "ended_by": snap.get("ended_by"), "turn_count": snap.get("turn_count"), "virtual_time": snap.get("virtual_time"),
        "timeline": [{"event_id": o["event_id"], "virtual_time": o["virtual_time"], "turn": o["turn"], "skipped": o["skipped"],
                      "reason": (o["facts"] or {}).get("reason")} for o in occ],
        "competencies": competencies,
        "planted_errors": planted,
        "e2_change": {"occurred": "E2" in fired,
                      "reflected": {r["key"]: ("2,000" in r["body"] or "2000" in r["body"])
                                    for r in all_(c, "SELECT key, body FROM artifacts WHERE session_id=%s AND key IN ('T1','T2','T3')", (sid,))}},
        "commitments": commitments,
        "final_board": tasks,
        "raw": {
            "messages": [{"id": str(m["id"]), "actor": ACTOR_LABEL[m["actor"]], "content": m["content"], "turn": m["turn"],
                          "kind": (m["meta"] or {}).get("kind"), "event_id": (m["meta"] or {}).get("event_id"),
                          "label": (m["meta"] or {}).get("label"), "at": m["created_at"].astimezone(KST).strftime("%H:%M")} for m in msgs],
            "revisions": [{"id": str(r["id"]), "artifact": f"{r['key']} {r['title']}", "actor": ACTOR_LABEL[r["actor"]],
                           "version": r["version"], "turn": r["turn"], "diff": _diff(r["body_before"], r["body_after"])} for r in revs],
            "approvals": approvals,
        },
        "reflection": (refl or {}).get("payload", {}).get("text"),
        "limitations": ["단일 가상 과제에서 관찰한 행동이며 성격·채용 성과를 단정하지 않음",
                        "관찰되지 않은 행동은 부정으로 해석하지 않음(관찰 기회 부족/없음으로 구분)",
                        "점수·등급·순위·합격 여부를 생성하지 않음", "최종 판단은 사람이 원문 근거를 확인해 내림"],
    }

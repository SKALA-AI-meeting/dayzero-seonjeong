"""세션 종료 시 일괄 판정(규칙): observe_at_end_if_still, end_check, 심어둔 오류 발견·처리, 약속 이행.

모두 로그(메시지·문서 diff·보드·열람 기록)로만 판정하고 코드북 코드 + 근거 참조만 남긴다. 점수·합불 없음.
못 찾은 오류는 부정 코드가 아니라 '관찰 없음'이다(설계서 5장).
"""
from __future__ import annotations

import re

from shared.db import J, all_, one

from shared.scenario import TARGET_PATTERNS as PE_MENTION

from .engine import TWO_K, missing_change, observe, state

DISCLOSE_RE = re.compile(r"(아직|미완|못\s*했|못했|남았|진행\s*중|안\s*됐|덜\s*됐|늦어|못\s*끝|어려울|빠듯)")
DONE_RE = re.compile(r"(봤어요|봤습니다|했어요|했습니다|완료|확인했|끝냈|고쳤|반영했|수정했|정리했)")


def judge_session(c, s: dict) -> None:
    sid = str(s["id"])
    sc = one(c, "SELECT definition FROM scenarios WHERE id=%s", (s["scenario_id"],))["definition"]
    st = state(s)
    occ = {o["event_id"]: o for o in all_(c, "SELECT * FROM event_occurrences WHERE session_id=%s AND NOT skipped", (sid,))}
    msgs = all_(c, "SELECT id, actor, content, turn, meta FROM messages WHERE session_id=%s ORDER BY created_at", (sid,))
    cand = [m for m in msgs if m["actor"] == "CANDIDATE"]
    revs = all_(c, """SELECT r.id, r.actor, r.body_before, r.body_after, r.turn, a.key FROM artifact_revisions r
                      JOIN artifacts a ON a.id=r.artifact_id WHERE r.session_id=%s ORDER BY r.created_at""", (sid,))
    arts = {a["key"]: a for a in all_(c, "SELECT key, body FROM artifacts WHERE session_id=%s", (sid,))}
    tasks = {t["key"]: t for t in all_(c, "SELECT * FROM tasks WHERE session_id=%s", (sid,))}
    obs = all_(c, "SELECT code, event_id, subject FROM observations WHERE session_id=%s", (sid,))
    fired = sorted(occ.values(), key=lambda o: o["turn"])

    def event_at(turn: int | None) -> str | None:  # 그 턴 시점의 활성 이벤트 = 그 턴 이전에 발생한 마지막 이벤트(E0는 턴 0)
        return next((o["event_id"] for o in reversed(fired) if o["turn"] < (turn or 0) or o["turn"] == 0), None)
    asked = {o["subject"] for o in obs if o["code"] == "CO+5"}
    any_co5 = any(o["code"] == "CO+5" for o in obs)

    # 심어둔 오류: 발견(PL+3, PE-1~3) · 요청 없이 대신 수정(CO·N1) · 언급 후 방치(CO-3)
    for pe in sc["planted_errors"]:
        pid, wrong = pe["id"], pe["wrong"]
        removed = [r for r in revs if wrong in r["body_before"] and wrong not in r["body_after"]]
        mentioned = [m for m in cand if PE_MENTION[pid].search(m["content"])]
        still = any(wrong in a["body"] for a in arts.values())
        if pid != "PE-4" and (removed or mentioned):
            ev = removed[0] if removed else None
            ref = {"kind": "revision", "id": str(ev["id"])} if ev else {"kind": "message", "id": str(mentioned[0]["id"])}
            observe(c, sid, "PL+3", event_at((ev or mentioned[0])["turn"]), ref, f"{pid} {pe['where']} 오류 발견", subject=pid)
        by_cand = [r for r in removed if r["actor"] == "CANDIDATE"]
        if by_cand and pid not in asked:
            observe(c, sid, "CO·N1", event_at(by_cand[0]["turn"]), {"kind": "revision", "id": str(by_cand[0]["id"])},
                    f"{pid}: 서윤 초안을 요청 없이 직접 수정", subject=pid)
        if mentioned and still and pid not in asked:
            observe(c, sid, "CO-3", event_at(mentioned[0]["turn"]), {"kind": "message", "id": str(mentioned[0]["id"])},
                    f"{pid}를 언급했으나 종료 시까지 요청·수정 없음", subject=pid)

    # E2 변경 반영(end_check doc_contains 2,000P)
    if "E2" in occ:
        missing = missing_change(c, sid)
        cand_added = [r for r in revs if r["actor"] == "CANDIDATE" and r["key"] in ("T2", "T3")
                      and TWO_K.search(r["body_after"]) and not TWO_K.search(r["body_before"])
                      and (tasks.get(r["key"]) or {}).get("owner") in ("COLLEAGUE", "SPLIT")]
        if cand_added and "E2-CHANGE" not in asked:
            observe(c, sid, "CO·N1", event_at(cand_added[0]["turn"]), {"kind": "revision", "id": str(cand_added[0]["id"])},
                    "E2 변경(피초대자 2,000P)을 서윤 담당 산출물에 요청 없이 직접 반영", subject="E2-CHANGE")
        if missing and (st.get("e2_reminded") or st.get("e2b_accepted")):
            observe(c, sid, "AD-1", "E2", {"kind": "artifact", "id": ",".join(missing)},
                    f"종료 시 2,000P 미반영 산출물: {', '.join(missing)}")
        if st.get("e2b_accepted") and "E2B" in occ:
            col_missing = missing_change(c, sid, owners=("COLLEAGUE", "SPLIT"))
            if col_missing:
                observe(c, sid, "CO-3", "E2B", {"kind": "artifact", "id": ",".join(col_missing)},
                        f"서윤의 '다 했어요' 뒤 미반영 상태로 종료: {', '.join(col_missing)}")

    # 약속 이행(RS+2 / RS-2)
    for cm in all_(c, "SELECT * FROM commitments WHERE session_id=%s AND status='OPEN'", (sid,)):
        later_msgs = [m for m in cand if m["turn"] > cm["registered_turn"]]
        later_revs = [r for r in revs if r["actor"] == "CANDIDATE" and r["turn"] > cm["registered_turn"]]
        kept = next((m for m in later_msgs if DONE_RE.search(m["content"])), None)
        if kept or later_revs:
            ref = {"kind": "message", "id": str(kept["id"])} if kept else {"kind": "revision", "id": str(later_revs[0]["id"])}
            c.execute("UPDATE commitments SET status='KEPT', resolved_at=now(), resolution=%s WHERE id=%s", (J(ref), cm["id"]))
            observe(c, sid, "RS+2", cm["event_id"], ref, f"약속 이행: “{cm['text'][:80]}”", subject=str(cm["id"]))
        else:
            mentioned = next((m for m in later_msgs if DISCLOSE_RE.search(m["content"])), None)
            c.execute("UPDATE commitments SET status='BROKEN', resolved_at=now(), resolution=%s WHERE id=%s",
                      (J({"mentioned": str(mentioned["id"]) if mentioned else None}), cm["id"]))
            if not mentioned:
                observe(c, sid, "RS-2", cm["event_id"], {"kind": "message", "id": str(cm["message_id"])},
                        f"약속 후 이행·언급 없음: “{cm['text'][:80]}”", subject=str(cm["id"]))

    # PL+4: E3 이후 브리프를 다시 열어 대조
    if "E3" in occ:
        opened = one(c, """SELECT id FROM actions WHERE session_id=%s AND kind IN ('DOCUMENT_OPENED','DOCUMENT_REOPENED')
                           AND entity_id='brief' AND turn >= %s ORDER BY seq LIMIT 1""", (sid, occ["E3"]["turn"]))
        if opened:
            observe(c, sid, "PL+4", None, {"kind": "action", "id": str(opened["id"])}, "E3 이후 브리프를 다시 열어 대조")

    # RS-1: 미완료를 알리지 않은 채 마감
    open_tasks = [k for k, t in tasks.items() if t["owner"] in ("CANDIDATE", "SPLIT") and t["status"] != "DONE"]
    disclosed = any(o["code"] in ("HO+1", "RS+1") for o in obs) or any(DISCLOSE_RE.search(m["content"]) for m in cand)
    if open_tasks and not disclosed:
        observe(c, sid, "RS-1", None, {"kind": "task", "id": ",".join(open_tasks)}, f"미완료 태스크: {', '.join(open_tasks)}")

    # Review response is a neutral fact, including no response before submission.
    for review in all_(c, "SELECT payload, turn, id FROM actions WHERE session_id=%s AND kind='ARTIFACT_READ'", (sid,)):
        key = review["payload"].get("key")
        if not one(c, "SELECT 1 FROM observations WHERE session_id=%s AND code='CO+7' AND run_id::text=%s", (sid, review['payload'].get('run_id'))):
            continue
        later = next((m for m in cand if m["turn"] > review["turn"]), None)
        applied = any(r["actor"] == "CANDIDATE" and r["key"] == key and r["turn"] > review["turn"] for r in revs)
        applied = applied or bool(one(c, "SELECT 1 FROM approvals WHERE session_id=%s AND run_id::text=%s AND status='APPLIED'", (sid,review["payload"].get("run_id"))))
        retained = later and re.search(r"검토|의견|피드백|말씀|유지|그대로", later["content"]) and re.search(r"때문|라서|이유|위해", later["content"])
        note = "서윤 검토 의견을 반영함" if applied else ("이유를 들어 유지함" if retained else "반응 없음")
        ref = {"kind":"message","id":str(later["id"])} if retained else {"kind":"action","id":str(review["id"])}
        observe(c,sid,"CO·N2",event_at(review["turn"]),ref,note,subject=key)

    # CO·N1만 있고 CO+5가 없으면 리포트에 사실 문장만 남긴다(점수 아님)
    st["report_flags"] = {"co_n1_without_co5": (not any_co5) and bool(one(c, "SELECT 1 FROM observations WHERE session_id=%s AND code='CO·N1'", (sid,)))}
    c.execute("UPDATE sessions SET scenario_state=%s WHERE id=%s", (J(st), sid))

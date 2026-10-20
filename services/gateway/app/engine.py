"""턴 기반 이벤트 엔진 (docs/SCENARIO_SC_A.md 4장, scenario.json events[]).

- 턴 = 지원자 메시지 1개 또는 보드·문서 액션 1개(태스크 변경, 산출물 저장, 분업 제안, 승인 결정). 문서 열람은 턴이 아니다.
- 이벤트는 trigger(session_start / turn + condition) 순서대로, 세션당 1회만 발생한다(event_occurrences unique).
  한 턴에 최대 1개만 발생하고 나머지는 다음 턴으로 미룬다. 조건 불충족(E2B)·optional 비활성(E4)은 skipped로 기록한다.
- 고정 대사는 LLM 없이 그대로 보내고 messages.meta.kind=SCENARIO_EVENT로 구분한다.
- 무응답(no_response_policy): remind_after_turns 후 SYSTEM 리마인드 1회 → advance_after_turns 추가 후 다음 단계로 자동 진행.
  E1은 branches의 NO_RESPONSE(after_turns)가, E2는 NOT_REFLECTED가 그 역할을 대신한다.
- 메시지 턴의 tick(이벤트 발생·무응답 처리)은 그 메시지에 대한 동료 응답 run이 끝난 뒤 실행해 대화 순서를 지킨다.
"""
from __future__ import annotations

import re

from shared.config import settings
from shared.db import J, all_, one

from .domain import (create_run, emit, enqueue_job, list_tasks, post_line, record_action, scenario_def, set_state,
                     task_dto, artifact_dto)

ACTOR = {"manager": "MANAGER", "colleague": "COLLEAGUE"}
AWAITS_RESPONSE = {"E0", "E1", "E2B", "E3B", "E4"}
TWO_K = re.compile(r"2[,.]?000\s*P|2천\s*P|2,000포인트|2000포인트", re.I)
ARTIFACT_TITLES = {"T1": "앱 공지용 이벤트 안내문", "T2": "고객 FAQ 5개", "T3": "리워드·일정 표",
                   "T5": "앱 푸시 문구 2개", "T4": "팀장 보고 3줄 요약"}


def doc_body(c, doc_id: str) -> str:
    d = one(c, "SELECT body FROM documents WHERE id=%s", (doc_id,))
    return d["body"] if d else ""


def state(s: dict) -> dict:
    return dict(s.get("scenario_state") or {})


def occurred(c, sid: str) -> dict[str, dict]:
    return {o["event_id"]: o for o in all_(c, "SELECT * FROM event_occurrences WHERE session_id=%s", (sid,))}


# ---- session start ---------------------------------------------------------------------

def start_session(c, s: dict) -> None:
    """Create board/artifacts from scenario.json and fire session_start events (E0). Caller holds row lock."""
    sid = str(s["id"])
    sc = scenario_def(c, s)
    for t in sc["tasks"]:
        if t["status"] == "HIDDEN":
            continue  # T4는 E4에서 공개
        c.execute("INSERT INTO tasks(session_id,key,title,status,owner,note) VALUES (%s,%s,%s,%s,'UNASSIGNED',%s)",
                  (sid, t["id"], t["title"], "IN_PROGRESS" if t["status"] == "IN_PROGRESS" else "TODO", t.get("note")))
    initial = {"T1": "", "T2": doc_body(c, "faq-draft"), "T3": doc_body(c, "reward-table")}
    for key, body in initial.items():
        c.execute("INSERT INTO artifacts(session_id,key,title,body,initial_body) VALUES (%s,%s,%s,%s,%s)",
                  (sid, key, ARTIFACT_TITLES[key], body, body))
    set_state(c, s, {"active_event": None, "awaiting": None, "colleague": {"offline": False, "offline_replies_left": 0},
                     "pushback": {"E0": False, "E2": False}, "pushback_pending": None, "e2_asked_colleague": False,
                     "e2_reminded": False, "e2b_accepted": False, "split": None, "e4": None, "manager_answered": []})
    for ev in sc["events"]:
        if ev["trigger"]["kind"] == "session_start":
            fire(c, s, ev, sc)


# ---- turns -----------------------------------------------------------------------------

def add_turn(c, s: dict, *, responded: bool = False) -> int:
    """Increase turn_count for one candidate action. A team message counts as a response to the awaiting event."""
    row = one(c, "UPDATE sessions SET turn_count=turn_count+1 WHERE id=%s RETURNING turn_count", (s["id"],))
    s["turn_count"] = row["turn_count"]
    if responded:
        st = state(s)
        if st.get("awaiting") and st["awaiting"]["event_id"] != "E0":  # E0 응답은 분업 확정으로만 끝난다
            st["awaiting"] = None
            set_state(c, s, st)
    return s["turn_count"]


def tick(c, s: dict) -> list[str]:
    """No-response handling, E2 reminder, then fire at most one due event. Caller holds the session row lock."""
    if s["status"] != "ACTIVE":
        return []
    if one(c, "SELECT 1 FROM runs WHERE session_id=%s AND kind='TEAM' AND status IN ('QUEUED','RUNNING','WAITING_APPROVAL')", (s["id"],)):
        return []  # 응답·승인 대기 중이면 그 run이 끝날 때(run_state) 다시 tick
    sc = scenario_def(c, s)
    no_response(c, s, sc)
    if s["status"] != "ACTIVE":
        return []
    e2_reminder(c, s, sc)
    return fire_due(c, s, sc)


def fire_due(c, s: dict, sc: dict, *, force_next: bool = False) -> list[str]:
    sid = str(s["id"])
    occ = occurred(c, sid)
    st = state(s)
    fired: list[str] = []
    for ev in sc["events"]:
        if ev["id"] in occ:
            continue
        trig = ev["trigger"]
        if trig["kind"] != "turn":
            continue
        if not force_next and s["turn_count"] < trig["at"]:
            break
        if ev["id"] == "E2B" and st.get("e2_asked_colleague"):
            skip(c, s, ev, "E2에서 이미 서윤에게 반영을 요청함(반문은 그 시점에 1회 수행)")
            continue
        if ev.get("optional") and ev["id"] == "E4" and not settings().event_e4_enabled:
            skip(c, s, ev, "EVENT_E4_ENABLED=false")
            continue
        fire(c, s, ev, sc)
        fired.append(ev["id"])
        break
    return fired


def skip(c, s: dict, ev: dict, reason: str) -> None:
    c.execute("""INSERT INTO event_occurrences(session_id,event_id,turn,virtual_time,skipped,facts)
                 VALUES (%s,%s,%s,%s,true,%s) ON CONFLICT DO NOTHING""",
              (s["id"], ev["id"], s["turn_count"], s["virtual_time"], J({"reason": reason})))
    record_action(c, str(s["id"]), "SYSTEM", "EVENT_SKIPPED", ev["id"], {"reason": reason})
    emit(c, str(s["id"]), "EVENT_SKIPPED", {"event_id": ev["id"]}, admin_payload={"event_id": ev["id"], "reason": reason})


def fire(c, s: dict, ev: dict, sc: dict) -> None:
    sid = str(s["id"])
    vt = ev.get("virtual_time") or s["virtual_time"]
    c.execute("UPDATE sessions SET virtual_time=%s WHERE id=%s", (vt, sid))
    s["virtual_time"] = vt
    record_action(c, sid, "SYSTEM", "EVENT_TRIGGERED", ev["id"], {"turn": s["turn_count"], "virtual_time": vt})
    st = state(s)
    first = None
    for line in ev["script"]:
        meta = {"kind": "SCENARIO_EVENT", "event_id": ev["id"], "virtual_time": vt}
        if ev["id"] == "E0" and line["actor"] == "colleague":
            meta["split_proposal"] = default_split(sc)
        m = post_line(c, sid, ACTOR[line["actor"]], line["text"], meta=meta)
        first = first or m
    c.execute("""INSERT INTO event_occurrences(session_id,event_id,turn,virtual_time,facts,first_message_id)
                 VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
              (sid, ev["id"], s["turn_count"], vt, J({"type": ev["type"]}), first["id"] if first else None))
    st["active_event"] = ev["id"]  # pushback_pending은 유지(반문 뒤 재요청이 다음 이벤트와 겹쳐도 이어서 처리)
    st["awaiting"] = {"event_id": ev["id"], "since_turn": s["turn_count"], "reminded": False} if ev["id"] in AWAITS_RESPONSE else None
    if ev["id"] == "E0":
        st["split"] = {"proposal": default_split(sc), "rounds": 0, "confirmed": False, "last_label": None,
                       "message_id": str(first["id"]) if first else None}
    for t in ev.get("adds_tasks", []):  # E2: T5 푸시 문구
        add_task_and_artifact(c, s, t["id"], t["title"], "UNASSIGNED")
    if ev["id"] == "E2":
        st["changed_fact"] = ev.get("changed_fact")
    if ev.get("colleague_status", {}).get("offline"):  # E3: 서윤 자리 비움, 답장 최대 1회
        st["colleague"] = {"offline": True, "offline_replies_left": ev["colleague_status"]["max_replies_while_offline"],
                           "until_event": ev["colleague_status"]["until_event"]}
    if ev["id"] == (st.get("colleague") or {}).get("until_event"):
        st["colleague"] = {"offline": False, "offline_replies_left": 0}
    if ev["id"] == "E4":
        t4 = next(t for t in sc["tasks"] if t["id"] == "T4")
        add_task_and_artifact(c, s, "T4", t4["title"], "CANDIDATE")
        st["e4"] = {"stage": "REPORT"}
    set_state(c, s, st)
    emit(c, sid, "EVENT_FIRED", {"event_id": ev["id"], "virtual_time": vt, "turn": s["turn_count"]})


def add_task_and_artifact(c, s: dict, key: str, title: str, owner: str) -> None:
    sid = str(s["id"])
    t = one(c, """INSERT INTO tasks(session_id,key,title,status,owner) VALUES (%s,%s,%s,'TODO',%s)
                  ON CONFLICT (session_id,key) DO NOTHING RETURNING *""", (sid, key, title, owner))
    a = one(c, """INSERT INTO artifacts(session_id,key,title) VALUES (%s,%s,%s)
                  ON CONFLICT (session_id,key) DO NOTHING RETURNING *""", (sid, key, ARTIFACT_TITLES.get(key, title)))
    if t:
        emit(c, sid, "TASK_UPDATED", {"task": task_dto(t)})
    if a:
        emit(c, sid, "ARTIFACT_UPDATED", {"artifact": artifact_dto(a), "actor": "SYSTEM"})


# ---- no-response policy ---------------------------------------------------------------------

def no_response(c, s: dict, sc: dict) -> None:
    st = state(s)
    aw = st.get("awaiting")
    if not aw:
        return
    sid = str(s["id"])
    waited = s["turn_count"] - aw["since_turn"]
    ev = next(e for e in sc["events"] if e["id"] == aw["event_id"])
    timeout = next((b for b in ev.get("branches", []) if b["when"] == "NO_RESPONSE"), None)
    if timeout:  # E1: 3턴 무응답 → 서윤 고정 대사 + CO-1
        if waited >= timeout["after_turns"]:
            m = post_line(c, sid, ACTOR[timeout["reply"]["actor"]], timeout["reply"]["text"],
                          meta={"kind": "SCENARIO_BRANCH", "event_id": ev["id"], "label": "NO_RESPONSE"})
            for code in timeout.get("observe", []):
                observe(c, sid, code, ev["id"], {"kind": "message", "id": str(m["id"])}, "3턴 동안 도움 요청에 응답 없음")
            st["awaiting"] = None
            set_state(c, s, st)
        return
    pol = sc["no_response_policy"]
    if not aw["reminded"] and waited >= pol["remind_after_turns"]:
        who = {"E4": "박준호 팀장"}.get(ev["id"], "한서윤")
        post_line(c, sid, "SYSTEM", f"{who}님의 메시지에 아직 답하지 않았습니다.",
                  meta={"kind": "REMINDER", "event_id": ev["id"]})
        aw.update({"reminded": True, "reminded_turn": s["turn_count"]})
        st["awaiting"] = aw
        set_state(c, s, st)
        return
    if aw["reminded"] and s["turn_count"] - aw.get("reminded_turn", aw["since_turn"]) >= pol["advance_after_turns"]:
        observe(c, sid, "RS-3", ev["id"], {"kind": "event", "id": ev["id"]}, "리마인드 후에도 무응답 → 다음 단계로 자동 진행")
        st["awaiting"] = None
        set_state(c, s, st)
        record_action(c, sid, "SYSTEM", "NO_RESPONSE_ADVANCED", ev["id"], {})
        if ev["id"] == "E0":
            confirm_split(c, s, default_split(sc), label="DEFAULT_FALLBACK", sc=sc)
        elif ev["id"] == "E2B":
            st = state(s)
            st["e2b_accepted"] = True
            set_state(c, s, st)
        elif ev["id"] == "E4":
            end_session(c, s, actor="SYSTEM", summary="E4 브리핑 무응답으로 자동 종료")


def e2_reminder(c, s: dict, sc: dict) -> None:
    """E2 NOT_REFLECTED: E2 후 3턴이 지나도 지원자 담당 산출물에 2,000P가 없으면 서윤이 1회 리마인드."""
    st = state(s)
    if st.get("e2_reminded"):
        return
    occ = one(c, "SELECT turn FROM event_occurrences WHERE session_id=%s AND event_id='E2' AND NOT skipped", (s["id"],))
    if not occ:
        return
    ev = next(e for e in sc["events"] if e["id"] == "E2")
    br = next(b for b in ev["branches"] if b["when"] == "NOT_REFLECTED")
    if s["turn_count"] - occ["turn"] < br["after_turns"]:
        return
    missing = missing_change(c, str(s["id"]), owners=("CANDIDATE",))
    if not missing:
        return
    post_line(c, str(s["id"]), ACTOR[br["reply"]["actor"]], br["reply"]["text"],
              meta={"kind": "SCENARIO_BRANCH", "event_id": "E2", "label": "NOT_REFLECTED"})
    st["e2_reminded"] = True
    set_state(c, s, st)


def missing_change(c, sid: str, *, owners: tuple[str, ...] | None = None) -> list[str]:
    """E2 end_check(doc_contains '2,000P'): 안내문·FAQ·표 중 2,000P가 없는 산출물 key."""
    rows = all_(c, """SELECT a.key, a.body, t.owner FROM artifacts a LEFT JOIN tasks t ON t.session_id=a.session_id AND t.key=a.key
                      WHERE a.session_id=%s AND a.key IN ('T1','T2','T3') ORDER BY a.key""", (sid,))
    return [r["key"] for r in rows if (owners is None or (r["owner"] or "UNASSIGNED") in owners) and not TWO_K.search(r["body"])]


# ---- E0 split -------------------------------------------------------------------------------

def default_split(sc: dict) -> dict:
    d = sc["default_split"]
    faq_c = next((int(x.split(":")[1]) for x in d["candidate"] if x.startswith("T2:")), 0)
    return {"T1": "CANDIDATE" if "T1" in d["candidate"] else "COLLEAGUE",
            "T3": "CANDIDATE" if "T3" in d["candidate"] else "COLLEAGUE", "faq_candidate": faq_c}


def split_label(p: dict) -> str:
    """분업 제안 분류(결정적). 부하 단위: 안내문 2, 표 2, FAQ 1개당 1 (총 9)."""
    cand = (2 if p["T1"] == "CANDIDATE" else 0) + (2 if p["T3"] == "CANDIDATE" else 0) + p["faq_candidate"]
    if cand == 9:
        return "TAKE_ALL"
    if cand <= 3:
        return "ONE_SIDED_SPLIT"
    return "BALANCED_SPLIT"


def confirm_split(c, s: dict, p: dict, *, label: str, sc: dict | None = None) -> None:
    sid = str(s["id"])
    st = state(s)
    sp = dict(st.get("split") or {})
    sp.update({"proposal": p, "confirmed": True, "final_label": label})
    st["split"] = sp
    if st.get("awaiting", {}) and st["awaiting"]["event_id"] == "E0":
        st["awaiting"] = None
    set_state(c, s, st)
    faq_c = p["faq_candidate"]
    owners = {"T1": p["T1"], "T3": p["T3"],
              "T2": "CANDIDATE" if faq_c == 5 else ("COLLEAGUE" if faq_c == 0 else "SPLIT")}
    for key, owner in owners.items():
        note = f"FAQ 지원자 {faq_c}개 / 서윤 {5 - faq_c}개" if key == "T2" else None
        t = one(c, "UPDATE tasks SET owner=%s, note=COALESCE(%s,note), version=version+1 WHERE session_id=%s AND key=%s RETURNING *",
                (owner, note, sid, key))
        if t:
            emit(c, sid, "TASK_UPDATED", {"task": task_dto(t)})
    record_action(c, sid, "SYSTEM", "SPLIT_CONFIRMED", sp.get("message_id"), {"proposal": p, "label": label})
    names = {"CANDIDATE": "나", "COLLEAGUE": "한서윤"}
    post_line(c, sid, "SYSTEM", f"분업 확정: 안내문 {names[p['T1']]} · 리워드 표 {names[p['T3']]} · FAQ 나 {faq_c}개 / 한서윤 {5 - faq_c}개",
              meta={"kind": "SPLIT_CONFIRMED", "label": label})
    emit(c, sid, "SPLIT_UPDATED", {"split": public_split(st)})


def public_split(st: dict) -> dict | None:
    sp = st.get("split")
    if not sp:
        return None
    return {"proposal": sp["proposal"], "rounds": sp["rounds"], "confirmed": sp["confirmed"], "max_rounds": 3}


# ---- observations ---------------------------------------------------------------------------

def observe(c, sid: str, code: str, event_id: str | None, evidence: dict, note: str = "", *,
            subject: str | None = None, source: str = "RULES", run_id: str | None = None) -> bool:
    from shared.scenario import codebook, competency_of
    if code not in codebook():
        raise ValueError(f"코드북에 없는 관찰 코드: {code}")
    r = one(c, """INSERT INTO observations(session_id,code,competency,event_id,subject,evidence_ref,note,source,run_id)
                  VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING RETURNING id""",
            (sid, code, competency_of(code), event_id, subject, J(evidence), note[:500], source, run_id))
    if r:
        emit(c, sid, "OBSERVATION_RECORDED", {}, admin_payload={"code": code, "event_id": event_id, "subject": subject})
    return bool(r)


# ---- session end ----------------------------------------------------------------------------

def end_session(c, s: dict, *, actor: str, summary: str = "") -> str:
    """Close session: cancel runs/approvals, end-of-session judgement(규칙), REPORT job. Caller holds row lock."""
    from .judge import judge_session
    sid = str(s["id"])
    existing = one(c, "SELECT id FROM reports WHERE session_id=%s", (sid,))
    if existing:
        return str(existing["id"])
    c.execute("UPDATE sessions SET status='SUBMITTED', phase='CLOSED', submitted_at=now(), version=version+1 WHERE id=%s", (sid,))
    s["status"] = "SUBMITTED"
    runs = all_(c, """UPDATE runs SET status='CANCELLED', updated_at=now() WHERE session_id=%s
                      AND status IN ('QUEUED','RUNNING','WAITING_APPROVAL') RETURNING id""", (sid,))
    for r in runs:
        c.execute("UPDATE jobs SET status='DONE' WHERE run_id=%s AND status IN ('QUEUED','LEASED')", (r["id"],))
    c.execute("UPDATE approvals SET status='EXPIRED' WHERE session_id=%s AND status='PENDING'", (sid,))
    seq = record_action(c, sid, actor, "SUBMITTED" if actor == "CANDIDATE" else "AUTO_ENDED", None,
                        {"summary": summary, "turn": s["turn_count"], "virtual_time": s["virtual_time"]})
    judge_session(c, s)
    snapshot = {"last_action_seq": seq, "ended_by": actor, "turn_count": s["turn_count"], "virtual_time": s["virtual_time"],
                "artifacts": {a["key"]: a["version"] for a in all_(c, "SELECT key, version FROM artifacts WHERE session_id=%s", (sid,))}}
    rep = one(c, "INSERT INTO reports(session_id,status,source_snapshot) VALUES (%s,'PENDING',%s) RETURNING id", (sid, J(snapshot)))
    enqueue_job(c, sid, "REPORT", f"report:{rep['id']}", input_={"report_id": str(rep["id"])})
    emit(c, sid, "SESSION_DONE", {"report_id": str(rep["id"])})
    return str(rep["id"])


__all__ = ["start_session", "add_turn", "tick", "fire_due", "end_session", "observe", "confirm_split", "split_label",
           "default_split", "public_split", "missing_change", "list_tasks", "create_run", "state", "TWO_K"]

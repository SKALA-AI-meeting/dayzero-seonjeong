"""분기 분류 점검: 3개 phase 라우팅 + work 단계 닫힌 분류기(live LLM vs fixture 규칙) + briefing·negotiate 판정.

uv run python -m scripts.classify_check  (live 분류는 OPENAI_API_KEY 필요, 서비스 기동 불필요)

graph.py의 실제 함수(route_phase, work, classify_live, classify_rules, briefing, negotiate)를 합성 컨텍스트로 호출한다.
"""
import json
import sys

from agent.app import graph as G
from shared.scenario import public_definition, scenario, targets_in

SC = public_definition(scenario())
EV = {e["id"]: e for e in SC["events"]}
RULES = scenario()["characters"]["colleague"]["feedback_rules"]
ACT = {"manager": "MANAGER", "colleague": "COLLEAGUE"}


def ctx_for(ev_id, *, pending=None, allow_e2=True, e4_stage=None):
    ev = EV[ev_id]
    msgs = [{"actor": ACT[l["actor"]], "content": l["text"]} for l in ev["script"]]
    if pending:
        msgs.append({"actor": "COLLEAGUE", "content": "아 근데 그건 제가 받은 범위가 아니어서요… 제가 하는 게 맞을까요?"})
    return {"event": ev, "scenario": SC, "feedback_rules": RULES, "messages": msgs,
            "state": {"pushback_pending": pending, "manager_answered": [], "e4": {"stage": e4_stage} if e4_stage else None,
                      "colleague": {"offline": False}},
            "allow_pushback": {"E0": ev_id == "E0", "E2": allow_e2 and ev_id in ("E2", "E2B")},
            "run": {"input": {}, "source_message_id": "m"}, "tasks": [], "artifacts": [], "events": [],
            "candidate_alias": "지원자"}


def labels(ctx, to):
    st = {"ctx": ctx, "to": to, "event_id": ctx["event"]["id"], "text": ""}
    return G.work.__wrapped__(st)["labels"] if hasattr(G.work, "__wrapped__") else G.work(st)["labels"]


# (이벤트, 받는 사람, 메시지, 기대 라벨들(허용), 유형, 반문 대기)
CASES = [
    ("E1", "COLLEAGUE", "지금 바로 같이 볼게요. 어디가 헷갈리세요?", {"HELP_NOW"}, "정상 응답", None),
    ("E1", "COLLEAGUE", "안내문 끝내고 11시쯤 같이 볼게요.", {"HELP_LATER_WITH_TIME"}, "정상 응답", None),
    ("E1", "COLLEAGUE", "지금은 FAQ 마감 때문에 어려울 것 같아요. 죄송해요.", {"DECLINE_WITH_REASON"}, "정상 응답", None),
    ("E1", "COLLEAGUE", "음… 글쎄요.", {"NONE"}, "애매한 표현", None),
    ("E1", "COLLEAGUE", "오늘 점심 뭐 먹을까요?", {"NONE"}, "무관한 말", None),
    ("E1", "COLLEAGUE", "표 일정이 11/2 ~ 11/31인데 11월은 30일까지라 없는 날짜예요. 브리프대로 고쳐주실 수 있을까요?", {"SPECIFIC_CORRECTION"}, "심어둔 오류 언급", None),
    ("E1", "COLLEAGUE", "표가 좀 이상한 것 같아요.", {"VAGUE_CRITICISM"}, "애매한 표현", None),
    ("E1", "COLLEAGUE", "왜 이렇게 대충 하셨어요? 다 틀렸잖아요.", {"HARSH_BLAME"}, "비난", None),
    ("E1", "COLLEAGUE", "제외 대상이 '동일 결제수단 계정'으로 돼 있는데 그거 잘못된 것 같아요.", {"WRONG_CRITICISM"}, "사실과 다른 지적", None),
    ("E2", "MANAGER", "팀장님, 피초대자도 첫 결제를 해야 2,000P를 받나요?", {"CLARIFYING_QUESTION"}, "정상 응답", None),
    ("E2", "MANAGER", "푸시까지 하면 17시까지 빠듯할 것 같은데 우선순위 조정이 가능할까요?", {"RISK_ESCALATION"}, "정상 응답", None),
    ("E2", "MANAGER", "넵 알겠습니다.", {"NONE"}, "애매한 표현", None),
    ("E2", "COLLEAGUE", "푸시 문구는 서윤 씨가 맡아 주시고 저는 FAQ를 마무리할게요. 보드도 바꿔둘게요.", {"REPLAN_OR_RESPLIT"}, "정상 응답", None),
    ("E2", "COLLEAGUE", "서윤 씨 표에도 피초대자 2,000P 반영 부탁드려요.", {"SPECIFIC_CORRECTION", "OUT_OF_SCOPE_REQUEST"}, "변경 반영 요청", None),
    ("E2B", "COLLEAGUE", "수고하셨어요!", {"ACCEPT_AS_DONE"}, "정상 응답", None),
    ("E2B", "COLLEAGUE", "표랑 FAQ는 서윤 씨 담당이라서요. 팀장님이 전부 반영해 달라고 하셨어요.", {"REQUEST_REPEATED_WITH_REASON"}, "반문 뒤 재요청", {"targets": ["E2-CHANGE"]}),
    ("E2B", "COLLEAGUE", "아 그럼 그냥 제가 할게요.", {"GIVE_UP_AND_FIX_SELF"}, "반문 뒤 포기", {"targets": ["E2-CHANGE"]}),
    ("E3", "COLLEAGUE", "급하신 거 알겠어요. 제가 이어서 할 부분이 어디예요?", {"HANDOVER_QUESTION"}, "정상 응답", None),
    ("E3", "COLLEAGUE", "다녀오세요. 표 피초대자 칸은 제가 채워둘게요.", {"TAKE_OVER_AND_NOTIFY"}, "정상 응답", None),
    ("E3B", "COLLEAGUE", "네, 브리프랑 달라서 금액을 3,000P로 맞춰뒀어요. 확인 부탁해요.", {"SOLUTION_FOCUSED_SHARE"}, "정상 응답(live 흐름 실패 문장)", None),
    ("E3B", "COLLEAGUE", "금액이 완전히 틀렸던데 왜 브리프 안 보셨어요?", {"BLAME_FOCUSED", "HARSH_BLAME"}, "비난", None),
    ("E3B", "COLLEAGUE", "주말에 뭐 하세요?", {"NONE"}, "무관한 말", None),
]


def main():
    out = {"phase": [], "work": [], "briefing": [], "negotiate": []}
    # 1) phase 라우팅
    for name, st, want in [
        ("분업 제안(run.type=split)", {"run_type": "split", "event_id": "E0", "to": "COLLEAGUE", "ctx": ctx_for("E0")}, "negotiate"),
        ("E0 중 채팅", {"run_type": "message", "event_id": "E0", "to": "COLLEAGUE", "ctx": ctx_for("E0")}, "work"),
        ("E2 팀장에게 질문", {"run_type": "message", "event_id": "E2", "to": "MANAGER", "ctx": ctx_for("E2")}, "work"),
        ("E4 보고(팀장, REPORT)", {"run_type": "message", "event_id": "E4", "to": "MANAGER", "ctx": ctx_for("E4", e4_stage="REPORT")}, "briefing"),
        ("E4 후속 답(팀장, FOLLOW_UP)", {"run_type": "message", "event_id": "E4", "to": "MANAGER", "ctx": ctx_for("E4", e4_stage="FOLLOW_UP")}, "briefing"),
        ("E4 중 서윤에게", {"run_type": "message", "event_id": "E4", "to": "COLLEAGUE", "ctx": ctx_for("E4", e4_stage="REPORT")}, "work"),
        ("E4 종료 후 팀장에게", {"run_type": "message", "event_id": "E4", "to": "MANAGER", "ctx": ctx_for("E4", e4_stage="DONE")}, "work"),
    ]:
        got = G.route_phase(st)
        out["phase"].append({"case": name, "want": want, "got": got, "ok": got == want})
    # 2) work 닫힌 분류
    for ev, to, text, want, kind, pending in CASES:
        ctx = ctx_for(ev, pending=pending)
        st = {"ctx": ctx, "to": to, "event_id": ev, "text": text, "run_id": "x", "token_usage": {"input": 0, "output": 0}}
        labs = G.work(st)["labels"]
        try:
            live = G.classify_live(st, labs)
        except Exception as e:  # noqa: BLE001
            live = f"ERROR:{type(e).__name__}"
        rule = G.classify_rules(text, targets_in(text), labs)
        out["work"].append({"event": ev, "to": to, "kind": kind, "text": text, "want": sorted(want), "live": live,
                            "fixture": rule, "live_ok": live in want, "fixture_ok": rule in want,
                            "allowed": labs})
    # 3) briefing(E4, 규칙 판정 — live에서도 LLM 미사용)
    tasks = [{"key": "T1", "status": "IN_PROGRESS", "owner": "CANDIDATE"}, {"key": "T5", "status": "TODO", "owner": "CANDIDATE"}]
    for stage, text, want in [
        ("REPORT", "안내문·표는 정리했고 푸시 문구는 아직 진행 중입니다. 표·FAQ 초안은 서윤 씨가 만들었어요.", {"HO+1", "HO+2"}),
        ("REPORT", "전부 다 끝났습니다. 문제 없어요.", {"HO-1"}),
        ("FOLLOW_UP", "아니요, 초안은 서윤 씨가 썼고 저는 검토만 했어요.", {"HO+3"}),
        ("FOLLOW_UP", "네, 제가 다 정리했어요.", {"HO-2"}),
    ]:
        ctx = ctx_for("E4", e4_stage=stage)
        ctx.update({"tasks": tasks, "events": [], "artifacts": []})
        r = G.briefing({"ctx": ctx, "text": text, "event_id": "E4"})
        got = {o["code"] for o in r["observes"]}
        out["briefing"].append({"stage": stage, "text": text, "want": sorted(want), "got": sorted(got), "ok": got == want})
    # 4) negotiate(E0, 결정적)
    for p, last, allow, want in [
        ({"T1": "CANDIDATE", "T3": "COLLEAGUE", "faq_candidate": 3}, None, True, ("BALANCED_SPLIT", True, ["CO+1"])),
        ({"T1": "CANDIDATE", "T3": "COLLEAGUE", "faq_candidate": 0}, None, True, ("ONE_SIDED_SPLIT", False, [])),
        ({"T1": "CANDIDATE", "T3": "COLLEAGUE", "faq_candidate": 0}, "ONE_SIDED_SPLIT", False, ("ONE_SIDED_SPLIT", True, ["CO-2"])),
        ({"T1": "CANDIDATE", "T3": "CANDIDATE", "faq_candidate": 5}, None, True, ("TAKE_ALL", False, [])),
    ]:
        ctx = ctx_for("E0")
        ctx["run"]["input"] = {"proposal": p, "action_id": "a"}
        ctx["state"]["split"] = {"last_label": last}
        ctx["allow_pushback"]["E0"] = allow
        r = G.negotiate({"ctx": ctx})
        got = (r["label"], r["effects"]["split"]["confirm"], [o["code"] for o in r["observes"]])
        out["negotiate"].append({"proposal": p, "want": want, "got": list(got), "ok": got == want})
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()

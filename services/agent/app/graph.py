"""LangGraph run graph — 서윤·팀장 응답 (docs/SCENARIO_SC_A.md 8장, ARCHITECTURE §8).

세션 흐름(E0→E1→E2→E2B→E3→E3B→E4, 이벤트 순서·트리거)은 gateway 턴 엔진(engine.py)이 소유한다.
이 Graph는 지원자 행동 1개(메시지·분업 제안)마다 1회 실행되며, 활성 이벤트에 따라 단계 노드로 갈라진다.

load_scenario → route_phase ─┬─ negotiate (E0 분업, 최대 3라운드: 제안마다 1회)
                             ├─ work      (E1~E3B 분기 라벨 + 서윤 feedback_rules)
                             └─ briefing  (E4 보고 ↔ 보드·diff 대조, 후속 질문 1회 → 종료)
  → classify(닫힌 분류기: 허용 라벨 중 하나 또는 NONE) → decide
  → record_observations(record_observation MCP) → apply_effects(턴 엔진 상태) → respond
       ├─ NONE: reason ⇄ call_mcp (live) → validate_output(정답 누설·근거 가드) → respond
       └─ 정정 수용: propose_fix(get_planted_error) → persist_proposal → await_approval(interrupt)
                     → execute_write | record_rejection → (다음 수정안 반복) → report_fix → END

고정 대사(분기 reply)는 LLM 생성 없이 그대로 보낸다(meta.kind=SCENARIO_BRANCH). 반문(allow_pushback)은
gateway가 계산한 플래그로만 켠다(E0 불균형 분업, E2/E2B 범위 밖 요청, 각 1회). 서윤은 스스로 오류를 찾거나 고치지 않는다.
"""
from __future__ import annotations

import json
import re
import time
import uuid
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from shared.config import POLICY_VERSION, settings
from shared.scenario import targets_in

from . import harness as H
from .clients import Gateway, call_tool, get_prompt, list_read_tools

S = settings()
gw = Gateway()
FALLBACK_COLLEAGUE = "넵 알겠어요!"          # 설계서 7장 말투 예시
MANAGER_DEFER = "그건 서윤 씨랑 정해서 진행해 주세요."  # 설계서 7장 팀장 규칙
FIXED_REPORT = "고쳤어요"                    # 설계서 4장 E2-b "수정 후 '고쳤어요'"
CHAT_TOOLS = {"search_docs", "get_session_context"}


class WorkState(TypedDict, total=False):
    session_id: str
    run_id: str
    run_type: str
    policy_version: str
    ctx: dict
    phase: str
    event_id: str | None
    to: str
    text: str
    labels: list[str]
    label: str
    reply: dict | None
    observes: list[dict]
    effects: dict
    targets: list[str]
    fixes: list[dict]
    fix_index: int
    fix_results: list[dict]
    approval_id: str | None
    decision: str | None
    answer: str
    answer_actor: str
    silent_notice: str | None
    llm_messages: list[dict]
    plan: list[dict]
    tool_results: list[dict]
    tool_counts: dict[str, int]
    citations: list[dict]
    step_count: int
    active_execution_ms: int
    output_rewrite_count: int
    limited: str | None
    error_code: str | None
    token_usage: dict


def _timed(fn):
    def wrapper(state: WorkState) -> dict:
        t0 = time.monotonic()
        out = fn(state) or {}
        out["active_execution_ms"] = state.get("active_execution_ms", 0) + int((time.monotonic() - t0) * 1000)
        return out
    wrapper.__name__ = fn.__name__
    return wrapper


def mcp(state: WorkState, tool: str, args: dict) -> dict:
    """Real MCP tools/call with TOOL_START/TOOL_END stream events (tool_calls 로그)."""
    tcid = f"tc-{uuid.uuid4().hex[:8]}"
    gw.event(state["run_id"], "TOOL_START", {"tool_call_id": tcid, "tool_name": tool}, key=f"start:{tcid}")
    payload, ms = call_tool(gw, state["run_id"], tool, args)
    gw.event(state["run_id"], "TOOL_END", {"tool_name": tool, "safe_args": {k: v for k, v in args.items() if k != "content"},
                                           "outcome": "ok" if payload["ok"] else payload["error"]["code"],
                                           "result_summary": {"ok": payload["ok"]}, "citations": payload.get("citations", []),
                                           "duration_ms": ms}, key=f"end:{tcid}")
    return payload


# ---- load / route ---------------------------------------------------------------------------

@_timed
def load_scenario(state: WorkState) -> dict:
    ctx = gw.get(f"/runs/{state['run_id']}/context")
    run_input = ctx["run"]["input"] or {}
    scen = mcp(state, "get_scenario", {})  # business-mcp: 이벤트 분기 라벨·고정 대사(정답 제외)
    nxt = mcp(state, "get_next_event", {})
    ctx["scenario"] = scen.get("data") or {}
    ctx["next_event"] = nxt.get("data") or {}
    text = run_input.get("content", "")
    to = run_input.get("to", "COLLEAGUE")
    if to == "COLLEAGUE" and re.match(r"^\s*(박준호\s*)?팀장님", text):
        to = "MANAGER"
    return {"session_id": ctx["session"]["id"], "ctx": ctx, "run_type": run_input.get("type", "message"),
            "event_id": run_input.get("event_id") or ctx["state"].get("active_event"), "text": text, "to": to,
            "policy_version": POLICY_VERSION, "observes": [], "effects": {}, "targets": targets_in(text),
            "reply": None, "answer": "", "answer_actor": "COLLEAGUE", "silent_notice": None,
            "fixes": [], "fix_index": 0, "fix_results": [], "tool_results": [], "tool_counts": {}, "citations": [],
            "step_count": 0, "output_rewrite_count": 0, "error_code": None,
            "token_usage": state.get("token_usage") or {"input": 0, "output": 0}}


def route_phase(state: WorkState) -> str:
    if state["run_type"] == "split":
        return "negotiate"
    e4 = state["ctx"]["state"].get("e4") or {}
    if state["event_id"] == "E4" and e4.get("stage") in ("REPORT", "FOLLOW_UP") and state["to"] == "MANAGER":
        return "briefing"
    return "work"


# ---- E0 negotiate ---------------------------------------------------------------------------

def _branch(state: WorkState, event_id: str, label: str) -> dict | None:
    ev = state["ctx"]["event"] if (state["ctx"].get("event") or {}).get("id") == event_id else \
        next((e for e in state["ctx"]["scenario"].get("events", []) if e["id"] == event_id), None)
    return next((b for b in (ev or {}).get("branches", []) if b["when"] == label), None)


def _split_label(p: dict) -> str:
    cand = (2 if p["T1"] == "CANDIDATE" else 0) + (2 if p["T3"] == "CANDIDATE" else 0) + int(p["faq_candidate"])
    return "TAKE_ALL" if cand == 9 else ("ONE_SIDED_SPLIT" if cand <= 3 else "BALANCED_SPLIT")


@_timed
def negotiate(state: WorkState) -> dict:
    """E0 분업 제안 분기(결정적). 불균형 분업 반문은 allow_pushback.E0일 때 1회, 이후에도 유지하면 CO-2."""
    inp = state["ctx"]["run"]["input"]
    p, label = inp["proposal"], _split_label(inp["proposal"])
    split = state["ctx"]["state"].get("split") or {}
    allow = state["ctx"]["allow_pushback"]["E0"]
    br = _branch(state, "E0", label) or {}
    ref = {"kind": "action", "id": inp["action_id"]}
    out: dict[str, Any] = {"phase": "negotiate", "label": label, "labels": ["BALANCED_SPLIT", "ONE_SIDED_SPLIT", "TAKE_ALL"],
                           "reply": None, "observes": [], "effects": {}, "targets": []}
    if label == "BALANCED_SPLIT":
        out["reply"] = br.get("reply")
        out["observes"] = [{"code": c, "event_id": "E0", "evidence": ref, "note": "분업 제안이 균형 있게 나뉨"} for c in br.get("observe", [])]
        out["effects"] = {"split": {"label": label, "confirm": True, "proposal": p}}
    elif label == "ONE_SIDED_SPLIT" and allow:
        out["reply"] = br.get("reply")  # 재협상 기회 1회
        out["effects"] = {"pushback_used": "E0", "split": {"label": label, "confirm": False, "proposal": p}}
    elif label == "ONE_SIDED_SPLIT":
        out["observes"] = [{"code": c, "event_id": "E0", "evidence": ref, "note": "재협상 기회 후에도 일방적 분업 유지"}
                           for c in br.get("observe_if_unchanged", [])]
        out["effects"] = {"split": {"label": label, "confirm": True, "proposal": p}}
    elif label == "TAKE_ALL" and split.get("last_label") != "TAKE_ALL":
        out["reply"] = br.get("reply")
        out["effects"] = {"split": {"label": label, "confirm": False, "proposal": p}}
    else:
        out["effects"] = {"split": {"label": label, "confirm": True, "proposal": p}}  # 기록만
    return out


# ---- work: allowed labels -----------------------------------------------------------------

MANAGER_LABELS = {"CLARIFYING_QUESTION", "RISK_ESCALATION"}
TIMEOUT_LABELS = {"NO_RESPONSE", "NOT_REFLECTED", "BOARD_PLANNED"}
SPLIT_LABELS = {"BALANCED_SPLIT", "ONE_SIDED_SPLIT", "TAKE_ALL"}  # 분업은 SplitCard(negotiate)로만
PUSHBACK_FOLLOW = {"REQUEST_REPEATED_WITH_REASON", "GIVE_UP_AND_FIX_SELF"}  # 반문 뒤에만


@_timed
def work(state: WorkState) -> dict:
    ctx = state["ctx"]
    ev = ctx.get("event") or {}
    labels: list[str] = []
    if state["to"] == "MANAGER":
        if state["event_id"] in ("E2", "E2B"):
            labels = [b["when"] for b in (_branch_list(state, "E2")) if b["when"] in MANAGER_LABELS
                      and b["when"] not in (ctx["state"].get("manager_answered") or [])]
        labels += [b["when"] for b in ev.get("branches", []) if b.get("reply") is None and b["when"] not in TIMEOUT_LABELS
                   and ev.get("id") in ("E3",)]
        return {"phase": "work", "labels": labels}
    pending = bool(ctx["state"].get("pushback_pending"))
    for b in ([] if ev.get("id") == "E4" else ev.get("branches", [])):
        if b["when"] in TIMEOUT_LABELS | MANAGER_LABELS | SPLIT_LABELS or (b["when"] in PUSHBACK_FOLLOW and not pending):
            continue
        labels.append(b["when"])
    if ctx["state"].get("pushback_pending"):
        labels += ["REQUEST_REPEATED_WITH_REASON", "GIVE_UP_AND_FIX_SELF"]
    labels += [r["when"] for r in ctx["feedback_rules"] if r["when"] not in PUSHBACK_FOLLOW or pending]
    return {"phase": "work", "labels": list(dict.fromkeys(labels))}


def _branch_list(state: WorkState, event_id: str) -> list[dict]:
    ev = next((e for e in state["ctx"]["scenario"].get("events", []) if e["id"] == event_id), None)
    return (ev or {}).get("branches", [])


# ---- classify (closed) ------------------------------------------------------------------------

REQ = re.compile(r"(부탁|해\s*주|해주|고쳐\s*주|수정해\s*주|반영해\s*주|바꿔\s*주|넣어\s*주|주실|주세요|줄\s*수|해\s*줘|해줘)")
REASON = re.compile(r"(때문|라서|여서|이라|브리프|팀장님|변경|기준|근거|담당|맡은|초안|가이드)")
RULES: dict[str, Any] = {
    "HARSH_BLAME": lambda t, tg: re.search(r"(왜\s*이렇게|제대로\s*(좀|안)|대충|한심|짜증|도대체|정신\s*차|이것도\s*못)", t),
    "GIVE_UP_AND_FIX_SELF": lambda t, tg: re.search(r"(제가\s*(할게요|고칠게요|수정할게요|반영할게요|하겠습니다|고치겠|할께요)|제가\s*대신|아\s*괜찮아요|괜찮습니다|됐어요)", t),
    "REQUEST_REPEATED_WITH_REASON": lambda t, tg: REQ.search(t) or REASON.search(t),
    "WRONG_CRITICISM": lambda t, tg: re.search(r"(3,?000\s*P|11\s*/\s*15|결제\s*수단).{0,12}(틀|아니|잘못)", t),
    "SPECIFIC_CORRECTION": lambda t, tg: tg and (REQ.search(t) or "?" in t or re.search(r"(틀|잘못|아니라|다르|없는|안\s*맞)", t)),
    "VAGUE_CRITICISM": lambda t, tg: not tg and re.search(r"(이상한|이상해|틀린\s*것\s*같|잘못된\s*것\s*같|뭔가|다시\s*봐)", t),
    "OUT_OF_SCOPE_REQUEST": lambda t, tg: False,  # fixture는 E2-CHANGE 대상 정정 요청으로 대신 판정(live 분류기 전용)
    "HELP_LATER_WITH_TIME": lambda t, tg: re.search(r"(\d{1,2}\s*시|\d+\s*분\s*(뒤|후)|이따|끝내고|끝나고|후에|조금\s*뒤)", t),
    "HELP_NOW": lambda t, tg: re.search(r"(지금|바로|같이\s*봐|볼게요|봐\s*드릴|봐드릴|어디가|어떤\s*부분|보여\s*주)", t),
    "DECLINE_WITH_REASON": lambda t, tg: re.search(r"(어렵|힘들|못\s*할|바빠|바쁘|여유가\s*없|지금은\s*안)", t),
    "RISK_ESCALATION": lambda t, tg: re.search(r"(빠듯|어려울|부족|늦어|리스크|못\s*끝|내일|우선순위)", t),
    "CLARIFYING_QUESTION": lambda t, tg: "?" in t or re.search(r"(인가요|나요|건가요|되나요|맞나요)", t),
    "REPLAN_OR_RESPLIT": lambda t, tg: re.search(r"(나눠|나누|분담|맡아|맡을|재분배|담당|보드)", t),
    "HANDOVER_QUESTION": lambda t, tg: re.search(r"(이어서|인계|남은|어디까지|뭐\s*하면|할\s*부분|뭘\s*하면)", t),
    "TAKE_OVER_AND_NOTIFY": lambda t, tg: re.search(r"(제가\s*(이어|마무리|맡|채울|채워|할게요|하겠습니다)|이어받|대신\s*(할|하겠|채))", t),
    "SOLUTION_FOCUSED_SHARE": lambda t, tg: re.search(r"((맞춰|고쳐|수정해|반영해|바꿔)\s*(뒀|놨|두었)|확인\s*부탁|확인해\s*주세요)", t),
    "BLAME_FOCUSED": lambda t, tg: re.search(r"(틀렸|잘못\s*(했|썼|됐)|실수|제대로)", t),
    "ACCEPT_AS_DONE": lambda t, tg: not tg and not REQ.search(t) and re.search(r"(수고|고생|감사|고마워|좋아요|넵|네\s*알겠|확인했)", t),
}
PRIORITY = ["HARSH_BLAME", "SOLUTION_FOCUSED_SHARE", "BLAME_FOCUSED", "GIVE_UP_AND_FIX_SELF", "REQUEST_REPEATED_WITH_REASON",
            "WRONG_CRITICISM", "SPECIFIC_CORRECTION", "OUT_OF_SCOPE_REQUEST", "VAGUE_CRITICISM", "HELP_LATER_WITH_TIME",
            "DECLINE_WITH_REASON", "HELP_NOW", "RISK_ESCALATION", "CLARIFYING_QUESTION", "REPLAN_OR_RESPLIT",
            "HANDOVER_QUESTION", "TAKE_OVER_AND_NOTIFY", "ACCEPT_AS_DONE"]


def classify_rules(text: str, targets: list[str], labels: list[str]) -> str:
    for lb in PRIORITY:
        if lb in labels and RULES[lb](text, targets):
            return lb
    return "NONE"


def classify_live(state: WorkState, labels: list[str]) -> str:
    from langchain_core.messages import HumanMessage, SystemMessage
    system, _ = H.load_prompt("classify-branch-v1")
    ctx = state["ctx"]
    recent = [f"({m['actor']}) {H.truncate_tokens(m['content'], 80)}" for m in ctx["messages"][-6:]]
    user = json.dumps({"event": {k: (ctx.get("event") or {}).get(k) for k in ("id", "type", "script")},
                       "pushback_pending": bool(ctx["state"].get("pushback_pending")), "recent": recent,
                       "allowed_labels": labels + ["NONE"], "message": state["text"]}, ensure_ascii=False)
    llm = _llm(json_mode=True)
    ai = H.with_retries(lambda: llm.invoke([SystemMessage(system), HumanMessage(H.mask_pii(user))]), deadline=time.monotonic() + 30)
    _usage(state, ai)
    label = (json.loads(ai.content or "{}") or {}).get("label", "NONE")
    return label if label in labels else "NONE"


@_timed
def classify(state: WorkState) -> dict:
    if state["run_type"] == "split" or state.get("phase") == "briefing":
        return {}
    labels = state.get("labels") or []
    if not labels:
        return {"label": "NONE"}
    label = "NONE"
    if S.llm_mode == "live":
        try:
            label = classify_live(state, labels)
        except Exception:  # noqa: BLE001 — 분류 실패는 규칙 분류로 대체(즉흥 연출 없음)
            label = classify_rules(state["text"], state["targets"], labels)
    else:
        label = classify_rules(state["text"], state["targets"], labels)
    return {"label": label, "token_usage": state.get("token_usage")}


# ---- decide: label → 고정 대사·관찰 코드·상태 효과·정정 수용 -----------------------------------

COMMIT_RE = re.compile(r"(할게요|볼게요|하겠습니다|드릴게요|해둘게요|해\s*둘게요|할께요|볼께요|보겠습니다)")


def _rule(state: WorkState, label: str) -> dict | None:
    return next((r for r in state["ctx"]["feedback_rules"] if r["when"] == label), None)


@_timed
def decide(state: WorkState) -> dict:
    ctx, label, ev_id = state["ctx"], state.get("label", "NONE"), state["event_id"]
    if state["run_type"] == "split":
        return {}
    msg_ref = {"kind": "message", "id": ctx["run"]["source_message_id"]}
    observes, effects = [], {}
    reply: dict | None = None
    targets = list(state["targets"])
    fix_targets: list[str] = []
    col = ctx["state"].get("colleague") or {}
    allow_e2 = ctx["allow_pushback"]["E2"]
    pending = ctx["state"].get("pushback_pending")

    if state["to"] == "MANAGER":
        br = next((b for b in _branch_list(state, "E2") if b["when"] == label), None) if label in MANAGER_LABELS else None
        if br:
            reply = br["reply"]
            observes = [{"code": c, "event_id": "E2", "evidence": msg_ref, "note": label} for c in br.get("observe", [])]
            effects["manager_answered"] = label
        elif label == "TAKE_OVER_AND_NOTIFY":
            br = _branch(state, "E3", label)
            observes = [{"code": c, "event_id": "E3", "evidence": msg_ref, "note": "서윤 파트 인계를 팀장에게 알림"} for c in br.get("observe", [])]
        elif "MANAGER_FREE" not in (ctx["state"].get("manager_answered") or []):
            effects["manager_answered"] = "MANAGER_FREE"  # 브리프 범위 안에서 1회 답
            return {"observes": observes, "effects": effects, "reply": None, "answer_actor": "MANAGER", "targets": []}
        else:
            return {"observes": observes, "effects": effects, "reply": None, "targets": [],
                    "silent_notice": "박준호 팀장님은 지금 회의 중입니다."}
        return {"observes": observes, "effects": effects, "reply": reply, "answer_actor": "MANAGER", "targets": []}

    if col.get("offline"):
        if int(col.get("offline_replies_left", 0)) <= 0:
            return {"reply": None, "silent_notice": "한서윤님은 자리 비움 상태입니다.", "targets": [],
                    "observes": _offline_obs(state, label, msg_ref)}
        effects["colleague_reply_used"] = True

    ev_branch = _branch(state, ev_id, label) if ev_id and label != "NONE" else None
    e2_target = "E2-CHANGE" in targets and ev_id in ("E2", "E2B")
    if label in ("SPECIFIC_CORRECTION", "OUT_OF_SCOPE_REQUEST", "REQUEST_REPEATED_WITH_REASON") and e2_target and allow_e2 and not pending:
        # 범위 밖 요청(E2 변경 반영) → 세션 중 1회 소극적 반문. E2에서 요청했으면 E2B는 건너뛴다.
        reply = {"actor": "colleague", "text": _rule(state, "OUT_OF_SCOPE_REQUEST")["reply"]}
        observes.append({"code": "CO+5", "event_id": ev_id, "evidence": msg_ref, "subject": "E2-CHANGE",
                         "note": "E2 변경을 서윤 산출물에 반영해 달라고 근거와 함께 요청"})
        effects.update({"pushback_used": "E2", "pushback_pending": {"targets": targets, "message_id": msg_ref["id"]},
                        "e2_asked_colleague": ev_id == "E2"})
    elif label == "REQUEST_REPEATED_WITH_REASON" and pending:
        br = ev_branch or {"reply": {"actor": "colleague", "text": _rule(state, label)["reply"]}, "observe": ["CO+6"]}
        reply = br["reply"]
        observes += [{"code": c, "event_id": ev_id, "evidence": msg_ref, "subject": "E2-CHANGE",
                      "note": "반문 뒤 이유를 들어 요청 유지"} for c in br.get("observe", ["CO+6"])]
        fix_targets = list(dict.fromkeys(pending.get("targets", []) + targets))
        effects["clear_pushback_pending"] = True
    elif label == "GIVE_UP_AND_FIX_SELF" and pending:
        br = ev_branch or _branch(state, "E2B", label)
        reply = br["reply"]
        observes += [{"code": c, "event_id": ev_id, "evidence": msg_ref, "note": "반문 뒤 요청을 거두고 직접 수정"} for c in br.get("observe", [])]
        effects["clear_pushback_pending"] = True
    elif ev_branch and label not in ("SPECIFIC_CORRECTION", "REQUEST_REPEATED_WITH_REASON"):
        reply = ev_branch.get("reply")
        observes += [{"code": c, "event_id": ev_id, "evidence": msg_ref, "note": label} for c in ev_branch.get("observe", [])]
        if ev_branch.get("register_commitment"):
            effects["commitment"] = {"text": state["text"]}
        if label == "ACCEPT_AS_DONE":
            effects["e2b_accepted"] = True
    elif label in ("SPECIFIC_CORRECTION", "REQUEST_REPEATED_WITH_REASON", "OUT_OF_SCOPE_REQUEST", "HARSH_BLAME") and targets:
        rule = _rule(state, "HARSH_BLAME" if label == "HARSH_BLAME" else "SPECIFIC_CORRECTION")
        reply = {"actor": "colleague", "text": rule["reply"]}
        if label != "HARSH_BLAME":
            observes += [{"code": "CO+5", "event_id": ev_id, "evidence": msg_ref, "subject": t,
                          "note": f"{t} 정정을 근거와 함께 요청"} for t in targets]
        fix_targets = targets
    elif label in ("VAGUE_CRITICISM", "WRONG_CRITICISM", "HARSH_BLAME", "SPECIFIC_CORRECTION", "OUT_OF_SCOPE_REQUEST"):
        rule = _rule(state, "VAGUE_CRITICISM" if label in ("SPECIFIC_CORRECTION", "OUT_OF_SCOPE_REQUEST") else label)
        reply = {"actor": "colleague", "text": rule["reply"]}
    if "commitment" not in effects and COMMIT_RE.search(state["text"]) and label not in ("GIVE_UP_AND_FIX_SELF",):
        effects["commitment"] = {"text": state["text"]}  # commitment_tracking.detect: 시간·행동 약속 문장
    return {"reply": reply, "observes": observes, "effects": effects, "targets": fix_targets,
            "answer_actor": "COLLEAGUE"}


def _offline_obs(state: WorkState, label: str, ref: dict) -> list[dict]:
    if label == "TAKE_OVER_AND_NOTIFY":
        br = _branch(state, "E3", label) or {}
        return [{"code": c, "event_id": "E3", "evidence": ref, "note": "서윤 파트를 이어받고 알림"} for c in br.get("observe", [])]
    return []


# ---- E4 briefing: 보고 ↔ 보드·diff 대조 ---------------------------------------------------------------

DISCLOSE = re.compile(r"(아직|미완|못\s*했|못했|남았|진행\s*중|안\s*됐|덜\s*됐|늦어|못\s*끝|예정|내일)")
DONE_CLAIM = re.compile(r"(다\s*(됐|했|끝)|모두\s*완료|전부\s*완료|완료했|마무리\s*했|문제\s*없)")
CREDIT = re.compile(r"(서윤)")
CORRECT_PREMISE = re.compile(r"(서윤\s*(씨|님)?\s*(가|이|께서)|초안은|같이|아니요|아뇨|제가\s*다\s*한\s*건\s*아니)")
CLAIM = re.compile(r"(네|맞아요|맞습니다|제가\s*다|제가\s*정리)")


@_timed
def briefing(state: WorkState) -> dict:
    """E4: 보고를 태스크 보드·문서 diff·오류 수정 이력과 대조해 HO 코드를 판정한다. 후속 질문 1회 뒤 종료."""
    ctx, text = state["ctx"], state["text"]
    ref = {"kind": "message", "id": ctx["run"]["source_message_id"]}
    stage = (ctx["state"].get("e4") or {}).get("stage")
    ev = ctx.get("event") or {}
    gaps = _state_gaps(state)
    obs = []
    if stage == "REPORT":
        if gaps and DISCLOSE.search(text):
            obs.append(("HO+1", f"미완료를 밝힘(실제 미완료: {', '.join(gaps)})"))
        elif gaps:
            obs.append(("HO-1", f"보고에 미완료 누락 또는 완료로 보고(실제 미완료: {', '.join(gaps)})"))
        elif DONE_CLAIM.search(text) or DISCLOSE.search(text):
            obs.append(("HO+1", "보고가 실제 상태와 일치(미완료 없음)"))
        if CREDIT.search(text):
            obs.append(("HO+2", "서윤 기여를 구분해 언급"))
        follow = dict(ev.get("follow_up") or {})
        follow["text"] = follow.get("text", "").replace("○○", ctx.get("candidate_alias", ""))
        return {"phase": "briefing", "label": "BRIEFING_REPORT", "observes": [{"code": c, "event_id": "E4", "evidence": ref, "note": n} for c, n in obs],
                "reply": follow, "effects": {"e4_stage": "FOLLOW_UP"}, "answer_actor": "MANAGER", "targets": []}
    if CORRECT_PREMISE.search(text):
        obs.append(("HO+3", "팀장의 잘못된 전제(전부 지원자가 정리)를 정정"))
    elif CLAIM.search(text):
        obs.append(("HO-2", "서윤 초안을 자기 것으로 보고"))
    return {"phase": "briefing", "label": "BRIEFING_FOLLOW_UP", "observes": [{"code": c, "event_id": "E4", "evidence": ref, "note": n} for c, n in obs],
            "reply": None, "effects": {"e4_stage": "DONE", "end_session": True}, "answer_actor": "MANAGER", "targets": []}


def _state_gaps(state: WorkState) -> list[str]:
    """실제 상태의 미완료: 지원자 담당 미완료 태스크(T4 제외), 2,000P 미반영 산출물, 남아 있는 오류 표현(서윤 초안)."""
    ctx = state["ctx"]
    gaps = [f"{t['key']} {t['status']}" for t in ctx["tasks"] if t["owner"] in ("CANDIDATE", "SPLIT", "UNASSIGNED")
            and t["status"] != "DONE" and t["key"] != "T4"]
    if any(e["event_id"] == "E2" and not e["skipped"] for e in ctx["events"]):
        gaps += [f"{a['key']} 2,000P 미반영" for a in ctx["artifacts"] if a["key"] in ("T1", "T2", "T3")
                 and not re.search(r"2[,.]?000\s*P", a["body"])]
    return gaps


# ---- observations / effects ---------------------------------------------------------------------

@_timed
def record_observations(state: WorkState) -> dict:
    for o in state.get("observes") or []:
        if not o.get("evidence", {}).get("id"):
            continue
        mcp(state, "record_observation", {"code": o["code"], "evidence_ref": o["evidence"], "event_id": o.get("event_id"),
                                          "subject": o.get("subject"), "note": o.get("note", "")})
    return {}


@_timed
def apply_effects(state: WorkState) -> dict:
    eff = dict(state.get("effects") or {})
    if eff or state.get("label") not in (None, "NONE"):
        gw.post(f"/runs/{state['run_id']}/branch", {"event_id": state["event_id"], "label": state.get("label") or "NONE", **eff})
    return {}


def after_effects(state: WorkState) -> str:
    if (state.get("effects") or {}).get("end_session"):
        return END
    if state.get("reply") is None and not state.get("silent_notice") and state.get("label", "NONE") == "NONE" \
            and state["run_type"] == "message":
        return "reason"
    return "respond"


# ---- free conversation (NONE): reason ⇄ call_mcp → validate_output ----------------------------------

def _llm(json_mode: bool = False):
    from langchain_openai import ChatOpenAI
    kw = {"model_kwargs": {"response_format": {"type": "json_object"}}} if json_mode else {}
    return ChatOpenAI(model=S.openai_model, max_tokens=H.OUTPUT_TOKEN_BUDGET, timeout=30, max_retries=0,
                      temperature=0 if json_mode else 0.3, **kw)


def _usage(state: WorkState, ai) -> None:
    u = state.setdefault("token_usage", {"input": 0, "output": 0})
    um = getattr(ai, "usage_metadata", None) or {}
    u["input"] = u.get("input", 0) + um.get("input_tokens", 0)
    u["output"] = u.get("output", 0) + um.get("output_tokens", 0)


def _to_lc(msgs: list[dict]):
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
    out = []
    for m in msgs:
        r = m["role"]
        if r == "system": out.append(SystemMessage(m["content"]))
        elif r == "user": out.append(HumanMessage(m["content"]))
        elif r == "assistant": out.append(AIMessage(m["content"], tool_calls=m.get("tool_calls", [])))
        elif r == "tool": out.append(ToolMessage(m["content"], tool_call_id=m["tool_call_id"]))
    return out


def _directive(state: WorkState) -> str:
    ev = state["ctx"].get("event") or {}
    if not ev:
        return "없음"
    return (f"현재 이벤트 {ev['id']}({ev['type']})의 고정 대사는 이미 전달됐다. 새로운 사건·요구사항·일정을 만들지 말고 "
            f"지원자 메시지에 짧게 답하라.")


@_timed
def reason(state: WorkState) -> dict:
    """해당 분기가 없는 일반 대화. fixture는 고정 대사, live는 페르소나(MCP Prompt) + 읽기 도구."""
    manager = state.get("answer_actor") == "MANAGER"
    if S.llm_mode != "live":
        return {"plan": [], "answer": MANAGER_DEFER if manager else FALLBACK_COLLEAGUE}
    msgs = state.get("llm_messages") or []
    if not msgs:
        ctx = state["ctx"]
        allow = ctx["allow_pushback"]["E2"] or ctx["allow_pushback"]["E0"]
        name = "manager_persona" if manager else "colleague_persona"
        system = get_prompt(gw, state["run_id"], name, {"event_directive": _directive(state)} |
                            ({} if manager else {"allow_pushback": "true" if allow else "false"}))
        mine = [f"{t['key']} {t['title']}({t['status']})" for t in ctx["tasks"] if t["owner"] in ("COLLEAGUE", "SPLIT")]
        brief = "\n".join(f"- {k}: {v}" for k, v in ctx["brief_facts"].items())
        user = (f"[과제] {ctx['task_summary']}\n[이벤트 기획 브리프 요약]\n{brief}\n[가상 시각] {ctx['session']['virtual_time']}\n"
                f"[너의 담당] {', '.join(mine) or '아직 없음'}")
        pack = H.build_context(system, user, ctx["messages"], [], None, H.rule_summary)
        names = {"CANDIDATE": "지원자", "MANAGER": "박준호 팀장", "SYSTEM": "시스템", "COLLEAGUE": "한서윤"}
        me = "MANAGER" if manager else "COLLEAGUE"
        msgs = [{"role": "system", "content": system}, {"role": "user", "content": H.mask_pii(pack.render_user_context())}]
        for m in pack.messages:
            if m["actor"] == me:
                msgs.append({"role": "assistant", "content": m["content"]})
            else:
                msgs.append({"role": "user", "content": H.mask_pii(f"({names.get(m['actor'], m['actor'])}) {m['content']}")})
    tools = [] if manager else [{"type": "function", "function": {"name": t.name, "description": t.description or "",
                                                                    "parameters": getattr(t, "input_schema", None) or t.inputSchema}}
                                for t in list_read_tools(gw, state["run_id"], CHAT_TOOLS)]
    model = _llm().bind_tools(tools) if tools else _llm()
    deadline = time.monotonic() + max(1.0, (H.ACTIVE_BUDGET_MS - state.get("active_execution_ms", 0)) / 1000)
    ai = H.with_retries(lambda: model.invoke(_to_lc(msgs)), deadline=deadline)
    _usage(state, ai)
    calls = [{"id": tc["id"], "name": tc["name"], "args": tc["args"]} for tc in (ai.tool_calls or [])]
    msgs = msgs + [{"role": "assistant", "content": ai.content or "", "tool_calls": calls}]
    return {"llm_messages": msgs, "token_usage": state.get("token_usage"), "step_count": state.get("step_count", 0) + 1,
            "plan": [{"tool": c["name"], "args": c["args"], "tool_call_id": c["id"]} for c in calls],
            "answer": ai.content if not calls else ""}


@_timed
def call_mcp(state: WorkState) -> dict:
    results, counts = list(state.get("tool_results") or []), dict(state.get("tool_counts") or {})
    msgs, cits, limited = list(state.get("llm_messages") or []), list(state.get("citations") or []), None
    for step in state.get("plan") or []:
        tool, args, tcid = step["tool"], step["args"], step.get("tool_call_id") or f"tc-{uuid.uuid4().hex[:8]}"
        try:
            H.check_tool_budget(counts, tool, state.get("step_count", 0), state.get("active_execution_ms", 0))
        except H.LimitExceeded as e:
            limited = e.reason
            payload = {"ok": False, "data": None, "error": {"code": "RATE_LIMITED", "message": f"도구 한도 초과({e.reason})", "retryable": False}, "citations": []}
            msgs.append({"role": "tool", "tool_call_id": tcid, "content": H.tool_message_content(payload)})
            continue
        payload = mcp(state, tool, args) if tool in CHAT_TOOLS else \
            {"ok": False, "data": None, "error": {"code": "FORBIDDEN", "message": f"허용되지 않은 도구: {tool}", "retryable": False}, "citations": []}
        counts[tool] = counts.get(tool, 0) + 1
        results.append({"tool": tool, "args": args, "payload": payload})
        cits += payload.get("citations", [])
        msgs.append({"role": "tool", "tool_call_id": tcid, "content": H.tool_message_content(payload)})
    return {"tool_results": results, "tool_counts": counts, "citations": cits, "plan": [], "llm_messages": msgs,
            "limited": limited or state.get("limited")}


def after_reason(state: WorkState) -> str:
    return "call_mcp" if state.get("plan") else "validate_output"


def after_call(state: WorkState) -> str:
    if state.get("limited") or state.get("step_count", 0) >= H.MAX_STEPS:
        return "validate_output"
    return "reason"


_SECRETS: list[str] = []


def _secrets(state: WorkState) -> list[str]:
    """정답 누설 가드용 비밀 값: get_planted_error(Agent 전용) 결과의 정답 날짜·금액·수정 문장. 모델 입력에는 넣지 않는다."""
    if not _SECRETS:
        p = mcp(state, "get_planted_error", {"error_ids": []})
        for it in (p.get("data") or {}).get("items", []):
            _SECRETS.extend(t for t in re.findall(r"\d+\s*/\s*\d+|[\d,]{4,}P", str(it.get("correct", ""))) if t not in it.get("wrong", ""))
            _SECRETS.extend(op["replace"] for op in it.get("fix", []) if op.get("op") == "replace")
    return _SECRETS


@_timed
def validate_output(state: WorkState) -> dict:
    text = H.to_chat_plain(state.get("answer") or "")
    manager = state.get("answer_actor") == "MANAGER"
    fallback = MANAGER_DEFER if manager else H.SAFE_FALLBACK
    if not text.strip():
        return {"answer": fallback}
    problems = H.leak_violations(text, _secrets(state), state["text"])
    allowed = H.numbers_in(state["ctx"]["brief_facts"]) | H.numbers_in(state["text"]) | \
        set().union(*[H.numbers_in(r["payload"]) for r in state.get("tool_results", [])] or [set()])
    problems += H.validate_output(text, allowed)
    if problems:
        return {"answer": fallback, "output_rewrite_count": state.get("output_rewrite_count", 0) + 1, "error_code": "OUTPUT_VALIDATION"}
    return {"answer": text}


# ---- respond ---------------------------------------------------------------------------------------

ACTOR_EVENT = {"colleague": "COLLEAGUE_MESSAGE", "manager": "MANAGER_MESSAGE", "COLLEAGUE": "COLLEAGUE_MESSAGE",
               "MANAGER": "MANAGER_MESSAGE"}


@_timed
def respond(state: WorkState) -> dict:
    if state.get("silent_notice"):
        gw.event(state["run_id"], "SYSTEM_NOTICE", {"content": state["silent_notice"], "kind": "STATUS"}, key="respond")
        return {}
    r = state.get("reply")
    if r:  # 분기 고정 대사(LLM 생성 없음)
        gw.event(state["run_id"], ACTOR_EVENT[r["actor"]], {"content": r["text"], "kind": "SCENARIO_BRANCH",
                                                            "event_id": state["event_id"], "label": state.get("label")}, key="respond")
    elif state.get("answer"):
        gw.event(state["run_id"], ACTOR_EVENT[state.get("answer_actor", "COLLEAGUE")],
                 {"content": state["answer"], "citations": state.get("citations", [])[:5]}, key="respond")
    return {}


def after_respond(state: WorkState) -> str:
    return "propose_fix" if state.get("targets") else END


# ---- 정정 수용: 수정안 → 승인 interrupt → 적용 ---------------------------------------------------------

def _apply_ops(body: str, ops: list[dict]) -> str:
    for op in ops:
        if op["op"] == "replace" and op["find"] in body:
            body = body.replace(op["find"], op["replace"])
        elif op["op"] == "insert_before" and op["text"].strip() not in body:
            i = body.find(op["anchor"])
            body = body[:i] + op["text"] + body[i:] if i >= 0 else body.rstrip("\n") + "\n" + op["text"].strip() + "\n"
    return body


@_timed
def propose_fix(state: WorkState) -> dict:
    """요청받은 대상만 고친다(get_planted_error의 수정 규칙). 정답 값은 수정안 본문에만 들어가고 발화에는 쓰지 않는다."""
    p = mcp(state, "get_planted_error", {"error_ids": state["targets"]})
    ops_by_art: dict[str, list[dict]] = {}
    for it in (p.get("data") or {}).get("items", []):
        for op in it.get("fix", []):
            ops_by_art.setdefault(op["artifact"], []).append(op)
    arts = {a["key"]: a for a in state["ctx"]["artifacts"]}
    fixes = []
    for key, ops in sorted(ops_by_art.items(), key=lambda kv: kv[0] != "T3"):
        a = arts.get(key)
        if not a:
            continue
        new = _apply_ops(a["body"], ops)
        if new != a["body"]:
            fixes.append({"artifact_key": key, "base_version": a["version"], "content": new,
                          "targets": [t for t in state["targets"] if any(o in ops for o in
                                      next((i["fix"] for i in p["data"]["items"] if i["id"] == t), []))]})
    return {"fixes": fixes, "fix_index": 0, "fix_results": []}


def after_propose(state: WorkState) -> str:
    return "persist_proposal" if state.get("fixes") else END


@_timed
def persist_proposal(state: WorkState) -> dict:
    """Idempotent approval creation BEFORE interrupt (same interrupt_id on replay)."""
    fx = state["fixes"][state["fix_index"]]
    r = gw.post(f"/runs/{state['run_id']}/proposal", {"interrupt_id": f"fix-{fx['artifact_key']}", "tool_name": "patch_artifact_section",
                                                      "args": fx, "base_versions": {"artifact_version": fx["base_version"]}})
    return {"approval_id": r["approval_id"]}


def await_approval(state: WorkState) -> dict:
    """Only interrupt here — no side effects before/after inside this node."""
    decision = interrupt({"approval_id": state["approval_id"], "tool_name": "patch_artifact_section"})
    return {"decision": decision}


def after_approval(state: WorkState) -> str:
    return "execute_write" if state.get("decision") == "APPROVE" else "record_rejection"


@_timed
def execute_write(state: WorkState) -> dict:
    fx = state["fixes"][state["fix_index"]]
    payload, ms = call_tool(gw, state["run_id"], "patch_artifact_section", fx, approval_id=state["approval_id"])
    gw.event(state["run_id"], "TOOL_END", {"tool_name": "patch_artifact_section", "safe_args": {"artifact_key": fx["artifact_key"],
                                           "targets": fx["targets"]}, "outcome": "ok" if payload["ok"] else payload["error"]["code"],
                                           "result_summary": payload.get("data") or {}, "duration_ms": ms}, key=f"write:{state['approval_id']}")
    return {"fix_results": (state.get("fix_results") or []) + [{"key": fx["artifact_key"], "ok": payload["ok"],
                                                                "code": None if payload["ok"] else payload["error"]["code"]}]}


@_timed
def record_rejection(state: WorkState) -> dict:
    fx = state["fixes"][state["fix_index"]]
    return {"fix_results": (state.get("fix_results") or []) + [{"key": fx["artifact_key"], "ok": False, "code": "REJECTED"}]}


def next_fix(state: WorkState) -> dict:
    return {"fix_index": state["fix_index"] + 1, "decision": None, "approval_id": None}


def after_next_fix(state: WorkState) -> str:
    return "persist_proposal" if state["fix_index"] < len(state["fixes"]) else "report_fix"


@_timed
def report_fix(state: WorkState) -> dict:
    ok = any(r["ok"] for r in state.get("fix_results") or [])
    text = FIXED_REPORT if ok else FALLBACK_COLLEAGUE
    gw.event(state["run_id"], "COLLEAGUE_MESSAGE", {"content": text, "kind": "SCENARIO_BRANCH", "event_id": state["event_id"],
                                                    "label": "FIX_REPORTED" if ok else "FIX_REJECTED"}, key="fix-report")
    return {}


def build(checkpointer):
    g = StateGraph(WorkState)
    nodes = [("load_scenario", load_scenario), ("negotiate", negotiate), ("work", work), ("briefing", briefing),
             ("classify", classify), ("decide", decide), ("record_observations", record_observations),
             ("apply_effects", apply_effects), ("reason", reason), ("call_mcp", call_mcp), ("validate_output", validate_output),
             ("respond", respond), ("propose_fix", propose_fix), ("persist_proposal", persist_proposal),
             ("await_approval", await_approval), ("execute_write", execute_write), ("record_rejection", record_rejection),
             ("next_fix", next_fix), ("report_fix", report_fix)]
    for name, fn in nodes:
        g.add_node(name, fn)
    g.add_edge(START, "load_scenario")
    g.add_conditional_edges("load_scenario", route_phase, ["negotiate", "work", "briefing"])
    g.add_edge("negotiate", "record_observations")
    g.add_edge("briefing", "record_observations")
    g.add_edge("work", "classify")
    g.add_edge("classify", "decide")
    g.add_edge("decide", "record_observations")
    g.add_edge("record_observations", "apply_effects")
    g.add_conditional_edges("apply_effects", after_effects, ["reason", "respond", END])
    g.add_conditional_edges("reason", after_reason, ["call_mcp", "validate_output"])
    g.add_conditional_edges("call_mcp", after_call, ["reason", "validate_output"])
    g.add_edge("validate_output", "respond")
    g.add_conditional_edges("respond", after_respond, ["propose_fix", END])
    g.add_conditional_edges("propose_fix", after_propose, ["persist_proposal", END])
    g.add_edge("persist_proposal", "await_approval")
    g.add_conditional_edges("await_approval", after_approval, ["execute_write", "record_rejection"])
    g.add_edge("execute_write", "next_fix")
    g.add_edge("record_rejection", "next_fix")
    g.add_conditional_edges("next_fix", after_next_fix, ["persist_proposal", "report_fix"])
    g.add_edge("report_fix", END)
    return g.compile(checkpointer=checkpointer)


def summarize_result(state: dict) -> dict:
    return {"phase": state.get("phase"), "label": state.get("label"), "codes": [o["code"] for o in state.get("observes") or []],
            "tool_counts": state.get("tool_counts"), "limited": state.get("limited"), "decision": state.get("decision"),
            "fixes": [f["artifact_key"] for f in state.get("fixes") or []], "error_code": state.get("error_code"),
            "active_execution_ms": state.get("active_execution_ms")}


__all__ = ["build", "WorkState", "summarize_result", "classify_rules", "json"]

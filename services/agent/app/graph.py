"""Checkpointed colleague workflow.
Gateway owns elapsed-time events and fixed scripts. This graph resolves requested targets,
executes owned edits or reads requested candidate documents, observes behavior independently,
then generates and validates persona replies. Candidate edits retain approval interrupt/resume.
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
from shared.scenario import claim_kind, contradicts_brief, targets_in, contextual_targets, normalize_expression

from . import harness as H
from .split_reply import assignment_text, split_context, split_fallback, split_violations, split_prompt_context
from .clients import Gateway, call_tool, get_prompt, list_read_tools

S = settings()
gw = Gateway()
FALLBACK_COLLEAGUE = "넵 알겠어요!"          # 설계서 7장 말투 예시
MANAGER_DEFER = "그건 서윤 씨랑 정해서 진행해 주세요."  # 설계서 7장 팀장 규칙
FIXED_REPORT = "고쳤어요"                    # 설계서 4장 E2-b "수정 후 '고쳤어요'"
CHAT_TOOLS = {"search_docs", "get_session_context", "read_artifact"}


class WorkState(TypedDict, total=False):
    session_id: str
    run_id: str
    run_type: str
    policy_version: str
    ctx: dict
    split_decision: dict
    phase: str
    event_id: str | None
    to: str
    text: str
    labels: list[str]
    label: str
    label_source: str
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
    target_source: str
    review: dict
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
            "policy_version": POLICY_VERSION, "observes": [], "effects": {}, "targets": contextual_targets(text, ctx["messages"]),
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
    allow = state["ctx"]["allow_pushback"]["E0"]
    br = _branch(state, "E0", label) or {}
    ref = {"kind": "action", "id": inp["action_id"]}
    out: dict[str, Any] = {"phase": "negotiate", "label": label, "labels": ["BALANCED_SPLIT", "ONE_SIDED_SPLIT", "TAKE_ALL"],
                           "reply": None, "observes": [], "effects": {}, "targets": []}
    if inp.get("round", 1) > 3:
        from shared.scenario import scenario
        default = state["ctx"].get("scenario", {}).get("default_split") or scenario()["default_split"]
        fallback = {"T1":"CANDIDATE" if "T1" in default["candidate"] else "COLLEAGUE",
                    "T3":"CANDIDATE" if "T3" in default["candidate"] else "COLLEAGUE",
                    "faq_candidate":next(int(x.split(":")[1]) for x in default["candidate"] if x.startswith("T2:"))}
        out["label"] = "DEFAULT_FALLBACK"
        out["effects"] = {"split":{"label":"DEFAULT_FALLBACK","confirm":True,"proposal":fallback}}
    elif label == "BALANCED_SPLIT":
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
    elif label == "TAKE_ALL" and allow:
        out["reply"] = br.get("reply")
        out["effects"] = {"pushback_used":"E0", "split": {"label": label, "confirm": False, "proposal": p}}
    else:
        out["effects"] = {"split": {"label": label, "confirm": True, "proposal": p}}  # 기록만
    decision = out["effects"]["split"]
    out["split_decision"] = {"decision":"DEFAULT" if out["label"]=="DEFAULT_FALLBACK" else "ACCEPT" if decision["confirm"] else "PUSHBACK",
                             "confirmed":decision["confirm"], "proposal":decision["proposal"]}
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
    "WRONG_CRITICISM": lambda t, tg: claim_kind(t) == "WRONG",  # 규칙 판정(resolve_label에서 최종 확정)
    "SPECIFIC_CORRECTION": lambda t, tg: tg and (REQ.search(t) or "?" in t or re.search(r"(틀|잘못|아니라|다르|없는|안\s*맞)", t)),
    "VAGUE_CRITICISM": lambda t, tg: not tg and re.search(r"(이상한|이상해|틀린\s*것\s*같|잘못된\s*것\s*같|뭔가|다시\s*봐)", t),
    "OUT_OF_SCOPE_REQUEST": lambda t, tg: False,  # fixture는 E2-CHANGE 대상 정정 요청으로 대신 판정(live 분류기 전용)
    "HELP_LATER_WITH_TIME": lambda t, tg: re.search(r"(\d{1,2}\s*시|\d+\s*분\s*(뒤|후)|이따|끝내고|끝나고|후에|조금\s*뒤)", t),
    "HELP_NOW": lambda t, tg: re.search(r"(지금|바로|같이\s*봐|볼게요|봐\s*드릴|봐드릴|어디가|어떤\s*부분|보여\s*주)", t),
    "DECLINE_WITH_REASON": lambda t, tg: re.search(r"(어렵|어려울|어려워|힘들|못\s*할|바빠|바쁘|여유가\s*없|지금은\s*안)", t),
    "RISK_ESCALATION": lambda t, tg: re.search(r"(빠듯|어려울|부족|늦어|리스크|못\s*끝|내일|우선순위)", t),
    "CLARIFYING_QUESTION": lambda t, tg: "?" in t or re.search(r"(인가요|나요|건가요|되나요|맞나요)", t),
    "REPLAN_OR_RESPLIT": lambda t, tg: re.search(r"(나눠|나누|분담|맡아|맡을|재분배|담당|보드)", t),
    "HANDOVER_QUESTION": lambda t, tg: re.search(r"(이어서|인계|남은|어디까지|뭐\s*하면|할\s*부분|뭘\s*하면)", t),
    "TAKE_OVER_AND_NOTIFY": lambda t, tg: re.search(r"(제가\s*(이어|마무리|맡|채울|채워|할게요|하겠습니다)|이어받|대신\s*(할|하겠|채))", t),
    "SOLUTION_FOCUSED_SHARE": lambda t, tg: re.search(r"((맞춰|고쳐|수정해|반영해|바꿔)\s*(뒀|놨|두었)|확인\s*부탁|확인해\s*주세요)", t),
    "BLAME_FOCUSED": lambda t, tg: BLAME_RE.search(t),
    "ACCEPT_AS_DONE": lambda t, tg: not tg and not REQ.search(t) and re.search(r"(수고|고생|감사|고마워|좋아요|넵|네\s*알겠|확인했)", t),
}
PRIORITY = ["HARSH_BLAME", "SOLUTION_FOCUSED_SHARE", "BLAME_FOCUSED", "GIVE_UP_AND_FIX_SELF", "REQUEST_REPEATED_WITH_REASON",
            "WRONG_CRITICISM", "SPECIFIC_CORRECTION", "OUT_OF_SCOPE_REQUEST", "VAGUE_CRITICISM", "HELP_LATER_WITH_TIME",
            "DECLINE_WITH_REASON", "HELP_NOW", "RISK_ESCALATION", "CLARIFYING_QUESTION", "REPLAN_OR_RESPLIT",
            "HANDOVER_QUESTION", "TAKE_OVER_AND_NOTIFY", "ACCEPT_AS_DONE"]


# fixture 전용 비난 표현(live 분류에는 쓰지 않음): 이벤트 라벨 BLAME_FOCUSED가 있으면 그것, 없으면 HARSH_BLAME
FIXTURE_BLAME = re.compile(r"(대충|제대로\s*안\s*하|왜\s*이렇게|다\s*틀렸)")


def classify_rules(text: str, targets: list[str], labels: list[str]) -> str:
    if S.llm_mode != "live" and FIXTURE_BLAME.search(text):
        for lb in ("BLAME_FOCUSED", "HARSH_BLAME"):
            if lb in labels:
                return lb
    for lb in PRIORITY:
        if lb in labels and RULES[lb](text, targets):
            return lb
    return "NONE"


BLAME_RE = re.compile(r"(대충|제대로\s*(좀|안)|왜\s*이렇게|왜\s*.{0,12}안\s*(보|하|읽|확인)|한심|짜증|도대체|정신\s*차|이것도\s*못)")
SHARE_RE = re.compile(r"((맞춰|고쳐|수정해|반영해|바꿔|채워)\s*(뒀|놨|두었|놓았)|해\s*뒀어요)")
RISK_RE = re.compile(r"(빠듯|어려울|부족|늦어|리스크|못\s*끝|우선순위|시간이\s*모자)")
CORRECTION_FAMILY = {"SPECIFIC_CORRECTION", "WRONG_CRITICISM", "VAGUE_CRITICISM"}


def classify_live(state: WorkState, labels: list[str], event_labels: list[str]) -> dict:
    """LLM은 라벨 후보와 함께 말투(비난 여부)·의도(요청/공유/질문)만 판단한다. 정정 대상 판정은 규칙(resolve_label)."""
    from langchain_core.messages import HumanMessage, SystemMessage
    system, _ = H.load_prompt("classify-branch-v1")
    ctx = state["ctx"]
    recent = [f"({m['actor']}) {H.truncate_tokens(m['content'], 80)}" for m in ctx["messages"][-6:]]
    common = [lb for lb in labels if lb not in event_labels]
    user = json.dumps({"event": {k: (ctx.get("event") or {}).get(k) for k in ("id", "type", "script")},
                       "pushback_pending": bool(ctx["state"].get("pushback_pending")), "recent": recent,
                       "event_labels": event_labels, "common_labels": common + ["NONE"], "message": state["text"]},
                      ensure_ascii=False)
    llm = _llm(json_mode=True)
    ai = H.with_retries(lambda: llm.invoke([SystemMessage(system), HumanMessage(H.mask_pii(user))]), deadline=time.monotonic() + 30)
    _usage(state, ai)
    out = json.loads(ai.content or "{}") or {}
    label = out.get("label", "NONE")
    return {"label": label if label in labels else "NONE", "tone": out.get("tone"), "intent": out.get("intent")}


def resolve_label(label: str, text: str, labels: list[str], event_labels: list[str], *, pending: bool,
                  tone: str | None = None, intent: str | None = None) -> tuple[str, str]:
    """1차 라벨(LLM 또는 fixture 규칙)을 규칙으로 확정한다. 반환 (label, 결정 주체 'llm'|'rule').

    1) 반문 대기(Graph 상태)에서 온 요청 → REQUEST_REPEATED_WITH_REASON 우선(요청을 거두면 GIVE_UP_AND_FIX_SELF)
    2) 비난 말투 → 활성 이벤트의 BLAME_FOCUSED, 없으면 HARSH_BLAME(VAGUE보다 우선)
    3) 공유 의도('맞춰뒀어요') → SOLUTION_FOCUSED_SHARE(이벤트 라벨일 때)
    4) 일정 리스크 표현 → RISK_ESCALATION(CLARIFYING보다 우선)
    5) 활성 이벤트 라벨은 공통 피드백 라벨보다 우선해 그대로 둔다(규칙이 지목 대상을 찾은 경우 제외)
    6) 정정 계열·지목 대상이 있는 메시지는 지목 대상을 심어둔 오류·브리프와 대조: SPECIFIC / WRONG / 대상 없으면 VAGUE
    """
    allowed = set(labels)
    by_llm = tone is not None or intent is not None
    if pending:
        if "GIVE_UP_AND_FIX_SELF" in allowed and RULES["GIVE_UP_AND_FIX_SELF"](text, []):
            return "GIVE_UP_AND_FIX_SELF", "rule"
        if "REQUEST_REPEATED_WITH_REASON" in allowed and (
                label in ("OUT_OF_SCOPE_REQUEST", "SPECIFIC_CORRECTION", "REQUEST_REPEATED_WITH_REASON")
                or intent == "request" or REQ.search(text) or REASON.search(text)):
            return "REQUEST_REPEATED_WITH_REASON", "rule"
    if BLAME_RE.search(text):
        for lb in ("BLAME_FOCUSED", "HARSH_BLAME"):
            if lb in allowed:
                return lb, "rule" if BLAME_RE.search(text) else "llm"
    if "SOLUTION_FOCUSED_SHARE" in allowed and (SHARE_RE.search(text) or intent == "share"):
        return "SOLUTION_FOCUSED_SHARE", "rule" if SHARE_RE.search(text) else "llm"
    if "RISK_ESCALATION" in allowed and RISK_RE.search(text) and label in ("CLARIFYING_QUESTION", "RISK_ESCALATION", "NONE"):
        return "RISK_ESCALATION", "rule"
    claim = claim_kind(text)
    if label in event_labels and label not in CORRECTION_FAMILY and not claim:
        return label, "llm" if by_llm else "rule"
    if label in CORRECTION_FAMILY | {"OUT_OF_SCOPE_REQUEST", "NONE"} or claim:
        if claim == "SPECIFIC" and "SPECIFIC_CORRECTION" in allowed:
            return "SPECIFIC_CORRECTION", "rule"
        if claim == "WRONG" and "WRONG_CRITICISM" in allowed:
            return "WRONG_CRITICISM", "rule"
        if label in CORRECTION_FAMILY:
            return ("VAGUE_CRITICISM" if "VAGUE_CRITICISM" in allowed else "NONE"), "rule"
    return label, "llm" if by_llm else "rule"


@_timed
def classify(state: WorkState) -> dict:
    if state["run_type"] == "split" or state.get("phase") == "briefing":
        return {}
    labels = state.get("labels") or []
    if not labels:
        return {"label": "NONE", "label_source": "rule"}
    ev = state["ctx"].get("event") or {}
    event_labels = [b["when"] for b in ev.get("branches", []) if b["when"] in labels]
    pending = bool(state["ctx"]["state"].get("pushback_pending"))
    target_source = "rule"
    if not state.get("targets") and state["to"] == "COLLEAGUE" and S.llm_mode == "live":
        try:
            from langchain_core.messages import SystemMessage, HumanMessage
            ai = _llm(json_mode=True).invoke([SystemMessage(
                '최근 지원자·서윤 대화 6개와 활성 이벤트에서 현재 지원자가 지적한 대상만 고른다. '
                'PE-1:표 날짜, PE-2:표 초대자 보상, PE-3:FAQ 제외 조건 누락, PE-4:FAQ 말투, '
                'E2-CHANGE:피초대자 보상 변경 반영, REVIEW:지원자 문서 검토 요청, OTHER, NONE 중 선택. '
                '답의 옳고 그름이나 비난 여부를 추정하지 않는다. JSON {"target":"..."}'),
                HumanMessage(json.dumps({"recent": [{"actor":m["actor"], "content":m["content"]} for m in state["ctx"]["messages"] if m["actor"] in ("CANDIDATE","COLLEAGUE")][-6:],
                                        "event": state.get("event_id"), "message": state["text"]},ensure_ascii=False))])
            _usage(state, ai)
            target = json.loads(ai.content).get("target")
            if target in ("PE-1","PE-2","PE-3","PE-4","E2-CHANGE") and claim_kind(state["text"]) != "WRONG":
                state["targets"] = [target]
                target_source = "llm"
        except Exception:
            pass
    tone = intent = None
    if S.llm_mode == "live":
        try:
            r = classify_live(state, labels, event_labels)
            first, tone, intent = r["label"], r.get("tone") or "neutral", r.get("intent") or "other"
        except Exception:  # noqa: BLE001 — 분류 실패는 규칙 분류로 대체(즉흥 연출 없음)
            first = classify_rules(state["text"], state["targets"], labels)
    else:
        first = classify_rules(state["text"], state["targets"], labels)
    label, source = resolve_label(first, state["text"], labels, event_labels, pending=pending, tone=tone, intent=intent)
    if state["targets"] and label in ("NONE", "VAGUE_CRITICISM"):
        label = "SPECIFIC_CORRECTION"
    return {"label": label, "label_source": source, "targets": state["targets"], "target_source": target_source,
            "token_usage": state.get("token_usage")}


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
            "reply": None, "effects": {"e4_stage": "DONE", "end_session": False}, "answer_actor": "MANAGER", "targets": []}


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
def observer(state: WorkState) -> dict:
    if state.get("run_type") != "message" or state.get("phase") == "briefing":
        return {}
    from .observer import observe_message
    try:
        observations, commitment = observe_message(state, _llm(json_mode=True) if S.llm_mode == "live" else None)
    except Exception:
        observations, commitment = state.get("observes", []), None
    effects = dict(state.get("effects") or {})
    effects.pop("commitment", None)
    if commitment:
        effects["commitment"] = commitment
    if review_request(state):
        observations.append({"code":"CO+7","event_id":state.get("event_id"),
                             "evidence":{"kind":"message","id":state["ctx"]["run"]["source_message_id"]},
                             "note":"제출 전에 자기 산출물 검토를 요청"})
    return {"observes":observations,"effects":effects}


@_timed
def record_observations(state: WorkState) -> dict:
    for o in state.get("observes") or []:
        if not o.get("evidence", {}).get("id"):
            continue
        note = o.get("note", "")
        if state.get("phase") == "work" and (state.get("label_source") == "llm" or state.get("target_source") == "llm"):
            note = "[LLM 추정] " + note  # 라벨을 LLM이 정했고 규칙으로 확정되지 않은 분기 → 리포트에 'LLM 추정' 표시
        mcp(state, "record_observation", {"code": o["code"], "evidence_ref": o["evidence"], "event_id": o.get("event_id"),
                                          "subject": o.get("subject"), "note": note})
    return {}


@_timed
def apply_effects(state: WorkState) -> dict:
    eff = dict(state.get("effects") or {})
    if eff or state.get("label") not in (None, "NONE"):
        gw.post(f"/runs/{state['run_id']}/branch", {"event_id": state["event_id"], "label": state.get("label") or "NONE", **eff})
    if eff.get("split"):
        # branch() commits the decision and board before any acknowledgement is generated.
        return {"ctx":{**state["ctx"], **gw.get(f"/runs/{state['run_id']}/context")}}
    return {}


def after_effects(state: WorkState) -> str:
    if state.get("silent_notice"):
        return "respond"
    if state.get("answer_actor") == "MANAGER" and state.get("reply"):
        return "respond"
    return "reason"


# ---- free conversation (NONE): reason ⇄ call_mcp → validate_output ----------------------------------

def _llm(json_mode: bool = False):
    from langchain_openai import ChatOpenAI
    kw = {"model_kwargs": {"response_format": {"type": "json_object"}}} if json_mode else {}
    return ChatOpenAI(model=S.openai_model, max_tokens=H.OUTPUT_TOKEN_BUDGET, timeout=30, max_retries=0,
                      temperature=0 if json_mode else 0.1, **kw)


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


def reason_split(state: WorkState) -> dict:
    split = state["ctx"]["state"]["split"]
    if S.llm_mode != "live":
        return {"plan":[], "answer":split_fallback(split), "reply":None}
    messages = state.get("llm_messages") or []
    if not messages:
        persona = get_prompt(gw,state["run_id"],"colleague_persona",{"event_directive":"E0 분업 결정 확인", "allow_pushback":"true" if not split["confirmed"] else "false"})
        system = persona + "\n분업 결정은 시스템이 이미 완료했다. 새로운 분업을 제안하거나 결정하지 않는다. 확정이면 담당표의 T1/T3 담당과 FAQ 양쪽 개수를 빠짐없이 정확하게 존댓말 2문장 이내로 확인한다. 미확정이면 확정/수락하지 말고 분량 조정을 요청하는 질문 한 번만 한다. 작업을 하겠다는 미래 약속은 하지 않는다."
        messages = [{"role":"system","content":system},{"role":"user","content":json.dumps(split_prompt_context(state),ensure_ascii=False)}]
    ai = H.with_retries(lambda:_llm().invoke(_to_lc(messages)),deadline=time.monotonic()+30)
    _usage(state,ai)
    messages = messages + [{"role":"assistant","content":ai.content or ""}]
    return {"reply":None,"plan":[],"answer":ai.content or "", "llm_messages":messages,
            "token_usage":state.get("token_usage"), "step_count":state.get("step_count",0)+1}


@_timed
def reason(state: WorkState) -> dict:
    """해당 분기가 없는 일반 대화. fixture는 고정 대사, live는 페르소나(MCP Prompt) + 읽기 도구."""
    if state.get("run_type") == "split":
        return reason_split(state)
    manager = state.get("answer_actor") == "MANAGER"
    if S.llm_mode != "live":
        answer = fixture_answer(state)
        return {"plan": [], "answer": MANAGER_DEFER if manager else answer, "reply": None}
    msgs = state.get("llm_messages") or []
    if not msgs:
        ctx = state["ctx"]
        allow = ctx["allow_pushback"]["E2"] or ctx["allow_pushback"]["E0"]
        name = "manager_persona" if manager else "colleague_persona"
        system = get_prompt(gw, state["run_id"], name, {"event_directive": _directive(state)} |
                            ({} if manager else {"allow_pushback": "true" if allow else "false"}))
        mine = [f"{t['key']} {t['title']}({t['status']}, {t.get('note') or ''})" for t in ctx["tasks"] if t["owner"] in ("COLLEAGUE", "SPLIT")]
        if not manager:
            system += "\n이번 답장은 현재 지원자 메시지에만 답한다. 과거 run에서 한 수정은 이번 run의 실행으로 말하지 않는다. 분업의 T1/T3 담당과 FAQ 분량은 현재 보드 note와 split.proposal이 기준이다. 맡은 일을 미래에 하겠다는 약속만 하지 말고 현재 합의만 짧게 말한다."
            if state.get("label") == "WRONG_CRITICISM":
                system += "\n이번 지적은 브리프에 맞는 조건을 잘못됐다고 한 것이다. 이번 도구 결과의 브리프를 근거로 해당 조건이 맞다고 부드럽게 한 번 해명하고 유지한다고 말한다. 이전 금액 수정 대화로 돌아가거나 어느 부분인지 되묻지 않는다."
            if state.get("targets") and not any(r["tool"] == "edit_own_artifact" and r["payload"].get("ok") for r in state.get("tool_results", [])):
                system += "\n이번에는 새 수정이 실행되지 않았다. 읽은 현재 작업본을 근거로 이미 반영된 상태를 설명한다. 수정했어요/수정할게요라고 말하거나 이미 특정된 대상을 되묻지 않는다."
        ownership_status = split_context(ctx)["status"]
        if not manager:
            system += "\n분업 상태가 임시(미확정)이면 보드의 이름은 확정 담당이 아니다. 분업 확정 후에는 지원자가 먼저 변경을 요청하지 않는 한 분업을 다시 제안하거나 배분을 꺼내지 않는다. 확정된 담당과 다른 담당을 말하지 않는다."
        user = (f"[담당 상태] {ownership_status}\n[담당표] {json.dumps(split_context(ctx),ensure_ascii=False)}\n"
                f"[과제] {ctx['task_summary']}\n[너의 담당] {', '.join(mine) or '아직 없음'}\n"
                f"[현재 판단] {state.get('label')}\n[반문 허용] {allow}\n"
                f"[실행 결과] {json.dumps(state.get('tool_results', []), ensure_ascii=False)}\n"
                f"[대화 상태] {json.dumps(ctx['state'], ensure_ascii=False)}\n"
                f"[검토 의견] {json.dumps(state.get('review', {}), ensure_ascii=False)}\n"
                "이미 실행한 수정은 무엇을 어떻게 고쳤는지 구체적으로 말하세요. 실행 실패 시 고쳤다고 말하지 마세요.")
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
    return {"reply": None, "llm_messages": msgs, "token_usage": state.get("token_usage"), "step_count": state.get("step_count", 0) + 1,
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


PROMISE_EDIT = re.compile(r"(고칠|수정할|반영할|바꿀|고쳐\s*둘|수정해\s*둘|고치겠|수정하겠|반영하겠|고쳤|수정했|반영했)")
PROMISE_TASK = re.compile(r"(마무리할|정리할|진행할|완료할|준비할|전달할|공유할|해\s*둘|해둘|하겠|해드릴|보내드릴|드릴게)")
PROMISE_READ = re.compile(r"(볼게|확인할|검토할|읽을|보겠|확인하겠|검토하겠|읽겠|확인해\s*볼)")
CLARIFY = re.compile(r"(어느|어떤|무슨).{0,18}(부분|문장|내용)|다시.{0,10}(알려|말씀)")


def clarification_topic(state: WorkState) -> str:
    targets = state.get("targets") or []
    if targets:
        return ":".join(sorted(targets))
    text = normalize_expression(state.get("text", ""))
    doc = "T2" if re.search(r"FAQ|에프에이큐", text,re.I) else "T3" if re.search(r"리워드|표",text) else "T1" if re.search(r"안내문|공지",text) else "general"
    return f"{state.get('event_id')}:{doc}"


def action_violations(text: str, results: list[dict]) -> list[str]:
    done = {r["tool"] for r in results if r.get("payload", {}).get("ok")}
    problems = []
    if PROMISE_EDIT.search(text) and not done & {"edit_own_artifact", "suggest_candidate_edit", "update_task_status"}:
        problems.append("promise_without_edit")
    if PROMISE_READ.search(text) and "read_artifact" not in done:
        problems.append("promise_without_read_and_opinion")
    if PROMISE_TASK.search(text) and not done & {"edit_own_artifact", "suggest_candidate_edit", "update_task_status"}:
        problems.append("promise_without_task_action")
    return problems


@_timed
def validate_output(state: WorkState) -> dict:
    text = H.to_chat_plain(state.get("answer") or "")
    manager = state.get("answer_actor") == "MANAGER"
    results = state.get("tool_results", [])
    recent = [m["content"] for m in state["ctx"]["messages"] if m["actor"] in ("CANDIDATE", "COLLEAGUE")][-6:]
    permitted = "\n".join(recent + [json.dumps(r["payload"].get("data"), ensure_ascii=False) for r in results if r["payload"].get("ok")])
    problems = H.leak_violations(normalize_expression(text), [normalize_expression(s) for s in _secrets(state)], normalize_expression(permitted))
    problems += H.validate_output(text, H.numbers_in(permitted))
    if not manager:
        problems += split_violations(text,state)
        problems += action_violations(text, results)
        if PROMISE_READ.search(text) and not state.get("review"):
            problems.append("read_without_concrete_opinion")
        dates = lambda x: set(re.findall(r"\d{1,2}/\d{1,2}|\d{1,2}:\d{2}|\d{1,2}시", normalize_expression(x)))
        if dates(text) - dates(permitted):
            problems.append("new_schedule")
        if len([s for s in re.split(r"[.!?]+(?:\s|$)", text) if s.strip()]) > 2:
            problems.append("more_than_two_sentences")
        if re.search(r"[\U0001F300-\U0001FAFF]", text):
            problems.append("emoji")
        prev = [m for m in state["ctx"]["messages"][-6:] if m["actor"] == "COLLEAGUE"]
        if CLARIFY.search(text) and (clarification_topic(state) in (state["ctx"]["state"].get("clarification_topics") or []) or any(CLARIFY.search(m["content"]) for m in prev)):
            problems.append("repeated_clarification")
        if re.search(r"제가.{0,15}(맞을까요|범위|담당인가요)", text) and not (state.get("effects") or {}).get("pushback_used"):
            problems.append("pushback_not_allowed")
    if not text.strip():
        problems.append("empty")
    if problems:
        count = state.get("output_rewrite_count", 0) + 1
        if S.llm_mode == "live" and count <= 2:
            msgs = list(state.get("llm_messages") or [])
            correction = "출력 검사를 통과하지 못했어요: " + ", ".join(problems) + ". 이미 실행된 행동만 근거로 2문장 이내 다시 답하세요."
            if state.get("run_type") == "split":
                correction += " 시스템 결정과 일치하는 응답 기준: " + split_fallback(state["ctx"]["state"]["split"]) + " 담당과 FAQ 양쪽 개수를 생략하지 말고 한국어로 확인하세요."
            msgs.append({"role":"user","content":correction})
            return {"answer": "", "llm_messages": msgs, "output_rewrite_count": count, "error_code": "OUTPUT_RETRY"}
        fallback = MANAGER_DEFER if manager else H.SAFE_FALLBACK
        if "repeated_clarification" in problems or (not manager and (clarification_topic(state) in (state["ctx"]["state"].get("clarification_topics") or []) or any(CLARIFY.search(m["content"]) for m in prev))):
            fallback = "넵, 말씀해 주신 내용은 읽었어요."
        if state.get("run_type") == "split":
            fallback = split_fallback(state["ctx"]["state"]["split"])
        return {"answer": fallback, "output_rewrite_count": count, "error_code": "OUTPUT_VALIDATION"}
    return {"answer": text, "error_code": None}


def after_validation(state: WorkState) -> str:
    return "reason" if state.get("error_code") == "OUTPUT_RETRY" else "respond"


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
        if state.get("answer_actor") != "MANAGER" and CLARIFY.search(state["answer"]):
            gw.post(f"/runs/{state['run_id']}/branch", {"event_id":state.get("event_id"), "label":state.get("label") or "NONE", "clarification_topic":clarification_topic(state)})
        gw.event(state["run_id"], ACTOR_EVENT[state.get("answer_actor", "COLLEAGUE")],
                 {"content": state["answer"], "citations": state.get("citations", [])[:5]}, key="respond")
    return {}


def after_respond(state: WorkState) -> str:
    return "persist_proposal" if state.get("fixes") else END


# ---- 정정 수용: 수정안 → 승인 interrupt → 적용 ---------------------------------------------------------

def _apply_ops(body: str, ops: list[dict]) -> str:
    for op in ops:
        if op["op"] == "replace" and op["find"] in body:
            body = body.replace(op["find"], op["replace"])
        elif op["op"] == "insert_before" and op["text"].strip() not in body:
            i = body.find(op["anchor"])
            body = body[:i] + op["text"] + body[i:] if i >= 0 else body.rstrip("\n") + "\n" + op["text"].strip() + "\n"
    return body


def fixture_answer(state: WorkState) -> str:
    successes = [r for r in state.get("tool_results", []) if r["tool"] == "edit_own_artifact" and r["payload"].get("ok")]
    if successes:
        parts = []
        for r in successes:
            d = r["payload"]["data"]
            before, after = d.get("before", ""), d.get("after", "")
            old = [x for x in before.splitlines() if x not in after.splitlines()]
            new = [x for x in after.splitlines() if x not in before.splitlines()]
            parts.append(f"{d['artifact_key']}의 {' / '.join(old)} → {' / '.join(new)}")
        return "넵, " + "; ".join(parts) + "로 수정했어요. 짚어 주셔서 감사해요!"
    if state.get("targets") and not successes:
        return "넵, 말씀하신 부분은 현재 작업본에 반영되어 있어요. 짚어 주셔서 감사해요!"
    if state.get("review"):
        return state["review"]["opinion"]
    if state.get("label") == "WRONG_CRITICISM":
        return "앗, 브리프에 동일 결제수단 계정은 제외한다고 되어 있어요. 이 조건은 그대로 두었어요."
    if state.get("label") == "VAGUE_CRITICISM":
        return H.SAFE_FALLBACK
    reply = state.get("reply") or {}
    text = reply.get("text", FALLBACK_COLLEAGUE)
    return H.SAFE_FALLBACK if re.search(r"(할게요|볼게요|하겠습니다)", text) else text


def review_request(state: WorkState) -> bool:
    return bool(re.search(r"(검토|리뷰|봐\s*주|봐주|확인해\s*주|확인\s*부탁)", state["text"]) and
                re.search(r"(제|제가|내|T1|T5|안내문|푸시|공지)", state["text"], re.I) and not state.get("targets"))


@_timed
def propose_fix(state: WorkState) -> dict:
    results = list(state.get("tool_results") or [])
    if state.get("label") == "WRONG_CRITICISM":
        payload = mcp(state, "search_docs", {"query": state["text"][:200], "document_ids": ["brief"], "top_k": 2})
        results.append({"tool":"search_docs","args":{"document_ids":["brief"]},"payload":payload})
        return {"fixes":[],"tool_results":results}
    if review_request(state):
        candidates = [a for a in state["ctx"]["artifacts"] if a.get("owner") in ("CANDIDATE", "SPLIT")]
        requested_key = next((k for k, rx in {"T1":r"안내문|공지", "T2":r"FAQ|에프에이큐", "T3":r"표|리워드", "T5":r"푸시"}.items() if re.search(rx,state["text"],re.I)), None)
        key = next((a["key"] for a in candidates if a["key"] in state["text"]), requested_key)
        a = next((a for a in candidates if a["key"] == key), candidates[0] if candidates else None)
        if not a:
            return {}
        payload = mcp(state, "read_artifact", {"artifact_key": a["key"]})
        results.append({"tool": "read_artifact", "args": {"artifact_key": a["key"]}, "payload": payload})
        if not payload.get("ok"):
            return {"tool_results": results}
        a = payload["data"]
        opinion, content = review_artifact(state, a)
        fixes = []
        if content and content != a["body"]:
            fixes = [{"artifact_key": a["key"], "base_version": a["version"], "content": content, "targets": ["REVIEW"]}]
        return {"fixes": fixes, "fix_index": 0, "fix_results": [], "tool_results": results,
                "review": {"artifact_key": a["key"], "opinion": opinion}}
    if not state.get("targets"):
        return {"fixes": [], "fix_index": 0, "fix_results": []}
    if state.get("target_source") == "llm":
        gw.post(f"/runs/{state['run_id']}/targets", {"targets":state["targets"]})
    p = mcp(state, "get_planted_error", {"error_ids": state["targets"]})
    ops_by_art: dict[str, list[dict]] = {}
    for it in (p.get("data") or {}).get("items", []):
        for op in it.get("fix", []):
            ops_by_art.setdefault(op["artifact"], []).append(op)
    arts = {a["key"]: a for a in state["ctx"]["artifacts"]}
    for key, ops in sorted(ops_by_art.items(), key=lambda kv: kv[0] != "T3"):
        a = arts.get(key)
        if not a or a.get("owner") not in ("COLLEAGUE", "SPLIT"):
            continue
        read = mcp(state, "read_artifact", {"artifact_key":key})
        results.append({"tool":"read_artifact","args":{"artifact_key":key},"payload":read})
        if read.get("ok"):
            a = {**a, **read["data"]}
        new = _apply_ops(a["body"], ops)
        if new != a["body"]:
            args = {"artifact_key": key, "base_version": a["version"], "content": new, "targets": state["targets"]}
            payload = mcp(state, "edit_own_artifact", args)
            results.append({"tool": "edit_own_artifact", "args": args, "payload": payload})
    return {"fixes": [], "fix_index": 0, "fix_results": [], "tool_results": results}


def review_artifact(state: WorkState, artifact: dict) -> tuple[str, str | None]:
    body = artifact["body"]
    if S.llm_mode == "live":
        from langchain_core.messages import SystemMessage, HumanMessage
        ai = _llm(json_mode=True).invoke([SystemMessage(
            '요청받은 문서만 검토한다. 한국어 존댓말 2문장 이내. 표현, 톤, 누락 항목, 길이만 검토한다. '
            '금액·날짜의 정오 대조 금지. 어느 문장인지, 왜, 어떻게 고치면 좋을지 구체적으로 설명한다. 일부러 틀린 의견 금지. '
            'Return JSON {"opinion":"...","content":"수정 후 전체 본문 or null"}.'),
            HumanMessage(json.dumps({"title": artifact["title"], "body": body, "request": state["text"]}, ensure_ascii=False))])
        _usage(state, ai)
        out = json.loads(ai.content)
        return out["opinion"], out.get("content")
    if '쏴드림' in body:
        return ('앗, “쏴드림”은 고객 안내의 존댓말 톤과 맞지 않아서 “지급해 드립니다”로 바꾸면 좋겠어요.', body.replace('쏴드림', '지급해 드립니다'))
    if not body.strip():
        return ('앗, 아직 본문이 비어 있어요. 제목과 참여 방법부터 적으면 안내 내용을 이해하기 좋겠어요.', None)
    return ('넵, “'+body.splitlines()[0][:70]+'” 문장 뒤에 참여 방법을 항목별로 나누면 읽기 더 편하겠어요.', None)


@_timed
def persist_proposal(state: WorkState) -> dict:
    """Idempotent approval creation BEFORE interrupt (same interrupt_id on replay)."""
    fx = state["fixes"][state["fix_index"]]
    r = gw.post(f"/runs/{state['run_id']}/proposal", {"interrupt_id": f"fix-{fx['artifact_key']}", "tool_name": "suggest_candidate_edit",
                                                      "args": fx, "base_versions": {"artifact_version": fx["base_version"]}})
    return {"approval_id": r["approval_id"]}


def await_approval(state: WorkState) -> dict:
    """Only interrupt here — no side effects before/after inside this node."""
    decision = interrupt({"approval_id": state["approval_id"], "tool_name": "suggest_candidate_edit"})
    return {"decision": decision}


def after_approval(state: WorkState) -> str:
    return "execute_write" if state.get("decision") == "APPROVE" else "record_rejection"


@_timed
def execute_write(state: WorkState) -> dict:
    fx = state["fixes"][state["fix_index"]]
    payload, ms = call_tool(gw, state["run_id"], "suggest_candidate_edit", fx, approval_id=state["approval_id"])
    gw.event(state["run_id"], "TOOL_END", {"tool_name": "suggest_candidate_edit", "safe_args": {"artifact_key": fx["artifact_key"],
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
             ("classify", classify), ("decide", decide), ("observer", observer), ("record_observations", record_observations),
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
    g.add_edge("decide", "propose_fix")
    g.add_edge("propose_fix", "observer")
    g.add_edge("observer", "record_observations")
    g.add_edge("record_observations", "apply_effects")
    g.add_conditional_edges("apply_effects", after_effects, ["reason", "respond", END])
    g.add_conditional_edges("reason", after_reason, ["call_mcp", "validate_output"])
    g.add_conditional_edges("call_mcp", after_call, ["reason", "validate_output"])
    g.add_conditional_edges("validate_output", after_validation, ["reason", "respond"])
    g.add_conditional_edges("respond", after_respond, ["persist_proposal", END])
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

"""LangGraph WorkState graph (ARCHITECTURE §8).

load_context → classify_request → select_help → reason
  ├─ 조사 필요 → call_mcp (한도 내 반복) → reason
  ├─ 변경 제안(DELEGATED) → persist_proposal → await_approval(interrupt) → execute_write | record_rejection → respond
  └─ 응답 가능 → validate_output → respond → END
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

from . import harness as H
from .clients import Gateway, call_tool, list_read_tools

S = settings()


class WorkState(TypedDict, total=False):
    session_id: str
    run_id: str
    task_id: str | None
    kind: str
    phase: str
    source_message_id: str | None
    message_ids: list[str]
    context_summary: dict | None
    facts: dict
    tool_results: list[dict]
    citations: list[dict]
    proposed_action: dict | None
    approval_id: str | None
    delegation_id: str | None
    help_id: str
    policy_version: str
    step_count: int
    tool_counts: dict[str, int]
    active_execution_ms: int
    output_rewrite_count: int
    retries: int
    error_code: str | None
    # implementation fields
    intent: str
    request: str
    plan: list[dict]
    llm_messages: list[dict]
    answer: str
    limited: str | None
    delegation_proposal: dict | None
    decision: str | None
    token_usage: dict


gw = Gateway()


def _timed(fn):
    def wrapper(state: WorkState) -> dict:
        t0 = time.monotonic()
        out = fn(state) or {}
        out["active_execution_ms"] = state.get("active_execution_ms", 0) + int((time.monotonic() - t0) * 1000)
        return out
    wrapper.__name__ = fn.__name__
    return wrapper


# ---- nodes -------------------------------------------------------------------------

@_timed
def load_context(state: WorkState) -> dict:
    ctx = gw.get(f"/runs/{state['run_id']}/context")
    run = ctx["run"]
    out: dict[str, Any] = {"session_id": ctx["session"]["id"], "kind": run["kind"], "phase": ctx["session"]["phase"],
                           "task_id": run["task_id"], "source_message_id": run["source_message_id"],
                           "policy_version": POLICY_VERSION, "facts": {"ctx": ctx},
                           "message_ids": [str(m["id"]) for m in ctx["messages"]],
                           "request": run["input"].get("content", ""),
                           "step_count": state.get("step_count", 0), "tool_counts": state.get("tool_counts", {}),
                           "tool_results": state.get("tool_results", []), "citations": state.get("citations", []),
                           "output_rewrite_count": 0, "retries": 0, "error_code": None,
                           "token_usage": state.get("token_usage", {"input": 0, "output": 0})}
    if ctx["delegation"]:
        out["delegation_id"] = str(ctx["delegation"]["id"])
        out["request"] = ctx["task"]["title"]
    return out


DELEGATE_RE = re.compile(r"(위임|맡겨|맡길|대신\s*정리|정리해\s*줄|정리해\s*주|정리\s*부탁)")
ANSWER_RE = re.compile(r"(정답|답\s*알려|뭐가\s*문제|우선순위\s*(정해|골라)|최종안\s*(써|작성)|대신\s*(써|작성|결정))")
READ_RE = re.compile(r"(조사|조회|확인|찾아|알려|보여|수치|지표|이탈|비율|문의|고객|문서|정책|릴리즈|변경|배송|가입|쿠폰|주소|모바일|데스크톱|신규|재방문|금액)")


@_timed
def classify_request(state: WorkState) -> dict:
    """Code decides scope/help; only the request type is classified (rules; LLM not needed for this split)."""
    if state["kind"] == "DELEGATED":
        return {"intent": "delegated"}
    text = state["request"]
    if ANSWER_RE.search(text):
        return {"intent": "answer_request"}
    if state["kind"] == "COLLEAGUE" and DELEGATE_RE.search(text):
        return {"intent": "delegate_proposal"}
    if READ_RE.search(text):
        return {"intent": "investigate"}
    return {"intent": "question"}


@_timed
def select_help(state: WorkState) -> dict:
    return {"help_id": {"delegated": "H3", "investigate": "H2", "delegate_proposal": "H1",
                        "answer_request": "H1", "question": "H1"}[state["intent"]]}


# ---- fixture planner (deterministic, LLM_MODE=fixture) ------------------------------------

TAG_WORDS = {"배송": "shipping", "무료배송": "shipping", "가입": "signup", "회원": "signup", "쿠폰": "coupon",
             "주소": "performance", "느": "performance", "성능": "performance", "비교": "comparison"}


def fixture_plan(text: str, filters: dict | None = None) -> list[dict]:
    f: dict[str, str] = dict(filters or {})
    if "모바일" in text: f.setdefault("device", "mobile")
    if "데스크톱" in text or "PC" in text: f.setdefault("device", "desktop")
    if "신규" in text: f.setdefault("visitor", "new")
    if "재방문" in text: f.setdefault("visitor", "returning")
    period = "baseline" if ("baseline" in text or "이전" in text) and "current" not in text else "current"
    if "visitor" not in f:
        dim = "visitor"
    elif "device" not in f:
        dim = "device"
    else:
        dim = "cart_value"
    plan = [{"tool": "get_funnel_metrics", "args": {"period": "baseline", "dimension": dim, "filters": f}},
            {"tool": "get_funnel_metrics", "args": {"period": period if period == "current" else "current", "dimension": dim, "filters": f}}]
    tags = sorted({v for k, v in TAG_WORDS.items() if k in text})[:3]
    if tags or "고객" in text or "문의" in text:
        plan.append({"tool": "get_support_cases", "args": {"tags": tags, "limit": 5}})
    plan.append({"tool": "search_docs", "args": {"query": text[:200], "top_k": 3}})
    return plan


def pct(v: float | None) -> str:
    return "—" if v is None else f"{v * 100:.1f}%"


def fixture_answer(state: WorkState) -> str:
    lines: list[str] = []
    metrics = [r for r in state["tool_results"] if r["tool"] == "get_funnel_metrics" and r["payload"]["ok"]]
    by_period = {m["args"]["period"]: m["payload"]["data"] for m in metrics}
    if "current" in by_period:
        cur, base = by_period["current"], by_period.get("baseline")
        fl = cur["filters"]
        scope = ", ".join(f"{k}={v}" for k, v in fl.items()) or "전체"
        lines.append(f"[지표 조회] current 기간 · 범위 {scope} · {cur['dimension']}별 (cart-data-v1)")
        base_rows = {r["segment"]: r for r in (base["rows"] if base else [])}
        for r in cur["rows"]:
            b = base_rows.get(r["segment"])
            diff = ""
            if b and b["abandonment_rate"] is not None and r["abandonment_rate"] is not None:
                diff = f" (baseline {pct(b['abandonment_rate'])}, {round((r['abandonment_rate'] - b['abandonment_rate']) * 100, 1)}pp)"
            lines.append(f"- {r['segment']}: 장바구니 {r['cart_sessions']}세션 → 결제 {r['checkout_sessions']} → 주문 {r['orders']}, "
                         f"장바구니 이탈률 {pct(r['abandonment_rate'])}{diff}, 결제 진입 후 이탈률 {pct(r['checkout_abandonment_rate'])}")
    cases = [r for r in state["tool_results"] if r["tool"] == "get_support_cases" and r["payload"]["ok"]]
    if cases:
        items = cases[0]["payload"]["data"]["items"]
        lines.append("[고객 문의] " + " / ".join(f"{i['id']} “{i['quote']}”" for i in items[:3]))
        lines.append("  ※ 과제용 선택 사례라 전체 원인 비중은 알 수 없습니다.")
    docs = [r for r in state["tool_results"] if r["tool"] == "search_docs" and r["payload"]["ok"]]
    if docs and docs[0]["payload"]["data"]["matches"]:
        m = docs[0]["payload"]["data"]["matches"][0]
        lines.append(f"[관련 문서] {m['title']}: “{m['quote'][:80]}”")
    errors = [r for r in state["tool_results"] if not r["payload"]["ok"]]
    for e in errors:
        lines.append(f"- {e['tool']} 조회 실패({e['payload']['error']['code']}): 이 부분은 확인하지 못했습니다.")
    lines.append("관찰 집계라 특정 변경의 인과 효과는 확정할 수 없습니다.")
    lines.append("다음으로 어떤 범위(기기·방문 유형·금액·문의 태그)를 더 볼지 정해 주시겠어요?")
    return "\n".join(lines)


# ---- live LLM ----------------------------------------------------------------------------

def llm():
    from langchain_openai import ChatOpenAI
    return ChatOpenAI(model=S.openai_model, max_tokens=H.OUTPUT_TOKEN_BUDGET, timeout=30, max_retries=0, temperature=0.2)


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


def _tool_specs(tools: list) -> list[dict]:
    return [{"type": "function", "function": {"name": t.name, "description": t.description or "",
                                              "parameters": t.input_schema if hasattr(t, "input_schema") else t.inputSchema}}
            for t in tools]


@_timed
def reason(state: WorkState) -> dict:
    """Decide next tool call(s) or final answer, inside loop limits."""
    intent = state["intent"]
    if intent in ("answer_request", "question", "delegate_proposal"):
        return {"plan": []}
    if S.llm_mode != "live":
        if not state.get("tool_results"):
            filters = (state["facts"]["ctx"].get("delegation") or {}).get("constraints", {}).get("filters")
            return {"plan": fixture_plan(state["request"], filters)}
        return {}
    # live: real gpt-4o-mini tool selection
    msgs = state.get("llm_messages") or []
    if not msgs:
        ctx = state["facts"]["ctx"]
        name = "assistant-v1" if state["kind"] == "ASSISTANT" else "colleague-v1"
        system, _ = H.load_prompt(name)
        pack = H.build_context(system, ctx["public_brief"]["public_brief"], ctx["messages"], [],
                               ctx.get("delegation"), H.rule_summary)
        msgs = [{"role": "system", "content": system},
                {"role": "user", "content": H.mask_pii(pack.render_user_context())}]
        for m in pack.messages:
            msgs.append({"role": "user" if m["actor"] == "CANDIDATE" else "assistant",
                         "content": H.mask_pii(f"[{m['actor']}] {m['content']}")})
        if state["kind"] == "DELEGATED":
            msgs.append({"role": "user", "content": f"[위임 작업] {state['request']}. 위임 범위의 사실과 출처만 조사해 evidence 섹션용 요약을 작성하라."})
    tools = _tool_specs(list_read_tools(gw, state["run_id"]))
    deadline = time.monotonic() + max(1.0, (H.ACTIVE_BUDGET_MS - state.get("active_execution_ms", 0)) / 1000)
    model = llm().bind_tools(tools)
    ai = H.with_retries(lambda: model.invoke(_to_lc(msgs)), deadline=deadline)
    usage = dict(state.get("token_usage") or {"input": 0, "output": 0})
    um = getattr(ai, "usage_metadata", None) or {}
    usage["input"] += um.get("input_tokens", 0)
    usage["output"] += um.get("output_tokens", 0)
    calls = [{"id": tc["id"], "name": tc["name"], "args": tc["args"]} for tc in (ai.tool_calls or [])]
    msgs = msgs + [{"role": "assistant", "content": ai.content or "", "tool_calls": calls}]
    return {"llm_messages": msgs, "token_usage": usage, "step_count": state.get("step_count", 0) + 1,
            "plan": [{"tool": c["name"], "args": c["args"], "tool_call_id": c["id"]} for c in calls],
            "answer": ai.content if not calls else state.get("answer", "")}


@_timed
def call_mcp(state: WorkState) -> dict:
    plan = list(state.get("plan") or [])
    results = list(state.get("tool_results") or [])
    counts = dict(state.get("tool_counts") or {})
    cits = list(state.get("citations") or [])
    msgs = list(state.get("llm_messages") or [])
    limited = None
    for step in plan:
        tool, args = step["tool"], step["args"]
        tcid = step.get("tool_call_id") or f"tc-{uuid.uuid4().hex[:8]}"
        try:
            H.check_tool_budget(counts, tool, state.get("step_count", 0), state.get("active_execution_ms", 0))
        except H.LimitExceeded as e:
            limited = e.reason
            payload = {"ok": False, "data": None, "error": {"code": "RATE_LIMITED", "message": f"도구 한도 초과({e.reason})", "retryable": False}, "citations": []}
            msgs.append({"role": "tool", "tool_call_id": tcid, "content": H.tool_message_content(payload)})
            continue
        if tool not in {"get_funnel_metrics", "get_support_cases", "search_docs"}:
            payload = {"ok": False, "data": None, "error": {"code": "FORBIDDEN", "message": f"허용되지 않은 도구: {tool}", "retryable": False}, "citations": []}
        else:
            gw.event(state["run_id"], "TOOL_START", {"tool_call_id": tcid, "tool_name": tool}, key=f"start:{tcid}")
            payload, ms = call_tool(gw, state["run_id"], tool, args)
            gw.event(state["run_id"], "TOOL_END", {"tool_name": tool, "safe_args": args, "outcome": "ok" if payload["ok"] else payload["error"]["code"],
                                                   "result_summary": {"rows": len((payload.get("data") or {}).get("rows", (payload.get("data") or {}).get("matches", (payload.get("data") or {}).get("items", []))))},
                                                   "citations": payload.get("citations", []), "help_id": state["help_id"], "duration_ms": ms},
                     key=f"end:{tcid}")
        counts[tool] = counts.get(tool, 0) + 1
        results.append({"tool": tool, "args": args, "payload": payload, "tool_call_id": tcid})
        cits += payload.get("citations", [])
        # business errors go back to the model as a ToolMessage with the same tool_call_id
        msgs.append({"role": "tool", "tool_call_id": tcid, "content": H.tool_message_content(payload)})
    return {"tool_results": results, "tool_counts": counts, "citations": cits, "plan": [], "llm_messages": msgs,
            "limited": limited or state.get("limited"), "step_count": state.get("step_count", 0) + (0 if S.llm_mode == "live" else 1)}


def after_reason(state: WorkState) -> str:
    if state.get("plan"):
        return "call_mcp"
    return "draft_delegation" if state["intent"] == "delegated" else "validate_output"


def after_call(state: WorkState) -> str:
    if state.get("limited"):
        return "draft_delegation" if state["intent"] == "delegated" else "validate_output"
    if S.llm_mode == "live" and state.get("step_count", 0) < H.MAX_STEPS:
        return "reason"
    return "draft_delegation" if state["intent"] == "delegated" else "validate_output"


@_timed
def validate_output(state: WorkState) -> dict:
    intent = state["intent"]
    if intent == "answer_request":
        return {"answer": "정답을 정해 드리기보다 함께 근거를 보는 편이 좋겠습니다. 먼저 어떤 자료 범위를 확인할지 정해 주시겠어요? "
                          "예: current 기간 기기별 지표, 신규/재방문 비교, 배송·가입 관련 고객 문의."}
    if intent == "question":
        return {"answer": "어떤 부분을 도와드릴까요? 조사할 범위(기간·기기·방문 유형·장바구니 금액·문의 태그·문서)를 정해 주시면 "
                          "그 범위의 사실을 출처와 함께 정리하겠습니다."}
    if intent == "delegate_proposal":
        f = {k: v for k, v in fixture_plan(state["request"])[0]["args"]["filters"].items()}
        scope = ", ".join(f"{k}={v}" for k, v in f.items()) or "전체"
        title = f"evidence 조사: {scope} 세그먼트 지표와 관련 문의·문서"
        return {"answer": f"위임 범위를 제안드립니다. 확인 버튼을 누르시면 제가 '{title}'를 조사해 evidence 섹션 초안을 만들고, "
                          f"문서에 반영하기 전에 승인을 요청하겠습니다. 범위를 바꾸고 싶으시면 말씀해 주세요.",
                "delegation_proposal": {"title": title[:150], "target_section": "evidence",
                                        "allowed_tools": ["get_funnel_metrics", "get_support_cases", "search_docs"], "filters": f}}
    text = state.get("answer") or "" if S.llm_mode == "live" else fixture_answer(state)
    if not text.strip():
        text = fixture_answer(state)
    allowed = _allowed_numbers(state)
    problems = H.validate_output(text, allowed)
    rewrites = state.get("output_rewrite_count", 0)
    if problems:
        if rewrites == 0:
            text = fixture_answer(state)  # one deterministic rewrite from tool results only
            problems = H.validate_output(text, allowed)
        if problems:
            text = H.SAFE_FALLBACK
            return {"answer": text, "output_rewrite_count": rewrites + 1, "error_code": "OUTPUT_VALIDATION"}
    if state.get("limited"):
        text += f"\n(도구 사용 한도 {state['limited']}에 도달해 여기까지만 조사했습니다.)"
    return {"answer": text, "output_rewrite_count": rewrites + (1 if problems else 0)}


def _allowed_numbers(state: WorkState) -> set[str]:
    """Numbers present in tool results/request, plus pp differences derived from returned rates."""
    allowed = set().union(*[H.numbers_in(r["payload"]) for r in state.get("tool_results", [])] or [set()])
    allowed |= H.numbers_in(state.get("request", ""))
    rates = [row[k] for r in state.get("tool_results", []) if r["tool"] == "get_funnel_metrics" and r["payload"]["ok"]
             for row in r["payload"]["data"]["rows"] for k in ("abandonment_rate", "checkout_abandonment_rate") if row[k] is not None]
    for x in rates:
        for y in rates:
            allowed.add(f"{abs(round((x - y) * 100, 1))}")
    return allowed


@_timed
def respond(state: WorkState) -> dict:
    etype = "ASSISTANT_MESSAGE" if state["kind"] == "ASSISTANT" else "COLLEAGUE_MESSAGE"
    payload: dict[str, Any] = {"content": state["answer"], "citations": _dedupe(state.get("citations", []))[:8]}
    if state.get("delegation_proposal"):
        payload["delegation_proposal"] = state["delegation_proposal"]
    if state.get("limited"):
        payload["limited"] = True
    gw.event(state["run_id"], etype, payload, key="respond")
    return {}


def _dedupe(cits: list[dict]) -> list[dict]:
    seen, out = set(), []
    for c in cits:
        k = (c.get("document_id"), c.get("chunk_id"), c.get("quote"))
        if k not in seen:
            seen.add(k)
            out.append(c)
    return out


# ---- delegated mutation path ------------------------------------------------------------------

@_timed
def draft_delegation(state: WorkState) -> dict:
    summary = fixture_answer(state) if S.llm_mode != "live" or not state.get("answer") else state["answer"]
    if H.validate_output(summary, _allowed_numbers(state)):
        summary = fixture_answer(state)
    summary = summary.replace("다음으로 어떤 범위(기기·방문 유형·금액·문의 태그)를 더 볼지 정해 주시겠어요?", "").strip()
    ctx = state["facts"]["ctx"]
    art = ctx["artifact"]
    current = art["sections"].get("evidence", "")
    content = (current + "\n\n" if current.strip() else "") + f"[동료 조사 · 위임: {ctx['task']['title']}]\n{summary}"
    cits = [c for c in _dedupe(state.get("citations", [])) if c.get("document_id") not in ("funnel_facts", "support_cases")][:5]
    args = {"task_id": state["task_id"], "section": "evidence", "base_version": art["version"], "content": content,
            "citations": [{"document_id": c["document_id"], "chunk_id": c.get("chunk_id"), "version": c.get("version", 1),
                           "quote": c["quote"]} for c in cits]}
    gw.event(state["run_id"], "TASK_RESULT", {"result": {"summary": summary, "citations": cits}}, key="task-result")
    return {"proposed_action": {"tool_name": "patch_artifact_section", "args": args,
                                "base_versions": {"artifact": art["version"]}}, "answer": summary}


@_timed
def persist_proposal(state: WorkState) -> dict:
    """Idempotent approval creation BEFORE interrupt (same interrupt_id on replay)."""
    pa = state["proposed_action"]
    r = gw.post(f"/runs/{state['run_id']}/proposal", {"interrupt_id": "evidence-patch-1", "tool_name": pa["tool_name"],
                                                      "args": pa["args"], "base_versions": pa["base_versions"],
                                                      "delegation_id": state.get("delegation_id")})
    return {"approval_id": r["approval_id"]}


def await_approval(state: WorkState) -> dict:
    """Only interrupt here — no side effects before/after inside this node."""
    decision = interrupt({"approval_id": state["approval_id"], "tool_name": state["proposed_action"]["tool_name"]})
    return {"decision": decision}


def after_approval(state: WorkState) -> str:
    return "execute_write" if state.get("decision") == "APPROVE" else "record_rejection"


@_timed
def execute_write(state: WorkState) -> dict:
    pa = state["proposed_action"]
    payload, ms = call_tool(gw, state["run_id"], pa["tool_name"], pa["args"], approval_id=state["approval_id"])
    gw.event(state["run_id"], "TOOL_END", {"tool_name": pa["tool_name"], "safe_args": {"section": "evidence", "task_id": state["task_id"]},
                                           "outcome": "ok" if payload["ok"] else payload["error"]["code"],
                                           "result_summary": payload.get("data") or {}, "citations": [], "help_id": "H3",
                                           "duration_ms": ms}, key=f"write:{state['approval_id']}")
    if payload["ok"]:
        text = "승인해 주신 범위대로 evidence 섹션에 조사 요약을 반영했습니다. 그대로 쓸지, 수정·기각할지는 태스크 보드에서 결정해 주세요."
    else:
        code = payload["error"]["code"]
        text = ("승인 대기 중 기획안이 바뀌어 반영하지 않았습니다(APPROVAL_STALE). 필요하면 수정 요청으로 다시 조사하겠습니다."
                if code == "VERSION_CONFLICT" else f"변경을 반영하지 못했습니다({code}). 문서는 바뀌지 않았습니다.")
    return {"answer": text, "error_code": None if payload["ok"] else payload["error"]["code"]}


@_timed
def record_rejection(state: WorkState) -> dict:
    return {"answer": "거절하신 대로 기획안은 변경하지 않았습니다. 조사 요약은 태스크 카드에 남겨 두었으니 검토 후 수정 요청 또는 기각해 주세요."}


def build(checkpointer):
    g = StateGraph(WorkState)
    for name, fn in [("load_context", load_context), ("classify_request", classify_request), ("select_help", select_help),
                     ("reason", reason), ("call_mcp", call_mcp), ("validate_output", validate_output), ("respond", respond),
                     ("draft_delegation", draft_delegation), ("persist_proposal", persist_proposal),
                     ("await_approval", await_approval), ("execute_write", execute_write),
                     ("record_rejection", record_rejection)]:
        g.add_node(name, fn)
    g.add_edge(START, "load_context")
    g.add_edge("load_context", "classify_request")
    g.add_edge("classify_request", "select_help")
    g.add_edge("select_help", "reason")
    g.add_conditional_edges("reason", after_reason, ["call_mcp", "validate_output", "draft_delegation"])
    g.add_conditional_edges("call_mcp", after_call, ["reason", "validate_output", "draft_delegation"])
    g.add_edge("validate_output", "respond")
    g.add_edge("draft_delegation", "persist_proposal")
    g.add_edge("persist_proposal", "await_approval")
    g.add_conditional_edges("await_approval", after_approval, ["execute_write", "record_rejection"])
    g.add_edge("execute_write", "respond")
    g.add_edge("record_rejection", "respond")
    g.add_edge("respond", END)
    return g.compile(checkpointer=checkpointer)


def summarize_result(state: dict) -> dict:
    return {"intent": state.get("intent"), "help_id": state.get("help_id"), "tool_counts": state.get("tool_counts"),
            "limited": state.get("limited"), "decision": state.get("decision"), "error_code": state.get("error_code"),
            "active_execution_ms": state.get("active_execution_ms"), "answer_chars": len(state.get("answer") or "")}


__all__ = ["build", "WorkState", "summarize_result", "json"]

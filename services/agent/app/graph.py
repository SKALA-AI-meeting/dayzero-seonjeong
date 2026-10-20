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
from .clients import Gateway, call_tool, list_read_tools, read_resource

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
        out["request"] = ctx["task"]["title"] + (f" (수정 요청: {run['input']['revise_comment']})" if run["input"].get("revise_comment") else "")
    return out


ANSWER_RE = re.compile(r"(정답|답\s*알려|대신\s*(써|작성|결정|정해)|최종안\s*(써|작성))")
RECHECK_RE = re.compile(r"(유료|멤버십|결제|정책|재검토|다시\s*확인|확인해\s*(주|보)|맞나요|충돌|안\s*될|불가)")
FEEDBACK_RE = re.compile(r"(피드백|봐\s*주|검토|확인\s*(해|하고|부탁|좀)|어떤가요|어때요|의견)")
DOC_REF_RE = re.compile(r"(작성|섹션|\d\s*번|기획안|문서|초안|썼|적었)")
REVISE_RE = re.compile(r"(수정|고쳐|고치|반영|업데이트|다시\s*(작성|써|정리)|바꿔|보완|초안|작성|써\s*주|정리해)")
PROMISE_RE = re.compile(r"(작성|수정|반영|정리|보완|업데이트)(해\s*)?(하겠|할게|해\s*볼게|해\s*드릴게|해서\s*공유)")
ASK_RE = re.compile(r"(부탁|해\s*주|해줄|해주실|해\s*줘|주실\s*수|가능할까|할\s*수\s*있을까|해\s*달)")
SECTION_WORDS = [("problem", ("문제 정의", "문제정의", "대상 사용자", "대상")), ("interview_evidence", ("인터뷰",)),
                 ("features", ("핵심 기능", "기능 제안")), ("similar_cases", ("사례", "유사 서비스", "비슷한 서비스")),
                 ("metrics_timeline", ("지표", "일정", "출시"))]


def requested_sections(text: str, scen: dict, recent: list[str] | None = None) -> list[str]:
    secs = [sid for sid, words in SECTION_WORDS if any(w in text for w in words)]
    for prev in reversed(recent or []):  # 섹션 언급이 없으면 최근 대화 주제에서 찾음(가장 최근 우선)
        if secs:
            break
        secs = [sid for sid, words in SECTION_WORDS if any(w in prev for w in words)]
    if not secs:
        secs = list(scen.get("colleague_sections") or [])
        if scen.get("pivot_text") and any(w in text for w in ("공지", "변경", "대상", "방향")) and "problem" not in secs:
            secs.insert(0, "problem")
    return secs[:3]


READ_RE = re.compile(r"(조사|조회|찾아|알려|보여|수치|지표|재참여|비율|인터뷰|문서|정책|회의록|사례|규모|사용자|자료)")


@_timed
def classify_request(state: WorkState) -> dict:
    """Code decides scope/help; only the request type is classified."""
    if state["kind"] == "DELEGATED":
        return {"intent": "delegated"}
    text = state["request"]
    scen = state["facts"]["ctx"].get("scenario_state") or {}
    if state["kind"] == "COLLEAGUE" and scen.get("error_open") and RECHECK_RE.search(text):
        return {"intent": "policy_recheck"}
    if state["kind"] == "COLLEAGUE" and scen.get("split_confirmed") and REVISE_RE.search(text) and ASK_RE.search(text) \
            and not FEEDBACK_RE.search(text.split("수정")[0][-6:] if "수정" in text else ""):
        return {"intent": "revise_request"}
    if state["kind"] == "COLLEAGUE" and FEEDBACK_RE.search(text) and DOC_REF_RE.search(text):
        return {"intent": "feedback"}
    if ANSWER_RE.search(text):
        return {"intent": "answer_request"}
    if READ_RE.search(text):
        return {"intent": "investigate"}
    return {"intent": "conversation"}


@_timed
def select_help(state: WorkState) -> dict:
    return {"help_id": {"delegated": "H3", "investigate": "H2", "policy_recheck": "H2",
                        "answer_request": "H1", "conversation": "H1", "revise_request": "H3", "feedback": "H1"}[state["intent"]]}


# ---- fixture planner (deterministic, LLM_MODE=fixture) ------------------------------------

TAG_WORDS = {"어색": "awkward", "아는 사람": "awkward", "일정": "missed_schedule", "알림": "missed_schedule",
             "놓": "missed_schedule", "페이스": "pace", "위치": "location", "리더": "host"}
SECTION_QUERY = {"similar_cases": "비슷한 서비스 사례 같이달려 한바퀴", "metrics_timeline": "재참여율 지표 출시 일정 개발 리드",
                 "features": "재참여 기능 아이디어", "problem": "재참여율 문제", "interview_evidence": "사용자 인터뷰 의견"}


DOC_HINTS = {"operating-policy": ("운영 정책", "정책"), "metrics-status": ("지표 현황", "재참여율 정의"),
             "meeting-notes": ("회의록", "지난주 회의"), "company-intro": ("회사 소개", "서비스 소개", "회사·서비스"),
             "user-interviews": ("인터뷰",)}
DOC_TITLE = {"operating-policy": "운영 정책", "metrics-status": "지표 현황", "meeting-notes": "지난주 회의록",
             "company-intro": "회사·서비스 소개", "user-interviews": "사용자 인터뷰 요약"}
METRIC_RE = re.compile(r"(지표|재참여|수치|비율|규모|%|몇\s*명)")


def fixture_plan(text: str, section: str | None = None, released: bool = False) -> list[dict]:
    plan = []
    if section == "metrics_timeline" or (section is None and METRIC_RE.search(text)):
        plan.append({"tool": "get_rejoin_metrics", "args": {"dimension": "group_size"}})
    tags = sorted({v for k, v in TAG_WORDS.items() if k in text})[:3]
    if released and (tags or "인터뷰" in text or section in ("interview_evidence", "features")):
        plan.append({"tool": "get_interview_notes", "args": {"tags": tags, "limit": 8}})
    plan.append({"tool": "search_docs", "args": {"query": (SECTION_QUERY.get(section or "") or text)[:200], "top_k": 3}})
    return plan


def pct(v: float | None) -> str:
    return "—" if v is None else f"{round(v * 100, 1):g}%"


def _metrics(state: WorkState) -> list[dict]:
    for r in state.get("tool_results", []):
        if r["tool"] == "get_rejoin_metrics" and r["payload"]["ok"]:
            return r["payload"]["data"]["rows"]
    return []


def fixture_answer(state: WorkState) -> str:
    lines: list[str] = []
    rows = _metrics(state)
    if rows:
        lines.append("지표 현황 기준으로 첫 모임 규모별 30일 재참여율을 확인했어요.")
        for r in rows:
            lines.append(f"- {r['label']}: {r['first_time_participants']}명 중 {r['rejoined_within_30d']}명, {pct(r['rejoin_rate'])}")
        lines.append("규모가 클수록 낮게 나오지만, 이 수치만으로 규모가 원인이라고 단정하긴 어려워요.")
    notes = [r for r in state.get("tool_results", []) if r["tool"] == "get_interview_notes" and r["payload"]["ok"]]
    if notes:
        items = notes[0]["payload"]["data"]["items"]
        lines.append("인터뷰에서는 " + " / ".join(f"{i['id']} “{i['quote']}”" for i in items[:3]))
        lines.append("(8명 인터뷰라 전체 비중으로 일반화하긴 어려워요.)")
    docs = [r for r in state.get("tool_results", []) if r["tool"] == "search_docs" and r["payload"]["ok"]]
    if docs and docs[0]["payload"]["data"]["matches"]:
        for m in docs[0]["payload"]["data"]["matches"][:2]:
            lines.append(f"관련 문서({m['title']}): “{m['quote'][:120]}”")
    for e in [r for r in state.get("tool_results", []) if not r["payload"]["ok"]]:
        lines.append(f"- {e['tool']}는 확인하지 못했어요({e['payload']['error']['code']}).")
    if state.get("kind") != "ASSISTANT":
        lines.append("어떤 방향으로 볼지는 정해 주시면 거기에 맞춰 더 찾아볼게요.")
    return "\n".join(lines)


def section_draft(state: WorkState, section: str) -> str:
    """Deterministic, document-style section body built only from tool results and company documents."""
    rows = {r["segment"]: r for r in _metrics(state)}
    if section == "similar_cases":
        return ("- 같이달려(가상, 동네 운동 모임 앱): 첫 참가자에게 짝꿍을 매칭해 처음 온 사람의 어색함을 줄이는 방식 (지난주 회의록)\n"
                "- 한바퀴(가상, 걷기 모임 앱): 모임이 끝나면 다음 모임 일정을 자동으로 안내하는 방식 (지난주 회의록)\n"
                "- 비교 기준(안): 첫 참가자 적응 지원 여부, 다음 일정 안내 방식, 모임 리더 운영 부담, 무료 제공 가능 여부(운영 정책)\n"
                "- 한계: 두 사례의 효과 수치는 확인되지 않음 (지난주 회의록)")
    if section == "metrics_timeline":
        lines = ["- 핵심 지표: 첫 모임 참가자의 30일 내 두 번째 모임 참가율(재참여율), 현재 22% · 분모는 첫 모임 참가자 (지표 현황)"]
        if rows:
            lines.append("- 보조 지표: 첫 모임 규모별 재참여율 — " + ", ".join(f"{r['label']} {pct(r['rejoin_rate'])}" for r in rows.values()) + " (지표 현황)")
        lines += ["- 목표치: 기능 범위 확정 후 설정 필요(현재 근거 자료 없음)",
                  "- 출시 일정: 설계 → 개발 → 베타 순서로 진행하며 구체 일정은 개발 리드와 확정 필요 (지난주 회의록)"]
        return "\n".join(lines)
    pivot = (state["facts"]["ctx"].get("scenario_state") or {}).get("pivot_text")
    if section == "features":
        target = "3개월 이상 미참여 사용자" if pivot else "첫 모임 참가자"
        return (f"- 다음 모임 일정 안내: 모임 종료 후 같은 모임의 다음 일정을 앱에서 안내 — 다음 일정을 놓쳤다는 의견 (사용자 인터뷰 요약), "
                "'한바퀴'의 다음 모임 자동 안내 사례 (지난주 회의록)\n"
                "- 첫 참가자 연결: 처음 온 참가자와 기존 참가자를 짝으로 연결 — 아는 사람이 없어 어색했다는 의견 (사용자 인터뷰 요약), "
                "'같이달려'의 짝꿍 매칭 사례 (지난주 회의록)\n"
                "- 출발 위치 안내는 동네 단위 공개 정책 범위 안에서만 검토 (운영 정책)\n"
                "- 유료 혜택은 제외: 올해 유료 기능 출시 불가 (운영 정책)\n"
                f"- 대상: {target}. 기능 선택과 우선순위는 담당자가 확정 필요")
    if section == "interview_evidence":
        return ("- 아는 사람이 없어 어색했다는 의견: INT-01, INT-03, INT-06 (사용자 인터뷰 요약)\n"
                "- 다음 모임 일정을 놓쳤다는 의견: INT-02, INT-05, INT-07 (사용자 인터뷰 요약)\n"
                "- 리더의 환영과 단톡방 초대가 재참여 의향으로 이어졌다는 의견: INT-04 (사용자 인터뷰 요약)\n"
                "- 한계: 8명 인터뷰로 전체 사용자 의견 비중을 대표하지 않음 (사용자 인터뷰 요약)")
    if section == "problem":
        target = "3개월 이상 모임에 참여하지 않은 사용자(팀장 요구사항 변경)" if pivot else "첫 모임 참가자"
        return (f"- 대상 사용자: {target}\n"
                "- 현황: 첫 모임 참가자의 30일 내 재참여율 22% (지표 현황)\n"
                "- 문제 정의와 우선순위는 담당자가 확정 필요")
    return to_doc(fixture_answer(state))


def to_doc(text: str) -> str:
    return H.to_document_body(text)


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
    scen = state["facts"]["ctx"].get("scenario_state") or {}
    if intent == "revise_request":
        return {"plan": []}
    if S.llm_mode != "live":
        if intent in ("answer_request", "conversation"):
            return {"plan": []}
        if not state.get("tool_results"):
            if intent == "policy_recheck":
                return {"plan": [{"tool": "search_docs", "args": {"query": "올해 유료 기능 출시 정책", "document_ids": ["operating-policy"], "top_k": 1}}]}
            sec = (state["facts"]["ctx"].get("task") or {}).get("template_key") if intent == "delegated" else None
            return {"plan": fixture_plan(state["request"], sec, released=scen.get("interviews_released", False))}
        return {}
    if intent == "answer_request" and not state.get("llm_messages"):
        return {"plan": []}
    # live: real gpt-4o-mini tool selection
    msgs = state.get("llm_messages") or []
    if not msgs:
        ctx = state["facts"]["ctx"]
        name = "assistant-v2" if state["kind"] == "ASSISTANT" else "colleague-v2"
        system, _ = H.load_prompt(name)
        pack = H.build_context(system, ctx["public_brief"]["public_brief"], ctx["messages"], [],
                               ctx.get("delegation"), H.rule_summary)
        scen = ctx.get("scenario_state") or {}
        extra = []
        if not scen.get("interviews_released"):
            extra.append("[아직 공유되지 않은 자료] 사용자 인터뷰 요약 — 내용을 본 것처럼 말하거나 인용하지 말 것. 01:05 이후 공유 예정.")
        wanted = [d for d, words in DOC_HINTS.items() if any(w in state["request"] for w in words)]
        if state["intent"] == "policy_recheck" and "operating-policy" not in wanted:
            wanted.append("operating-policy")
        for doc_id in wanted[:2]:
            if doc_id == "user-interviews" and not scen.get("interviews_released"):
                continue
            t0 = time.monotonic()
            tcid = f"rr-{uuid.uuid4().hex[:8]}"
            gw.event(state["run_id"], "TOOL_START", {"tool_call_id": tcid, "tool_name": "read_resource"}, key=f"start:{tcid}")
            text = read_resource(gw, state["run_id"], doc_id)
            gw.event(state["run_id"], "TOOL_END", {"tool_name": "read_resource", "safe_args": {"uri": f"doc://moarun-rejoin-v1/{doc_id}"},
                                                   "outcome": "ok", "result_summary": {"chars": len(text)}, "citations": [],
                                                   "help_id": state["help_id"], "duration_ms": int((time.monotonic() - t0) * 1000)},
                     key=f"end:{tcid}")
            extra.append(f"[{DOC_TITLE[doc_id]} 원문 — Host가 Resource로 읽어 주입]\n{text}")
            body = text.split("-->")[-1].strip()
            first = body.split("\n")[0]
            state.setdefault("citations", []).append({"document_id": doc_id, "chunk_id": None, "version": 1,
                                                       "quote": first.split(". ")[0].rstrip(".") + "."})
        art = (ctx.get("artifact") or {}).get("sections") or {}
        doc_lines = [f"{i + 1}. {SECTION_TITLE[k]}\n{H.truncate_tokens(art.get(k) or '(비어 있음)', 500)}"
                     for i, k in enumerate(["problem", "interview_evidence", "features", "similar_cases", "metrics_timeline"])]
        extra.append("[현재 공유 기획안 — 섹션 번호는 아래 순서]\n" + "\n\n".join(doc_lines))
        if state["intent"] == "feedback":
            extra.append("[지시] 지원자가 작성한 섹션에 대한 피드백을 요청했다. 위 기획안 본문을 지금 읽고 이 메시지 안에서 바로 피드백하라. "
                         "'확인해 볼게요', '잠시만 기다려 주세요'처럼 나중으로 미루지 마라. 좋은 점 1개와 보완할 점 1~2개를 회사 자료 근거와 함께 "
                         "구체적으로 말하고, 최종 결정은 지원자에게 맡겨라. 섹션이 비어 있으면 비어 있다고 말하라.")
        speaker = {"CANDIDATE": "지원자", "MANAGER": "팀장 한서윤", "SYSTEM": "시스템 알림", "COLLEAGUE": "이도현", "ASSISTANT": "AI 어시스턴트"}
        msgs = [{"role": "system", "content": system},
                {"role": "user", "content": H.mask_pii(pack.render_user_context() + ("\n\n" + "\n\n".join(extra) if extra else ""))}]
        for m in pack.messages:
            if m["actor"] in ("COLLEAGUE", "ASSISTANT"):
                msgs.append({"role": "assistant", "content": H.mask_pii(m["content"])})
            else:
                msgs.append({"role": "user", "content": H.mask_pii(f"({speaker.get(m['actor'], m['actor'])}) {m['content']}")})
        if state["kind"] == "DELEGATED":
            sec = state["facts"]["ctx"]["task"]["template_key"]
            msgs.append({"role": "user", "content": f"[분담 작업] 네가 맡은 '{state['request']}'({sec}) 섹션 초안을 회사 문서 근거로 작성하라. "
                                                    "문서에 없는 수치나 회사 정보는 쓰지 말고, 참조 문서명을 괄호로 적어라."})
        elif state["intent"] == "policy_recheck":
            msgs.append({"role": "user", "content": "[지시] 지원자가 네 유료 멤버십 제안의 재검토를 요청했다. 위 운영 정책 원문을 근거로 "
                                                    "충돌 여부를 확인하고, 충돌하면 정책 문장을 인용해 인정하고 제안을 철회·정정하라."})
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
            "citations": state.get("citations", []),
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
        if tool not in {"get_rejoin_metrics", "get_interview_notes", "search_docs"}:
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
        return {"answer": "제가 정답을 정하기보다는 같이 근거를 보고 정하시는 게 좋을 것 같아요. 어떤 자료부터 볼까요? "
                          "지표 현황, 운영 정책, 회의록 중에 골라 주시면 정리해 드릴게요."}
    if intent == "revise_request":
        scen = state["facts"]["ctx"].get("scenario_state") or {}
        recent = [m["content"] for m in state["facts"]["ctx"]["messages"][-5:-1]]
        secs = requested_sections(state["request"], scen, recent)
        if not secs:
            return {"answer": "어느 섹션을 고치면 될지 알려 주시겠어요? 제가 맡은 섹션이 아직 없어서 바로 시작하기 어려워요."}
        r = gw.post(f"/runs/{state['run_id']}/followup", {"sections": secs, "instruction": state["request"][:2000]})
        made = [SECTION_TITLE[x] for x in r.get("created", [])]
        busy = [SECTION_TITLE[x] for x in r.get("skipped", [])]
        parts = []
        if made:
            parts.append(f"네, {', '.join(made)} 섹션을 지금 내용과 요청하신 점을 확인해서 다시 작성할게요. "
                         "다 쓰면 문서에 넣기 전에 기획안 탭에서 확인 요청을 드릴게요.")
        if busy:
            parts.append(f"{', '.join(busy)} 섹션은 이미 작업 중이라 그 결과가 나오면 함께 봐 주세요.")
        return {"answer": " ".join(parts) or "지금은 수정할 섹션을 찾지 못했어요. 섹션 이름을 알려 주시겠어요?"}
    if intent == "policy_recheck" and S.llm_mode != "live":
        quote = ""
        for r in state.get("tool_results", []):
            if r["tool"] == "search_docs" and r["payload"]["ok"] and r["payload"]["data"]["matches"]:
                quote = r["payload"]["data"]["matches"][0]["quote"]
        text = ("말씀 듣고 운영 정책 문서를 다시 확인했어요." + (f" “{quote[:80]}”라고 되어 있네요." if quote else "") +
                " 제가 제안한 유료 멤버십은 올해 정책과 맞지 않아서 철회할게요. 짚어 주셔서 감사합니다. "
                "대신 결제 없이 재참여를 돕는 방향으로 같이 다시 생각해 보면 좋겠어요.")
        return {"answer": text, "facts": {**state["facts"], "corrected": True}}
    if intent == "feedback" and S.llm_mode != "live":
        art = (state["facts"]["ctx"].get("artifact") or {}).get("sections") or {}
        filled = [SECTION_TITLE[k] for k in ["problem", "interview_evidence", "features", "similar_cases", "metrics_timeline"] if (art.get(k) or "").strip()]
        if not filled:
            return {"answer": "지금 기획안을 열어 보니 아직 작성된 섹션이 없어요. 작성하신 뒤 말씀해 주시면 바로 볼게요."}
        return {"answer": f"방금 기획안을 확인했어요. {', '.join(filled)} 섹션이 작성되어 있네요. 지표 현황의 재참여율 22%와 연결해 대상과 문제를 "
                          "조금 더 구체적으로 적으면 좋을 것 같아요. 어떻게 반영할지는 직접 정해 주세요."}
    if intent == "conversation" and S.llm_mode != "live":
        return {"answer": "말씀 감사해요. 그 방향으로 생각해 볼게요. 필요하신 자료가 있으면 편하게 말씀해 주세요."}
    text = (state.get("answer") or "") if S.llm_mode == "live" else fixture_answer(state)
    text = re.sub(r"^\s*[\[(](COLLEAGUE|ASSISTANT|이도현|AI 어시스턴트)[\])]\s*", "", text)
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
            return {"answer": H.SAFE_FALLBACK, "output_rewrite_count": rewrites + 1, "error_code": "OUTPUT_VALIDATION"}
    if state.get("limited"):
        text += f"\n(도구 사용 한도 {state['limited']}에 도달해 여기까지만 확인했어요.)"
    scen = state["facts"]["ctx"].get("scenario_state") or {}
    if state["kind"] == "COLLEAGUE" and scen.get("split_confirmed") and PROMISE_RE.search(text):
        recent = [m["content"] for m in state["facts"]["ctx"]["messages"][-5:-1]]
        secs = requested_sections(state["request"] + " " + text, scen, recent)
        r = gw.post(f"/runs/{state['run_id']}/followup", {"sections": secs, "instruction": state["request"][:2000]}) if secs else {"created": []}
        if r.get("created"):
            text += f"\n(지금 {', '.join(SECTION_TITLE[x] for x in r['created'])} 섹션 작성을 시작했어요. 완성되면 기획안 탭에서 확인 요청을 드릴게요.)"
        elif not r.get("skipped"):
            text = PROMISE_RE.sub("검토", text) + "\n(바로 작성할 섹션을 정하지 못했어요. 어느 섹션을 맡기실지 알려 주세요.)"
    out = {"answer": text, "output_rewrite_count": rewrites + (1 if problems else 0)}
    if intent == "policy_recheck" and re.search(r"(철회|제외|빼|맞지 않|충돌|수정|정정)", text):
        out["facts"] = {**state["facts"], "corrected": True}
    return out


_DOC_NUMBERS: set[str] = set()


def _public_doc_numbers() -> set[str]:
    """Numbers stated in the shared company documents (e.g. 30일, 22%, 30,000명) are grounded facts."""
    if not _DOC_NUMBERS:
        from shared.config import DATA_DIR
        for f in (DATA_DIR / "documents").glob("*.md"):
            _DOC_NUMBERS.update(H.numbers_in(f.read_text(encoding="utf-8")))
    return _DOC_NUMBERS


def _allowed_numbers(state: WorkState) -> set[str]:
    """Numbers present in tool results/request/company documents, plus pp differences derived from returned rates."""
    allowed = set().union(*[H.numbers_in(r["payload"]) for r in state.get("tool_results", [])] or [set()])
    allowed |= _public_doc_numbers()
    allowed |= H.numbers_in(state.get("request", ""))
    rates = [row["rejoin_rate"] for r in state.get("tool_results", []) if r["tool"] == "get_rejoin_metrics" and r["payload"]["ok"]
             for row in r["payload"]["data"]["rows"] if row["rejoin_rate"] is not None]
    allowed |= {"30000", "4000", "880"}  # 지표 현황 문서의 공개 수치
    for x in rates:
        for y in rates:
            allowed.add(f"{abs(round((x - y) * 100, 1))}")
    return allowed


@_timed
def respond(state: WorkState) -> dict:
    etype = "ASSISTANT_MESSAGE" if state["kind"] == "ASSISTANT" else "COLLEAGUE_MESSAGE"
    content = state["answer"] if state["kind"] == "ASSISTANT" else H.to_chat_plain(state["answer"])
    payload: dict[str, Any] = {"content": content, "citations": _dedupe(state.get("citations", []))[:8]}
    if state.get("facts", {}).get("corrected"):
        payload["kind"] = "ERROR_CORRECTED"
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

SECTION_TITLE = {"problem": "문제 정의와 대상 사용자", "interview_evidence": "사용자 인터뷰에서 찾은 근거", "features": "핵심 기능 제안",
                 "similar_cases": "비슷한 서비스 사례", "metrics_timeline": "성공 지표와 출시 일정"}


def write_section_live(state: WorkState, section: str, current: str) -> tuple[str, dict]:
    """Separate document-writing step: section body only, from collected evidence (not the chat reply)."""
    from langchain_core.messages import HumanMessage, SystemMessage
    system, _ = H.load_prompt("section-writer-v1")
    evidence = "\n\n".join(f"[{r['tool']}] {H.tool_message_content(r['payload'])}" for r in state.get("tool_results", []) if r["payload"]["ok"])
    run_input = state["facts"]["ctx"]["run"]["input"] or {}
    revise = run_input.get("revise_comment")
    rewrite = run_input.get("mode") == "rewrite" or bool(revise)
    pivot = (state["facts"]["ctx"].get("scenario_state") or {}).get("pivot_text")
    task = ("현재 섹션 내용을 하나씩 검토해 수정 요청을 반영한 **섹션 전체 본문**을 다시 작성하라. 근거와 맞지 않거나 "
            "근거 없이 단정한 문장은 고치거나 빼고, 유지할 내용은 다시 포함하라. 같은 내용을 반복하지 마라."
            if rewrite else "위 근거만으로 이 섹션에 추가할 본문을 작성하라.")
    user = (f"[섹션] {SECTION_TITLE.get(section, section)}\n[현재 섹션 내용]\n{current or '(비어 있음)'}\n"
            + (f"[지원자 수정 요청]\n{revise}\n" if revise else "")
            + (f"[팀장 요구사항 변경]\n{pivot}\n" if pivot else "")
            + ("[최근 팀 대화 — 논의된 아이디어는 반영하되 근거 자료와 맞는지 확인]\n"
               + "\n".join(f"({m['actor']}) {H.truncate_tokens(m['content'], 120)}" for m in state["facts"]["ctx"]["messages"][-8:]) + "\n")
            + f"[근거 자료]\n{H.truncate_tokens(evidence, 3000) or '(없음)'}\n\n{task}")
    deadline = time.monotonic() + max(1.0, (H.ACTIVE_BUDGET_MS - state.get("active_execution_ms", 0)) / 1000)
    ai = H.with_retries(lambda: llm().invoke([SystemMessage(system), HumanMessage(H.mask_pii(user))]), deadline=deadline)
    um = getattr(ai, "usage_metadata", None) or {}
    usage = dict(state.get("token_usage") or {"input": 0, "output": 0})
    usage["input"] += um.get("input_tokens", 0)
    usage["output"] += um.get("output_tokens", 0)
    return H.to_document_body(ai.content or ""), usage


@_timed
def draft_delegation(state: WorkState) -> dict:
    ctx = state["facts"]["ctx"]
    section = ctx["task"]["template_key"]
    art = ctx["artifact"]
    current = art["sections"].get(section, "")
    usage = state.get("token_usage")
    body, mode = "", "fixture"
    if S.llm_mode == "live":
        body, usage = write_section_live(state, section, current)
        mode = "live"
    allowed = _allowed_numbers(state) | H.numbers_in(current)
    if not body or H.validate_output(body, allowed) or H.ungrounded_units(body, allowed):
        body, mode = section_draft(state, section), ("fallback" if mode == "live" else "fixture")
    run_input = ctx["run"]["input"] or {}
    rewrite = run_input.get("mode") == "rewrite" or bool(run_input.get("revise_comment"))
    # 수정 요청은 섹션 전체 재작성(확인 카드에서 변경 전/후 비교), 첫 초안만 기존 내용 뒤에 추가
    content = body if rewrite else (current.rstrip() + "\n" if current.strip() else "") + body
    cits = [c for c in _dedupe(state.get("citations", [])) if c.get("document_id") not in ("rejoin_facts", "interview_notes")][:5]
    args = {"task_id": state["task_id"], "section": section, "base_version": art["version"], "content": content,
            "citations": [{"document_id": c["document_id"], "chunk_id": c.get("chunk_id"), "version": c.get("version", 1),
                           "quote": c["quote"]} for c in cits]}
    gw.event(state["run_id"], "TASK_RESULT", {"result": {"summary": body, "citations": cits, "draft_mode": mode}}, key="task-result")
    return {"proposed_action": {"tool_name": "patch_artifact_section", "args": args,
                                "base_versions": {"artifact": art["version"]}}, "answer": body, "token_usage": usage}


@_timed
def persist_proposal(state: WorkState) -> dict:
    """Idempotent approval creation BEFORE interrupt (same interrupt_id on replay)."""
    pa = state["proposed_action"]
    r = gw.post(f"/runs/{state['run_id']}/proposal", {"interrupt_id": "section-patch-1", "tool_name": pa["tool_name"],
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
    gw.event(state["run_id"], "TOOL_END", {"tool_name": pa["tool_name"], "safe_args": {"section": pa["args"]["section"], "task_id": state["task_id"]},
                                           "outcome": "ok" if payload["ok"] else payload["error"]["code"],
                                           "result_summary": payload.get("data") or {}, "citations": [], "help_id": "H3",
                                           "duration_ms": ms}, key=f"write:{state['approval_id']}")
    if payload["ok"]:
        text = "확인해 주셔서 감사해요. 제 담당 섹션에 초안을 반영했어요. 그대로 쓸지, 수정 요청할지는 태스크 보드에서 정해 주세요."
    else:
        code = payload["error"]["code"]
        text = ("승인 대기 중 기획안이 바뀌어 반영하지 않았습니다(APPROVAL_STALE). 필요하면 수정 요청으로 다시 조사하겠습니다."
                if code == "VERSION_CONFLICT" else f"변경을 반영하지 못했습니다({code}). 문서는 바뀌지 않았습니다.")
    return {"answer": text, "error_code": None if payload["ok"] else payload["error"]["code"]}


@_timed
def record_rejection(state: WorkState) -> dict:
    return {"answer": "알겠어요, 문서에는 넣지 않았어요. 초안은 태스크 카드에 남겨 둘게요. 어떤 점을 바꾸면 좋을지 말씀해 주시면 고쳐 볼게요."}


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

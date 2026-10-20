"""Harness 8요소 평가 실행기. 결과를 evals/results/{suite}-{label}.json 으로 저장한다.

uv run python -m scripts.eval_harness --suite harness-v1 --label baseline
모델 호출은 하지 않는다(fixture 재현). H-STATE/H-OBS는 실행 중 DB·LangSmith 기록을 대조한다.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from shared.config import PROMPTS_DIR, ROOT, settings
from shared.db import all_, one, tx

from agent.app import harness as H

S = settings()


def h_ins() -> dict:
    names = ["colleague-v2", "assistant-v2", "section-writer-v1", "summary-v1", "report-v1"]
    hashes = {n: H.load_prompt(n)[1] for n in names}
    H.load_prompt.cache_clear()
    stable = all(H.load_prompt(n)[1] == h for n, h in hashes.items())
    code = "".join(p.read_text() for p in (ROOT / "services" / "agent" / "app").glob("*.py"))
    no_inline = "너는 루프랩 프로덕트팀" not in code and "## 반드시 지킬 것" not in code
    colleague = (PROMPTS_DIR / "colleague-v2.md").read_text()
    forbids = all(w in colleague for w in ("평가", "점수", "누설") ) or ("평가 의도" in colleague and "점수" in colleague)
    from gateway.app.internal.routes import READ_TOOLS, WRITE_TOOLS
    assistant_no_write = not (READ_TOOLS & WRITE_TOOLS)
    return {"pass": stable and no_inline and forbids and assistant_no_write,
            "detail": {"prompt_hashes": hashes, "hash_stable": stable, "no_inline_system_prompt": no_inline,
                       "forbidden_rules_in_prompt": forbids, "assistant_read_only_toolset": assistant_no_write}}


def h_tool() -> dict:
    big = {"ok": True, "data": {"rows": [{"quote": "가" * 50, "n": i} for i in range(2000)]}, "error": None, "citations": []}
    out = H.tool_message_content(big)
    truncated = H.count_tokens(out) <= H.TOOL_RESULT_TOKEN_LIMIT + 10 and out.endswith("…(잘림)")
    err = H.tool_message_content({"ok": False, "data": None, "error": {"code": "NOT_FOUND", "message": "아직 공유되지 않았습니다", "retryable": False}, "citations": []})
    err_ok = '"code": "NOT_FOUND"' in err
    masked = H.mask_pii("연락처 test.user@example.com, 010-1234-5678")
    pii_ok = "@" not in masked and "1234" not in masked
    return {"pass": truncated and err_ok and pii_ok,
            "detail": {"truncated_tokens": H.count_tokens(out), "error_tool_message": err[:120], "masked": masked}}


def h_ctx() -> dict:
    msgs = [{"id": f"m{i}", "actor": "CANDIDATE" if i % 2 else "COLLEAGUE", "content": "재참여율 관련 논의 " * 120} for i in range(30)]
    pack = H.build_context("system", "brief", msgs, [{"chunk_id": "c1", "quote": "x" * 200}], None, H.rule_summary)
    under = pack.total_tokens() <= H.INPUT_TOKEN_BUDGET
    summary_ok = bool(pack.summary) and "[msg:m0]" in pack.summary and H.count_tokens(pack.summary) <= H.SUMMARY_TOKEN_LIMIT + 10
    return {"pass": under and summary_ok and len(pack.messages) <= H.MAX_RECENT_MESSAGES,
            "detail": {"total_tokens": pack.total_tokens(), "recent_messages": len(pack.messages),
                       "summarized_ids": len(pack.summarized_ids), "summary_tokens": H.count_tokens(pack.summary or "")}}


def h_state() -> dict:
    """대기 중 승인 run이 있으면 checkpoint 상태를 같은 thread_id로 조회해 다음 노드를 확인."""
    from langgraph.checkpoint.postgres import PostgresSaver
    from psycopg import Connection
    from psycopg.rows import dict_row
    from agent.app import graph as G
    with tx(S.psycopg_dsn) as c:
        r = one(c, "SELECT id, thread_id FROM runs WHERE status='WAITING_APPROVAL' ORDER BY updated_at DESC LIMIT 1")
        rows = one(c, "SELECT count(*) AS n FROM checkpoints.checkpoints")
    if not r:
        return {"pass": None, "detail": {"note": "WAITING_APPROVAL run 없음 — 승인 대기 상태를 만든 뒤 다시 실행", "checkpoints": rows["n"]}}
    conn = Connection.connect(S.checkpoint_database_url, autocommit=True, prepare_threshold=0, row_factory=dict_row)
    app = G.build(PostgresSaver(conn))
    st = app.get_state({"configurable": {"thread_id": r["thread_id"]}})
    nxt = list(st.next or [])
    return {"pass": "await_approval" in nxt, "detail": {"run_id": str(r["id"]), "thread_id": r["thread_id"], "next": nxt,
                                                         "approval_id": st.values.get("approval_id"), "checkpoints": rows["n"]}}


def h_loop() -> dict:
    cases = {"MAX_STEPS": ({}, "search_docs", 8, 0), "MAX_TOOL_CALLS": ({"a": 2, "b": 3}, "c", 1, 0),
             "MAX_SAME_TOOL": ({"search_docs": 3}, "search_docs", 1, 0), "ACTIVE_TIME_BUDGET": ({}, "x", 1, 120_000)}
    got = {}
    for name, (counts, tool, steps, ms) in cases.items():
        try:
            H.check_tool_budget(counts, tool, steps, ms)
            got[name] = None
        except H.LimitExceeded as e:
            got[name] = e.reason
    ok_under = True
    try:
        H.check_tool_budget({"search_docs": 1}, "get_rejoin_metrics", 2, 1000)
    except H.LimitExceeded:
        ok_under = False
    return {"pass": all(got[k] == k for k in cases) and ok_under, "detail": {"limits": got, "under_limit_allowed": ok_under}}


def h_guard() -> dict:
    allowed = {"22", "31", "24", "15.5", "30"}
    num = H.validate_output("재참여율 22%에서 4500명으로", allowed)
    unit = H.ungrounded_units("목표 재참여율 35%, 개발 6주", allowed)
    judge = H.validate_output("정답은 소규모 모임입니다", allowed)
    md = H.to_chat_plain("**소규모**\n1. 첫째\n- 둘째\n### 제목")
    md_ok = all(t not in md for t in ("**", "1.", "###")) and "- " not in md
    # 승인 없는 변경 도구는 gateway가 거절(실행 중 MCP 스모크에서도 검증)
    from gateway.app.internal.routes import execute_write
    from gateway.app.business import ToolError
    try:
        execute_write(None, "s", {"id": "r"}, {}, "patch_artifact_section", {})  # capability에 approval_id 없음
        blocked = False
    except ToolError as e:
        blocked = e.code == "APPROVAL_REQUIRED"
    return {"pass": bool(num) and len(unit) == 2 and bool(judge) and md_ok and blocked,
            "detail": {"ungrounded_number": num, "ungrounded_units": unit, "judgement_blocked": judge,
                       "chat_plain": md, "write_without_approval_blocked": blocked}}


def h_rec() -> dict:
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("Error code: 429 rate limit")
        return "ok"
    t0 = time.monotonic()
    r1 = H.with_retries(flaky, deadline=time.monotonic() + 30)
    n_ok = calls["n"]
    calls["n"] = 0

    def always():
        calls["n"] += 1
        raise RuntimeError("503 Service Unavailable")
    try:
        H.with_retries(always, deadline=time.monotonic() + 30)
        r2 = "no-raise"
    except RuntimeError:
        r2 = "raised"
    n_fail = calls["n"]
    calls["n"] = 0

    def fatal():
        calls["n"] += 1
        raise ValueError("invalid request")
    try:
        H.with_retries(fatal, deadline=time.monotonic() + 30)
    except ValueError:
        pass
    n_fatal = calls["n"]
    elapsed = round(time.monotonic() - t0, 1)
    same_model = S.openai_model == "gpt-4o-mini"
    return {"pass": r1 == "ok" and n_ok == 3 and r2 == "raised" and n_fail == 3 and n_fatal == 1 and same_model,
            "detail": {"429_then_ok_calls": n_ok, "503_always_calls": n_fail, "503_result": r2, "non_retryable_calls": n_fatal,
                       "elapsed_s": elapsed, "model_fixed": S.openai_model}}


def h_obs() -> dict:
    with tx(S.psycopg_dsn) as c:
        runs = all_(c, """SELECT id, trace_id, token_usage FROM runs WHERE kind<>'REPORT' AND status='SUCCEEDED'
                          ORDER BY updated_at DESC LIMIT 20""")
    with_trace = sum(1 for r in runs if r["trace_id"])
    with_tokens = sum(1 for r in runs if (r["token_usage"] or {}).get("input"))
    ls = {"enabled": S.langsmith_enabled}
    if S.langsmith_enabled and runs:
        try:
            from langsmith import Client
            ids = {str(r["id"]) for r in runs}
            found = set()
            for tr in Client().list_runs(project_name=S.langsmith_project, is_root=True, limit=100):
                rid = ((tr.extra or {}).get("metadata") or {}).get("run_id")
                if rid in ids:
                    found.add(rid)
            ls.update({"matched_runs": len(found), "checked_runs": len(ids)})
        except Exception as e:  # noqa: BLE001
            ls["error"] = type(e).__name__
    passed = bool(runs) and with_trace == len(runs) and (not S.langsmith_enabled or ls.get("matched_runs", 0) > 0)
    return {"pass": passed, "detail": {"recent_runs": len(runs), "with_trace_id": with_trace, "with_token_usage": with_tokens, "langsmith": ls}}


CHECKS = {"H-INS": h_ins, "H-TOOL": h_tool, "H-CTX": h_ctx, "H-STATE": h_state, "H-LOOP": h_loop,
          "H-GUARD": h_guard, "H-REC": h_rec, "H-OBS": h_obs}


def main() -> None:
    ap = argparse.ArgumentParser(); ap.add_argument("--suite", default="harness-v1"); ap.add_argument("--label", default="baseline")
    a = ap.parse_args()
    suite = json.loads((ROOT / "evals" / f"{a.suite}.json").read_text())
    results = []
    for case in suite["cases"]:
        try:
            r = CHECKS[case["id"]]()
        except Exception as e:  # noqa: BLE001
            r = {"pass": False, "detail": {"exception": f"{type(e).__name__}: {e}"[:300]}}
        status = "PASS" if r["pass"] is True else ("NOT_RUN" if r["pass"] is None else "FAIL")
        results.append({"id": case["id"], "element": case["element"], "status": status, **r})
        print(f"{status:8} {case['id']:8} {case['element']}")
    out = {"suite": a.suite, "label": a.label, "ran_at": datetime.now(timezone.utc).isoformat(), "mode": S.llm_mode,
           "summary": {s: sum(1 for r in results if r["status"] == s) for s in ("PASS", "FAIL", "NOT_RUN")}, "results": results}
    p = ROOT / "evals" / "results" / f"{a.suite}-{a.label}.json"
    p.write_text(json.dumps(out, ensure_ascii=False, indent=2, default=str))
    print(f"\n{out['summary']} → {p.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

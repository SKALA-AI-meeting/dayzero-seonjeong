"""REPORT job: 규칙 기반 관찰 리포트(gateway) → (live) 역량별 근거 요약 1문장(선택).

관찰 코드·근거 원문·이벤트는 코드가 구성한다. LLM은 관찰된 역량의 '근거 요약'만 만들고,
판정·점수 표현이 있거나 실패하면 버린다(리포트는 RULES 그대로 유지).
"""
from __future__ import annotations

import json
import logging
import re
import time

from shared.config import settings

from . import harness as H
from .clients import Gateway

log = logging.getLogger("agent.report")
S = settings()
BANNED = re.compile(r"(점수|등급|순위|합격|불합격|탈락|채용\s*추천|우수|부족한\s*지원자|성격|뛰어|훌륭|미흡)")


def run_report(gw: Gateway, job: dict) -> None:
    sid, report_id = job["session_id"], job["input"]["report_id"]
    r = gw.post(f"/reports/{sid}/build", {"report_id": report_id})
    if r.get("status") != "READY":
        raise RuntimeError(f"report build failed: {r.get('status')}")  # worker가 리포트를 FAILED로 표시 → 관리자 재시도
    if S.llm_mode != "live":
        return
    try:
        body = gw.get(f"/reports/{sid}/body")["body"]
        items = {c["key"]: [{"code": o["code"], "definition": o["definition"], "event": o["event_id"],
                             "evidence": (o["evidence"].get("quote") or o["note"] or "")[:200]} for o in c["observations"]]
                 for c in body["competencies"] if c["status"] == "OBSERVED"}
        if not items:
            return
        from langchain_core.messages import HumanMessage, SystemMessage
        from langchain_openai import ChatOpenAI
        system, _ = H.load_prompt("report-summary-v1")
        llm = ChatOpenAI(model=S.openai_model, max_tokens=H.OUTPUT_TOKEN_BUDGET, timeout=40, max_retries=0, temperature=0,
                         model_kwargs={"response_format": {"type": "json_object"}})
        ai = H.with_retries(lambda: llm.invoke([SystemMessage(system), HumanMessage(H.mask_pii(json.dumps(items, ensure_ascii=False)))]),
                            deadline=time.monotonic() + 100)
        out = json.loads(ai.content or "{}").get("summaries", {})
        keep = {k: str(v)[:300] for k, v in out.items() if k in items and v and not BANNED.search(str(v))}
        if keep:
            gw.post(f"/reports/{sid}/summaries", {"report_id": report_id, "summaries": keep})
    except Exception as e:  # noqa: BLE001 — 요약 실패는 규칙 리포트를 유지
        log.warning("report summaries skipped: %s", e)

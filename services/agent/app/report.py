"""REPORT job: 규칙 기반 사실 리포트(gateway) → (live) LLM 제한 해석 추가.

사실·발생 기회·근거는 코드가 구성하고, LLM은 관찰된 영역의 '제한된 해석(추정)'과 '후속 확인점'만 생성한다.
판정·점수 표현이 있거나 실패하면 해석을 버리고 RULES_FALLBACK을 유지한다.
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
BANNED = re.compile(r"(점수|등급|순위|합격|불합격|탈락|채용\s*추천|우수한|부족한\s*지원자|성격)")


def run_report(gw: Gateway, job: dict) -> None:
    sid, report_id = job["session_id"], job["input"]["report_id"]
    r = gw.post(f"/reports/{sid}/build", {"report_id": report_id, "mode": "RULES_FALLBACK"})
    if r.get("status") not in ("READY",):
        raise RuntimeError(f"report build failed: {r.get('status')}")  # 큐 재시도 대상
    if S.llm_mode != "live":
        return
    try:
        body = gw.get(f"/reports/{sid}/body")["body"]
        items = [{"key": a["dimension"], "label": a["label"],
                  "situations": [x["situation"] for x in a["situations"] if x["status"] == "OBSERVED"],
                  "facts": [f"{f.get('at') or ''} {f['text']}" for f in a["facts"][:8]]}
                 for a in body["areas"] if a["status"] == "OBSERVED" and a["facts"]]
        if not items:
            return
        system, _ = H.load_prompt("report-v1")
        from langchain_core.messages import HumanMessage, SystemMessage
        from langchain_openai import ChatOpenAI
        llm = ChatOpenAI(model=S.openai_model, max_tokens=H.OUTPUT_TOKEN_BUDGET, timeout=40, max_retries=0, temperature=0.1,
                         model_kwargs={"response_format": {"type": "json_object"}})
        msg = H.mask_pii(json.dumps({"items": items}, ensure_ascii=False))
        ai = H.with_retries(lambda: llm.invoke([SystemMessage(system), HumanMessage(msg)]), deadline=time.monotonic() + 100)
        out = json.loads(ai.content or "{}").get("items", [])
        interp = {}
        for it in out:
            key, text, follow = it.get("key"), str(it.get("interpretation", ""))[:400], str(it.get("follow_up", ""))[:300]
            if key and text and not BANNED.search(text + follow):
                interp[key] = {"text": text, "label": "INFERENCE", "follow_up": follow}
        if interp:
            gw.post(f"/reports/{sid}/interpret", {"report_id": report_id, "interpretations": interp})
    except Exception as e:  # noqa: BLE001 — 해석 실패는 사실 리포트를 유지(RULES_FALLBACK)
        log.warning("report interpretation skipped: %s", e)

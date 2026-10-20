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


def _observe(llm, body: dict) -> list[dict]:
    """원자료를 보고 검토자용 사전 확인 사항('~한 부분에서 ~를 확인함')을 만든다. 판정 표현은 버린다."""
    raw = body.get("raw") or {}
    if not raw:
        return []
    from langchain_core.messages import HumanMessage, SystemMessage
    system, _ = H.load_prompt("report-observe-v1")
    slim = {"동료에게_한_요청": [{"시각": r.get("at"), "지원자_발화": r.get("request"), "동료_답변(지원자_발화_아님)": r.get("reply"),
                                "시작된_작업": r.get("work_started")} for r in raw.get("colleague_requests", [])],
            "확인_카드_결정(지원자)": [{"시각": c.get("at"), "섹션": c.get("section"), "결정": c.get("decision") or c.get("status"),
                                   "지원자_검토사항": c.get("comment")} for c in raw.get("card_decisions", [])],
            "태스크_검토(지원자)": raw.get("task_reviews", []),
            "기획안_수정이력": [{k: h.get(k) for k in ("at", "section", "actor", "chars_before", "chars_after")} for h in raw.get("revision_history", [])],
            "어시스턴트_대화": [{"시각": r.get("at"), "지원자_발화": r.get("request"), "어시스턴트_답변(지원자_발화_아님)": r.get("reply")}
                           for r in raw.get("assistant_log", [])]}
    cand_texts = [r.get("request") or "" for r in raw.get("colleague_requests", []) + raw.get("assistant_log", [])] + \
                 [c.get("comment") or "" for c in raw.get("card_decisions", [])] + [t.get("comment") or "" for t in raw.get("task_reviews", [])]
    msg = H.truncate_tokens(H.mask_pii(json.dumps(slim, ensure_ascii=False)), 5000)
    try:
        ai = H.with_retries(lambda: llm.invoke([SystemMessage(system), HumanMessage(msg)]), deadline=time.monotonic() + 100)
        out = json.loads(ai.content or "{}").get("observations", [])
    except Exception as e:  # noqa: BLE001
        log.warning("observations skipped: %s", e)
        return []
    keep = []
    for o in out:
        if not isinstance(o, dict) or not o.get("text") or BANNED.search(str(o.get("text"))) or len(str(o["text"])) < 12:
            continue
        q = str(o.get("quote") or "").strip().strip('"“”')
        if "태도" in str(o.get("area", "")):
            # 태도 항목은 인용문이 실제 지원자 발화에 있을 때만 남긴다(동료·어시스턴트 발화 오귀속 방지)
            if not q or not any(q[:20] in t for t in cand_texts if t):
                continue
        keep.append(o)
    return keep[:10]


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
        if not items and not (body.get("raw") or {}).get("colleague_requests"):
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
        observations = _observe(llm, body)
        if interp or observations:
            gw.post(f"/reports/{sid}/interpret", {"report_id": report_id, "interpretations": interp, "observations": observations})
    except Exception as e:  # noqa: BLE001 — 해석 실패는 사실 리포트를 유지(RULES_FALLBACK)
        log.warning("report interpretation skipped: %s", e)

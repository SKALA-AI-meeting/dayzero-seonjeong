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
from .clients import Gateway, search_company_criteria

log = logging.getLogger("agent.report")
S = settings()
BANNED = re.compile(r"(점수|등급|순위|합격|불합격|탈락|채용\s*추천|우수|부족한\s*지원자|성격|뛰어|훌륭|미흡)")


def _evidence_text(o: dict) -> str:
    """근거 원문 요약: 메시지는 원문 앞부분, 문서 수정은 '어떤 문서 수정'(diff 숫자·행동 코드명은 질의를 흐려 뺀다)."""
    e = o.get("evidence") or {}
    if e.get("kind") == "revision":
        return f"{e.get('artifact', '')} 수정"
    return (e.get("quote") or "")[:60]


def criteria_query(o: dict) -> str:
    """질의 = 코드 정의(첫 문장, '판정 없이 기록만' 같은 메모 제외) + 근거 원문 요약."""
    ev = _evidence_text(o)
    return f"{o['definition'].split('. ')[0]} — {ev}" if ev else o["definition"].split(". ")[0]


def link_company_criteria(gw: Gateway, sid: str, report_id: str, company_id: str, url: str) -> None:
    """관찰 코드마다 회사 기준 MCP의 search_criteria(질의 = 코드 정의 + 근거 원문 요약) 상위 1개를 linked_criterion으로 저장.
    회사는 job 입력의 URL로만 정해진다(회사별 분기 없음). 연결 실패 시 조항 없이 READY(리포트 본문은 유지)."""
    body = gw.get(f"/reports/{sid}/body")["body"]
    refs = [(c["key"], i, criteria_query(o))
            for c in body["competencies"] for i, o in enumerate(c["observations"])]
    links, name, err = [], None, None
    try:
        found = search_company_criteria(url, [q for _, _, q in refs]) if refs else []
        for (comp, i, _), cr in zip(refs, found):
            if cr:
                links.append({"competency": comp, "index": i, "criterion": cr})
                name = name or cr.get("company_name")
    except Exception as e:  # noqa: BLE001 — company-mcp 장애는 조항 연결만 생략
        err = f"company-mcp 호출 실패: {type(e).__name__}"
        log.warning("company criteria skipped: %s", e)
    gw.post(f"/reports/{sid}/criteria", {"report_id": report_id, "company_id": company_id, "company_name": name,
                                          "links": links, "error": err})


def run_report(gw: Gateway, job: dict) -> None:
    sid, report_id = job["session_id"], job["input"]["report_id"]
    company_id, company_url = job["input"].get("company_id"), job["input"].get("company_mcp_url")
    r = gw.post(f"/reports/{sid}/build", {"report_id": report_id, "hold": bool(company_url)})
    if r.get("status") not in ("READY", "RUNNING"):
        raise RuntimeError(f"report build failed: {r.get('status')}")  # worker가 리포트를 FAILED로 표시 → 관리자 재시도
    if company_url:
        link_company_criteria(gw, sid, report_id, company_id or "", company_url)
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

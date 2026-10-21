"""시나리오 정의(scenario.json)·관찰 코드북(criteria.md)·서윤 수정 규칙(colleague_fixes.json) 로더.

코드북은 criteria.md 표 한 곳에서만 정의하고 여기서 파싱한다(record_observation 검증·리포트 공용).
"""
from __future__ import annotations

import json
import re
from functools import lru_cache

from .config import DATA_DIR

COMPETENCIES = ["RESPONSIBILITY", "PLANNING", "ADAPTABILITY", "COLLABORATION", "HONESTY"]
COMPETENCY_LABEL = {"RESPONSIBILITY": "책임감/성실성", "PLANNING": "계획성/꼼꼼함", "ADAPTABILITY": "적응성/유연성",
                    "COLLABORATION": "협업/조율", "HONESTY": "정직/공정 보고"}
_PREFIX = {"RS": "RESPONSIBILITY", "PL": "PLANNING", "AD": "ADAPTABILITY", "CO": "COLLABORATION", "HO": "HONESTY"}
# 역량 × 이벤트 매트릭스(설계서 2장, ●·○ 모두). 이벤트가 하나도 발생하지 않은 역량은 '관찰 기회 없음'
COMPETENCY_EVENTS = {
    "RESPONSIBILITY": ["E0", "E1", "E2", "E3", "E4"],
    "PLANNING": ["E0", "E1", "E2", "E3"],
    "ADAPTABILITY": ["E2", "E3"],
    "COLLABORATION": ["E0", "E1", "E2", "E2B", "E3", "E3B"],
    "HONESTY": ["E4"],
}
# 지원자 메시지가 가리키는 정정 대상(심어둔 오류 위치·값, E2 변경). 정답 값은 쓰지 않는다.
# judge(발견·언급 판정)와 agent(서윤이 고칠 대상 결정)가 함께 쓴다.
TARGET_PATTERNS = {
    "PE-1": re.compile(r"11\s*/\s*31|31일|없는\s*날짜|(날짜|기간)[이가]?\s*(이상|틀|잘못|다르)"),
    "PE-2": re.compile(r"5,?000\s*P|5천|금액[이가]?\s*(이상|틀|잘못|다르)"),
    # PE-3 오답은 '가족 계정도 지급'. '결제수단'만 언급하면 정답(제외 조건)일 수 있어 누락을 지적할 때만 대상으로 본다.
    "PE-3": re.compile(r"가족|결제\s*수단.{0,20}(빠졌|빠져|누락|없어|들어가야|넣어|추가|반영)"),
    "PE-4": re.compile(r"반말|쏴드림|톤\s*가이드|존댓말"),
    "E2-CHANGE": re.compile(r"2,?000\s*P|2천|피초대자|초대받은\s*(친구|분)|변경\s*사항|바뀐\s*(내용|조건)"),
}


def normalize_expression(text: str) -> str:
    text = re.sub(r"(?<=\d),(?=\d)", "", text)
    text = re.sub(r"([1-9])\s*천", lambda m: str(int(m[1])*1000), text)
    text = re.sub(r"(\d+)\s*(?:포인트|점|[pP])", r"\1P", text)
    text = re.sub(r"(\d{1,2})월\s*(\d{1,2})일", r"\1/\2", text)
    return text


def targets_in(text: str) -> list[str]:
    norm = normalize_expression(text)
    out = [k for k, rx in TARGET_PATTERNS.items() if rx.search(norm)]
    if re.search(r"3000P|5000P|리워드.{0,15}(금액|보상)|초대\s*1?명당.*3000", norm, re.I):
        out.append("PE-2")
    return list(dict.fromkeys(out))


def contextual_targets(text: str, messages: list[dict]) -> list[str]:
    current = targets_in(text)
    if current or claim_kind(text) == "WRONG":
        return current
    if re.search(r"(그거|그게|그\s*부분|아까|말한|말씀드린|그\s*표|그\s*문서)", text):
        for msg in reversed([m for m in messages if m.get("actor") in ("CANDIDATE", "COLLEAGUE")][-6:]):
            found = targets_in(msg["content"])
            if found:
                return found
    return []


# ---- 정정 요청 vs 사실과 다른 지적: LLM이 아니라 규칙으로 판정 ---------------------------------
# 지원자가 '틀렸다'고 지목한 내용이 심어둔 오류(wrong)면 정정 요청, 브리프의 정답(correct, brief_facts)이면 사실과 다른 지적.
NEG_CLAIM = re.compile(r"(틀|잘못|아닌\s*것|아니에요|아니잖|이상하|맞지\s*않|오류|아닌가요|아닌데)")
REQUEST = re.compile(r"(부탁|해\s*주|해주|반영해\s*주|넣어\s*주|주실|주세요|들어가야|반영돼야|해야\s*해요)")
MISSING = re.compile(r"(빠졌|빠져|누락|없어|들어가야|넣어|추가|반영)")


def correct_tokens(sc: dict | None = None) -> list[str]:
    """브리프 정답 표현(정규화 전): 기간 끝 날짜, 초대자 보상 금액, 제외 조건, 지급 조건, 최대 인원."""
    sc = sc or scenario()
    out: list[str] = []
    for v in sc["brief_facts"].values():
        out += re.findall(r"\d+\s*/\s*\d+|[\d,]{4,}P|동일\s*결제\s*수단|결제\s*수단|첫\s*결제|최대\s*\d+\s*명", v)
    return list(dict.fromkeys(out))


def claim_kind(text: str, sc: dict | None = None) -> str | None:
    """SPECIFIC(심어둔 오류·E2 변경을 지목) / WRONG(브리프의 맞는 내용을 틀렸다고 함) / None(지목 대상 없음)."""
    tg = targets_in(text)
    if any(t.startswith("PE-") for t in tg):
        return "SPECIFIC"
    norm = re.sub(r"\s+", "", text)
    mentions_correct = any(re.sub(r"\s+", "", t) in norm for t in correct_tokens(sc) if not t.startswith("11/2"))
    if mentions_correct and NEG_CLAIM.search(text) and not MISSING.search(text):
        return "WRONG"
    # E2 변경(피초대자 2,000P)은 서윤에게 반영을 '요청'할 때만 정정 요청이다('제가 채워둘게요'는 이어받기)
    if "E2-CHANGE" in tg and REQUEST.search(text):
        return "SPECIFIC"
    return None


def contradicts_brief(before: str, after: str, sc: dict | None = None) -> list[str]:
    """수정안 안전장치: 수정으로 새로 생긴 날짜·금액이 브리프·E2 변경·심어둔 오류 정답에 없거나,
    브리프의 정답 표현이 사라지면 어긋남으로 본다."""
    sc = sc or scenario()
    allowed = set(re.sub(r"\s+", "", t) for t in correct_tokens(sc))
    allowed |= {"11/2", "2,000P"}  # 브리프 시작일, E2 changed_fact
    for pe in sc.get("planted_errors", []):
        allowed |= {re.sub(r"\s+", "", t) for t in re.findall(r"\d+\s*/\s*\d+|[\d,]{4,}P", pe["correct"])}
    tok = lambda x: {re.sub(r"\s+", "", t) for t in re.findall(r"\d+\s*/\s*\d+|[\d,]{4,}P", x)}
    bad = [f"new:{t}" for t in tok(after) - tok(before) if t not in allowed]
    for t in correct_tokens(sc):
        k = re.sub(r"\s+", "", t)
        if k in re.sub(r"\s+", "", before) and k not in re.sub(r"\s+", "", after):
            bad.append(f"removed:{t}")
    return bad


_ROW = re.compile(r"^\|\s*((?:RS|PL|AD|CO|HO)(?:[+-]\d|·N\d))\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*$")


@lru_cache
def scenario() -> dict:
    return json.loads((DATA_DIR / "scenario.json").read_text(encoding="utf-8"))


@lru_cache
def fixes() -> dict:
    return json.loads((DATA_DIR / "colleague_fixes.json").read_text(encoding="utf-8"))["fixes"]


@lru_cache
def codebook() -> dict[str, dict]:
    out = {}
    for line in (DATA_DIR / "documents" / "criteria.md").read_text(encoding="utf-8").splitlines():
        m = _ROW.match(line)
        if m:
            code = m.group(1)
            out[code] = {"code": code, "competency": competency_of(code), "label": m.group(2),
                         "definition": m.group(3), "evidence": m.group(4), "scenes": m.group(5)}
    return out


def competency_of(code: str) -> str:
    return _PREFIX[code[:2]]


def event(event_id: str, sc: dict | None = None) -> dict | None:
    return next((e for e in (sc or scenario())["events"] if e["id"] == event_id), None)


def public_definition(sc: dict) -> dict:
    """지원자·서윤 프롬프트·get_scenario 응답용: 심어둔 오류(정답)와 내부 판정 정보를 뺀 정의."""
    hidden = {"planted_errors", "commitment_tracking", "brief_facts"}
    out = {k: v for k, v in sc.items() if k not in hidden}
    out["events"] = [{k: v for k, v in e.items() if k not in ("actual_state", "verify_against", "end_check")}
                     for e in sc["events"]]
    return out

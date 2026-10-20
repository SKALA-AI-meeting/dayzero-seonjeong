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
    "PE-3": re.compile(r"가족\s*계정|결제\s*수단"),
    "PE-4": re.compile(r"반말|쏴드림|톤\s*가이드|존댓말"),
    "E2-CHANGE": re.compile(r"2,?000\s*P|2천|피초대자|초대받은\s*(친구|분)|변경\s*사항|바뀐\s*(내용|조건)"),
}


def targets_in(text: str) -> list[str]:
    return [k for k, rx in TARGET_PATTERNS.items() if rx.search(text)]


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
    hidden = {"planted_errors", "commitment_tracking"}
    out = {k: v for k, v in sc.items() if k not in hidden}
    out["events"] = [{k: v for k, v in e.items() if k not in ("actual_state", "verify_against", "end_check")}
                     for e in sc["events"]]
    return out

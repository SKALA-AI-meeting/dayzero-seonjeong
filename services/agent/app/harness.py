"""Harness 8 elements (ARCHITECTURE §9): instructions, tools, context, loop limits, guardrails, recovery, observability."""
from __future__ import annotations

import hashlib
import json
import random
import re
import time
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Callable

import tiktoken

from shared.config import PROMPTS_DIR

# ---- limits (자체 선택값, 교안 고정 수치 아님) ---------------------------------
INPUT_TOKEN_BUDGET = 6000
OUTPUT_TOKEN_BUDGET = 1200
TOOL_RESULT_TOKEN_LIMIT = 1500
SUMMARY_TOKEN_LIMIT = 800
MAX_RECENT_MESSAGES = 12
MAX_CHUNKS = 5
MAX_STEPS = 8
MAX_TOOL_CALLS = 5
MAX_SAME_TOOL = 3
ACTIVE_BUDGET_MS = 120_000
RETRY_DELAYS = (1.0, 2.0)  # 최초 + 2회 재시도
RETRYABLE = ("429", "503", "timeout", "rate limit", "overloaded", "temporarily")
SAFE_FALLBACK = "어떤 자료를 기준으로 볼지 정해 주시면 확인해 볼게요. 예: 지표 현황(모임 규모별 재참여율), 운영 정책, 회의록, 사용자 인터뷰(공유 후)."


# ---- Instructions -----------------------------------------------------------

@lru_cache
def load_prompt(name: str) -> tuple[str, str]:
    """Return (text, version_hash). name like 'colleague-v1'."""
    text = (PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8")
    return text, hashlib.sha256(text.encode()).hexdigest()[:12]


# ---- Context budget ------------------------------------------------------------

_enc = tiktoken.get_encoding("o200k_base")


def count_tokens(text: str) -> int:
    return len(_enc.encode(text))


def truncate_tokens(text: str, limit: int) -> str:
    ids = _enc.encode(text)
    if len(ids) <= limit:
        return text
    return _enc.decode(ids[:limit]) + " …(잘림)"


@dataclass
class ContextPack:
    system: str
    brief: str
    summary: str | None
    messages: list[dict]
    chunks: list[dict]
    delegation: dict | None
    dropped_chunks: int = 0
    summarized_ids: list[str] = field(default_factory=list)

    def render_user_context(self) -> str:
        parts = [f"[공개 브리프]\n{self.brief}"]
        if self.summary:
            parts.append(f"[이전 대화 요약]\n{self.summary}")
        if self.delegation:
            parts.append(f"[위임 범위]\n{json.dumps(self.delegation, ensure_ascii=False)}")
        if self.chunks:
            parts.append("[참고 청크]\n" + "\n".join(f"- ({c['chunk_id']}) {c['quote']}" for c in self.chunks))
        return "\n\n".join(parts)

    def total_tokens(self) -> int:
        return count_tokens(self.system) + count_tokens(self.render_user_context()) + sum(
            count_tokens(m["content"]) + 4 for m in self.messages)


def build_context(system: str, brief: str, messages: list[dict], chunks: list[dict], delegation: dict | None,
                  summarize: Callable[[list[dict]], str]) -> ContextPack:
    """Recent ≤12 messages; if over 6000 tokens summarize older ones (≤800 tokens, source IDs kept),
    then drop oldest chunks until under budget."""
    recent = messages[-MAX_RECENT_MESSAGES:]
    older = messages[:-MAX_RECENT_MESSAGES]
    pack = ContextPack(system, brief, None, recent, list(chunks[:MAX_CHUNKS]), delegation)
    if older:
        pack.summary = truncate_tokens(summarize(older), SUMMARY_TOKEN_LIMIT)
        pack.summarized_ids = [str(m["id"]) for m in older]
    while pack.total_tokens() > INPUT_TOKEN_BUDGET and len(pack.messages) > 2:
        moved = pack.messages[:2]
        pack.messages = pack.messages[2:]
        pack.summarized_ids += [str(m["id"]) for m in moved]
        pack.summary = truncate_tokens(summarize(older + moved), SUMMARY_TOKEN_LIMIT)
        older = older + moved
    while pack.total_tokens() > INPUT_TOKEN_BUDGET and pack.chunks:
        pack.chunks.pop(0)
        pack.dropped_chunks += 1
    return pack


def rule_summary(msgs: list[dict]) -> str:
    """Deterministic fallback summarizer: facts + source message IDs only, no intent inference."""
    lines = [f"- {m['actor']}: {truncate_tokens(m['content'], 60)} [msg:{m['id']}]" for m in msgs]
    return "\n".join(lines)


# ---- Tools: result shaping + PII masking ----------------------------------------

EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PHONE = re.compile(r"\b01[016789][-\s]?\d{3,4}[-\s]?\d{4}\b|\b\d{2,3}-\d{3,4}-\d{4}\b")


def mask_pii(text: str) -> str:
    return PHONE.sub("[전화번호]", EMAIL.sub("[이메일]", text))


def tool_message_content(payload: dict) -> str:
    """Serialize a tool result (including business errors) for the ToolMessage, capped at 1500 tokens."""
    return truncate_tokens(mask_pii(json.dumps(payload, ensure_ascii=False)), TOOL_RESULT_TOKEN_LIMIT)


# ---- Agent loop limits -------------------------------------------------------------

class LimitExceeded(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def check_tool_budget(tool_counts: dict[str, int], tool: str, step_count: int, active_ms: int) -> None:
    if step_count >= MAX_STEPS:
        raise LimitExceeded("MAX_STEPS")
    if sum(tool_counts.values()) >= MAX_TOOL_CALLS:
        raise LimitExceeded("MAX_TOOL_CALLS")
    if tool_counts.get(tool, 0) >= MAX_SAME_TOOL:
        raise LimitExceeded("MAX_SAME_TOOL")
    if active_ms >= ACTIVE_BUDGET_MS:
        raise LimitExceeded("ACTIVE_TIME_BUDGET")


# ---- Guardrails -----------------------------------------------------------------------

FORBIDDEN_OUTPUT = [r"최종\s*우선순위는", r"정답은", r"점수", r"합격", r"불합격", r"이것을\s*선택하세요"]
NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")


def validate_output(text: str, allowed_numbers: set[str]) -> list[str]:
    """Return violations: forbidden judgement phrases or business numbers absent from tool results/citations."""
    problems = [f"forbidden:{p}" for p in FORBIDDEN_OUTPUT if re.search(p, text)]
    for n in NUMBER.findall(text):
        norm = n.replace(",", "")
        if len(norm.replace(".", "")) < 3:  # 작은 수(항목 번호, 1~2자리)는 검사하지 않음
            continue
        if norm not in allowed_numbers:
            problems.append(f"ungrounded_number:{n}")
    return problems


def numbers_in(obj: Any) -> set[str]:
    out: set[str] = set()
    def walk(v: Any) -> None:
        if isinstance(v, dict):
            for x in v.values():
                walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)
        elif isinstance(v, bool):
            return
        elif isinstance(v, (int, float)):
            out.add(str(v))
            if isinstance(v, float):
                pct = v * 100
                for d in (0, 1, 2, 4):
                    out.add(f"{pct:.{d}f}")
                    out.add(f"{v:.{d}f}")
        elif isinstance(v, str):
            for n in NUMBER.findall(v):
                out.add(n.replace(",", ""))
    walk(obj)
    return out


# ---- Recovery ------------------------------------------------------------------------------

def is_retryable(e: Exception) -> bool:
    s = f"{type(e).__name__} {e}".lower()
    return any(k in s for k in RETRYABLE)


def with_retries(fn: Callable[[], Any], *, deadline: float, on_retry: Callable[[int, Exception], None] | None = None) -> Any:
    """First attempt + 2 retries for 429/503/timeout with 1s/2s jitter, within remaining budget. No model switch."""
    for attempt in range(len(RETRY_DELAYS) + 1):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001
            if attempt == len(RETRY_DELAYS) or not is_retryable(e):
                raise
            delay = RETRY_DELAYS[attempt] + random.uniform(0, 0.3)
            if time.monotonic() + delay > deadline:
                raise
            if on_retry:
                on_retry(attempt + 1, e)
            time.sleep(delay)
    raise RuntimeError("unreachable")

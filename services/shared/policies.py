"""Conditional intervention rules (SCENARIO_DATA §5). Pure functions: inputs are stored actions/state only.

The LLM never chooses events; ability/personality is never estimated.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache

from shared.config import DATA_DIR

CANDIDATE_ACTIONS = {"MESSAGE_SENT", "DOCUMENT_OPENED", "ARTIFACT_SAVED", "TASK_REVIEWED",
                     "DELEGATION_CREATED", "APPROVAL_DECIDED"}
CONSTRAINT_TERMS = ("전고객무료배송", "일괄10%쿠폰")
NEGATIONS = ("금지", "제외", "하지않", "안함", "불가")
SENTENCE_SPLIT = re.compile(r"(?<=[.!?。])\s+|\n+")


@lru_cache
def help_policy() -> dict:
    return json.loads((DATA_DIR / "policies" / "help-v1.json").read_text())


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", s)


def constraint_hit(options_text: str) -> bool:
    """True if any sentence contains a constraint term without a negation in the same sentence."""
    for sent in SENTENCE_SPLIT.split(options_text):
        n = _norm(sent)
        if any(t in n for t in CONSTRAINT_TERMS) and not any(x in n for x in NEGATIONS):
            return True
    return False


def detect(action: dict, *, revision_sections: dict | None, segment_metric_before: bool,
           review: dict | None) -> str | None:
    """Return event_id whose predicate this single action satisfies, or None."""
    kind, p = action["kind"], action["payload"]
    if kind == "ARTIFACT_SAVED" and p.get("section") == "options" and revision_sections is not None:
        if constraint_hit(revision_sections.get("options", "")):
            return "E-CONSTRAINT"
    if kind == "TASK_REVIEWED" and review and review.get("decision") == "ACCEPT" and review.get("owner") == "COLLEAGUE" \
            and not review.get("source_refs"):
        return "E-VERIFY"
    if kind == "ARTIFACT_SAVED" and p.get("section") == "problem" and p.get("was_empty") and p.get("length", 0) > 0 \
            and not segment_metric_before:
        return "E-SEGMENT"
    return None


def choose(pending: list[dict], occurred: set[str], priorities: dict[str, int], auto_count: int,
           actions_since_last: int, has_previous: bool) -> tuple[dict | None, str]:
    """Pick at most one intervention. Returns (candidate, decision) with decision in
    EMIT | SUPPRESSED_BUDGET | DEFERRED_GAP | NONE."""
    cands = sorted((c for c in pending if c["event_id"] not in occurred),
                   key=lambda c: (priorities[c["event_id"]], c["trigger_action_seq"]))
    if not cands:
        return None, "NONE"
    pol = help_policy()
    if auto_count >= pol["max_auto_interventions"]:
        return cands[0], "SUPPRESSED_BUDGET"
    if has_previous and actions_since_last < pol["min_candidate_actions_between_interventions"]:
        return cands[0], "DEFERRED_GAP"
    return cands[0], "EMIT"

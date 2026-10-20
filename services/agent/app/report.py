"""REPORT job — M4 placeholder: rules-only fact report (generation_mode RULES_FALLBACK).

The full LLM_WITH_RULES report with quote verification is M4 work (issue #5)."""
from __future__ import annotations

from .clients import Gateway


def run_report(gw: Gateway, job: dict) -> None:
    gw.post(f"/reports/{job['session_id']}/build", {"report_id": job["input"]["report_id"], "mode": "RULES_FALLBACK"})

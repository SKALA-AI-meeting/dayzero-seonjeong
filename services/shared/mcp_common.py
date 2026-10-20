"""Shared MCP helpers: common tool output shape and capability header extraction."""
from __future__ import annotations

import json
from typing import Any

import mcp_types as t

CAPABILITY_HEADER = "x-capability"


def result(payload: dict) -> t.CallToolResult:
    """Serialize the common {ok,data,error,citations} shape into text + structuredContent.

    Business errors are returned as isError=True (not JSON-RPC errors)."""
    return t.CallToolResult(
        content=[t.TextContent(type="text", text=json.dumps(payload, ensure_ascii=False))],
        structured_content=payload,
        is_error=not payload.get("ok", False),
    )


def error(code: str, message: str, retryable: bool = False) -> t.CallToolResult:
    return result({"ok": False, "data": None, "error": {"code": code, "message": message, "retryable": retryable},
                   "citations": []})


def capability_from(ctx: Any) -> str:
    req = getattr(ctx.request_context, "request", None)
    if req is None:
        return ""
    return req.headers.get(CAPABILITY_HEADER, "")


READ = t.ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False)
WRITE = t.ToolAnnotations(read_only_hint=False, destructive_hint=True, idempotent_hint=False, open_world_hint=False)

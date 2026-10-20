"""Gateway internal API client and MCP SDK client adapter used by the agent."""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from typing import Any

import httpx
import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

from shared.config import SCENARIO_ID, settings

S = settings()
SVC = {"x-service-token": S.internal_service_secret}
RAG_TOOLS = {"search_docs"}


class Gateway:
    def __init__(self) -> None:
        self.base = S.gateway_internal_url + "/internal/v1"
        self.http = httpx.Client(timeout=10, headers=SVC)

    def post(self, path: str, body: dict) -> dict:
        r = self.http.post(self.base + path, json=body)
        if r.status_code >= 400:
            raise GatewayError(r.status_code, r.text[:300])
        return r.json()

    def get(self, path: str) -> dict:
        r = self.http.get(self.base + path)
        r.raise_for_status()
        return r.json()

    def event(self, run_id: str, type_: str, payload: dict, key: str | None = None) -> dict:
        return self.post(f"/runs/{run_id}/events", {"client_event_id": key or f"{type_}:{uuid.uuid4().hex}",
                                                    "type": type_, "payload": payload})

    def state(self, run_id: str, status: str, **kw: Any) -> None:
        self.post(f"/runs/{run_id}/state", {"status": status, **{k: v for k, v in kw.items() if v is not None}})

    def capability(self, run_id: str, audience: str, approval_id: str | None = None) -> str:
        return self.post(f"/runs/{run_id}/capability", {"audience": audience, "approval_id": approval_id})["token"]


class GatewayError(Exception):
    def __init__(self, status: int, body: str):
        super().__init__(f"{status}: {body}")
        self.status, self.body = status, body


def _payload(res) -> dict:
    if res.structured_content:
        return dict(res.structured_content)
    try:
        return json.loads(res.content[0].text)
    except Exception:  # protocol-level error text
        text = res.content[0].text if res.content else "unknown error"
        return {"ok": False, "data": None, "error": {"code": "INVALID_ARGUMENT", "message": text[:300], "retryable": False},
                "citations": []}


async def _call(url: str, cap: str, tool: str, args: dict) -> dict:
    async with Client(streamable_http_client(url, http_client=httpx2.AsyncClient(headers={"x-capability": cap}, timeout=30))) as c:
        return _payload(await c.call_tool(tool, args))


async def _list(url: str, cap: str) -> list:
    async with Client(streamable_http_client(url, http_client=httpx2.AsyncClient(headers={"x-capability": cap}, timeout=30))) as c:
        return (await c.list_tools()).tools


async def _read(url: str, cap: str, uri: str) -> str:
    async with Client(streamable_http_client(url, http_client=httpx2.AsyncClient(headers={"x-capability": cap}, timeout=30))) as c:
        rr = await c.read_resource(uri)
        return rr.contents[0].text


def call_tool(gw: Gateway, run_id: str, tool: str, args: dict, approval_id: str | None = None) -> tuple[dict, int]:
    """Real MCP tools/call. Returns (common payload, duration_ms). Never raises for business errors."""
    t0 = time.monotonic()
    rag = tool in RAG_TOOLS
    try:
        cap = gw.capability(run_id, "rag-mcp" if rag else "business-mcp", approval_id)
        out = asyncio.run(_call(S.rag_mcp_url if rag else S.business_mcp_url, cap, tool, args))
    except GatewayError as e:
        out = {"ok": False, "data": None, "error": {"code": "FORBIDDEN", "message": e.body[:200], "retryable": False}, "citations": []}
    except Exception as e:  # noqa: BLE001 — transport failure → structured TIMEOUT/INTERNAL_ERROR ToolMessage
        code = "TIMEOUT" if "timeout" in str(e).lower() else "INTERNAL_ERROR"
        out = {"ok": False, "data": None, "error": {"code": code, "message": type(e).__name__, "retryable": True}, "citations": []}
    return out, int((time.monotonic() - t0) * 1000)


def list_read_tools(gw: Gateway, run_id: str) -> list:
    """tools/list on both servers, keeping read-only tools (annotations) for model binding."""
    tools = []
    for url, aud in ((S.business_mcp_url, "business-mcp"), (S.rag_mcp_url, "rag-mcp")):
        cap = gw.capability(run_id, aud)
        for t in asyncio.run(_list(url, cap)):
            if t.annotations and t.annotations.read_only_hint and t.name != "get_session_context":
                tools.append(t)
    return tools


def read_resource(gw: Gateway, run_id: str, document_id: str) -> str:
    cap = gw.capability(run_id, "rag-mcp")
    return asyncio.run(_read(S.rag_mcp_url, cap, f"doc://{SCENARIO_ID}/{document_id}"))

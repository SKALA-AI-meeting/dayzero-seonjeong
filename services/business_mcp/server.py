"""business-mcp: commerce metrics, support cases, delegated task/artifact mutations.

All tools forward to gateway /internal/v1/mcp/{tool}. This server has no DB DSN.
Session/actor context comes from the capability header, never from model input.
"""
from __future__ import annotations

import asyncio
from typing import Literal

import httpx
import mcp_types as t
import uvicorn
from mcp.server.mcpserver import Context, MCPServer
from pydantic import BaseModel, Field

from shared.config import settings
from shared.mcp_common import READ, WRITE, capability_from, error, result

mcp = MCPServer(name="business-mcp", version="0.1.0",
                instructions="모아마켓 장바구니 퍼널 지표·고객 문의 조회와 위임된 evidence 변경 도구. 숫자는 세션 수, rate는 0~1.")
TIMEOUT = 5.0


class Filters(BaseModel):
    device: Literal["mobile", "desktop"] | None = None
    visitor: Literal["new", "returning"] | None = None
    cart_value: Literal["low", "high"] | None = None


class Citation(BaseModel):
    document_id: str
    chunk_id: str | None = None
    version: int = 1
    quote: str = Field(max_length=1500)


async def forward(tool: str, args: dict, ctx: Context, *, retries: int) -> t.CallToolResult:
    cap = capability_from(ctx)
    if not cap:
        return error("FORBIDDEN", "capability가 없습니다")
    url = f"{settings().gateway_internal_url}/internal/v1/mcp/{tool}"
    headers = {"x-service-token": settings().internal_service_secret, "x-capability": cap}
    for attempt in range(retries + 1):
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT) as client:
                r = await client.post(url, json={"args": args}, headers=headers)
            if r.status_code == 403:
                return error("FORBIDDEN", r.json().get("error", {}).get("message", "권한 없음"))
            r.raise_for_status()
            return result(r.json())
        except httpx.TimeoutException:
            if attempt == retries:
                return error("TIMEOUT", "gateway 응답 시간 초과", retryable=True)
        except httpx.HTTPError as e:
            if attempt == retries:
                return error("INTERNAL_ERROR", f"gateway 호출 실패: {type(e).__name__}", retryable=True)
        await asyncio.sleep(0.3 * (attempt + 1))
    return error("INTERNAL_ERROR", "unreachable")


@mcp.tool(annotations=READ, description=(
    "현재 세션의 공개 브리프, 진행 단계, 태스크 목록, 기획안 버전을 조회한다. 인자 없음. "
    "평가 기준이나 개입 정책은 포함하지 않는다."))
async def get_session_context(ctx: Context) -> t.CallToolResult:
    return await forward("get_session_context", {}, ctx, retries=2)


@mcp.tool(annotations=READ, description=(
    "모아마켓 장바구니 퍼널 집계를 조회한다. period: baseline(2026-09-28~10-04) | current(2026-10-12~10-18). "
    "dimension: overall | device | visitor | cart_value 로 group by. filters: device(mobile|desktop), "
    "visitor(new|returning), cart_value(low<5만원|high≥5만원) AND 필터. 출력 rows는 segment, cart_sessions, "
    "checkout_sessions, orders(세션 수)와 abandonment_rate=(cart-orders)/cart, "
    "checkout_abandonment_rate=(checkout-orders)/checkout (0~1, 분모 0이면 null). 인과 효과는 알 수 없다. "
    "오류: INVALID_ARGUMENT(허용되지 않는 enum)."))
async def get_funnel_metrics(period: Literal["baseline", "current"],
                             dimension: Literal["overall", "device", "visitor", "cart_value"],
                             ctx: Context, filters: Filters | None = None) -> t.CallToolResult:
    f = {k: v for k, v in (filters.model_dump() if filters else {}).items() if v}
    return await forward("get_funnel_metrics", {"period": period, "dimension": dimension, "filters": f}, ctx, retries=2)


@mcp.tool(annotations=READ, description=(
    "current 기간 고객센터 합성 문의 사례(VOC)를 태그로 조회한다. tags 최대 3개: shipping, transparency, signup, "
    "friction, performance, checkout, coupon, comparison, deferred. 빈 배열이면 전체. limit 1~5. "
    "확률표본이 아니므로 전체 원인 비중을 추정하면 안 된다. 오류: INVALID_ARGUMENT."))
async def get_support_cases(ctx: Context, tags: list[str] | None = None, limit: int = 5) -> t.CallToolResult:
    return await forward("get_support_cases", {"tags": tags or [], "limit": limit}, ctx, retries=2)


@mcp.tool(annotations=WRITE, description=(
    "위임받은 동료 태스크의 상태를 IN_PROGRESS 또는 REVIEW로 변경한다. 지원자의 변경별 승인이 있어야만 실행된다. "
    "DONE은 지원자만 결정한다. 오류: APPROVAL_REQUIRED, OUT_OF_SCOPE, VERSION_CONFLICT."))
async def update_task_status(task_id: str, base_version: int, status: Literal["IN_PROGRESS", "REVIEW"],
                             ctx: Context) -> t.CallToolResult:
    return await forward("update_task_status", {"task_id": task_id, "base_version": base_version, "status": status},
                         ctx, retries=0)


@mcp.tool(annotations=WRITE, description=(
    "위임받은 조사 결과를 기획안 evidence 섹션에 반영한다. section은 evidence만 허용. content는 사실 요약과 출처만. "
    "변경마다 지원자 승인이 필요하며 승인된 인자와 다르면 거절된다. "
    "오류: APPROVAL_REQUIRED, APPROVAL_EXPIRED, OUT_OF_SCOPE, VERSION_CONFLICT."))
async def patch_artifact_section(task_id: str, section: Literal["evidence"], base_version: int, content: str,
                                 citations: list[Citation], ctx: Context) -> t.CallToolResult:
    args = {"task_id": task_id, "section": section, "base_version": base_version, "content": content,
            "citations": [c.model_dump() for c in citations]}
    return await forward("patch_artifact_section", args, ctx, retries=0)


app = mcp.streamable_http_app(streamable_http_path="/mcp", host="0.0.0.0", stateless_http=True)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=9101)

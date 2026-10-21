"""business-mcp: 시나리오·턴 상태 조회, 심어둔 오류(Agent 판정 전용), 관찰 기록, 승인 후 서윤 산출물·태스크 변경.

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
from shared.mcp_common import LOG, READ, WRITE, capability_from, error, result

mcp = MCPServer(name="business-mcp", version="0.2.0",
                instructions="핏모아 친구 초대 이벤트(sc-a) 시뮬레이션의 시나리오·턴 상태 조회, 관찰 코드 기록, "
                             "지원자 승인 후 서윤 산출물(T2 FAQ·T3 리워드 표) 수정 도구.")
TIMEOUT = 5.0


class EvidenceRef(BaseModel):
    kind: Literal["message", "revision", "action"]
    id: str = Field(max_length=80)


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
    "현재 세션의 턴 수, 경과 시간, 활성 이벤트, 서윤 상태(자리 비움), 태스크 보드(담당·상태·예상 시각), "
    "산출물 목록(T1~T5 key·버전)을 조회한다. 인자 없음. 관찰 코드·심어둔 오류는 포함하지 않는다."))
async def get_session_context(ctx: Context) -> t.CallToolResult:
    return await forward("get_session_context", {}, ctx, retries=2)


@mcp.tool(annotations=READ, description=(
    "시나리오 정의(sc-a)를 조회한다: 등장인물·성격, 공유 문서 목록, 태스크, 이벤트(E0~E4)의 트리거·고정 대사·분기 라벨, "
    "무응답 정책. 심어둔 오류의 정답은 포함하지 않는다(get_planted_error 사용). 인자 없음."))
async def get_scenario(ctx: Context) -> t.CallToolResult:
    return await forward("get_scenario", {}, ctx, retries=2)


@mcp.tool(annotations=READ, description=(
    "다음 이벤트와 남은 턴 수(turns_until), 현재 활성 이벤트, 응답 대기 중인 이벤트를 조회한다. 인자 없음. "
    "이벤트 발생 자체는 gateway 턴 엔진이 한다."))
async def get_next_event(ctx: Context) -> t.CallToolResult:
    return await forward("get_next_event", {}, ctx, retries=2)


@mcp.tool(annotations=READ, description=(
    "[Agent 판정·수정 전용, 기밀] 심어둔 오류(PE-1~PE-4)와 E2 변경(E2-CHANGE)의 위치·오답·정답·수정 규칙을 조회한다. "
    "error_ids를 비우면 전체. 결과는 confidential이며 서윤의 발화나 지원자에게 보내는 메시지에 넣지 않는다. 오류: NOT_FOUND."))
async def get_planted_error(ctx: Context, error_ids: list[str] | None = None) -> t.CallToolResult:
    return await forward("get_planted_error", {"error_ids": error_ids or []}, ctx, retries=2)


@mcp.tool(annotations=LOG, description=(
    "관찰 코드 1개를 근거와 함께 기록한다(승인 불필요, 업무 산출물은 바꾸지 않음). code는 코드북(criteria) 코드만 허용 "
    "(예: CO+5, RS+1, HO-1, CO·N1). evidence_ref는 이 세션의 message·revision·action ID. 같은 코드·이벤트·대상은 1회만 기록된다. "
    "점수·판정은 만들지 않는다. 오류: INVALID_ARGUMENT, NOT_FOUND."))
async def record_observation(code: str, evidence_ref: EvidenceRef, ctx: Context, event_id: str | None = None,
                             subject: str | None = None, note: str = "") -> t.CallToolResult:
    args = {"code": code, "evidence_ref": evidence_ref.model_dump(), "event_id": event_id, "subject": subject, "note": note[:300]}
    return await forward("record_observation", args, ctx, retries=1)


@mcp.tool(annotations=WRITE, description=(
    "서윤 담당 태스크의 상태를 IN_PROGRESS 또는 DONE으로 변경한다. 지원자의 승인이 있어야만 실행된다. "
    "오류: APPROVAL_REQUIRED, OUT_OF_SCOPE, VERSION_CONFLICT."))
async def update_task_status(task_key: str, base_version: int, status: Literal["IN_PROGRESS", "DONE"],
                             ctx: Context) -> t.CallToolResult:
    return await forward("update_task_status", {"task_key": task_key, "base_version": base_version, "status": status},
                         ctx, retries=0)


@mcp.tool(annotations=WRITE, description=(
    "지원자의 정정 요청을 받아 서윤 초안 산출물(T2 FAQ, T3 리워드·일정 표) 전체 본문을 수정안으로 바꾼다. "
    "변경마다 지원자 승인이 필요하며 승인된 인자와 다르면 거절된다. targets는 요청받은 정정 대상(PE-1~4, E2-CHANGE). "
    "오류: APPROVAL_REQUIRED, APPROVAL_EXPIRED, OUT_OF_SCOPE, VERSION_CONFLICT."))
async def patch_artifact_section(artifact_key: Literal["T2", "T3"], base_version: int, content: str,
                                 targets: list[str], ctx: Context) -> t.CallToolResult:
    args = {"artifact_key": artifact_key, "base_version": base_version, "content": content, "targets": targets}
    return await forward("patch_artifact_section", args, ctx, retries=0)


app = mcp.streamable_http_app(streamable_http_path="/mcp", host="0.0.0.0", stateless_http=True)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=9101)

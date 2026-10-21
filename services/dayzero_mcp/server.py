"""dayzero-mcp: 평가자(사람 또는 평가자의 AI)가 지원자 근거를 조회하는 읽기 전용 MCP 서버.

DB에 직접 접근하지 않고 gateway /internal/v1/dayzero/**를 호출한다(business-mcp와 같은 규칙).
평가자 토큰은 gateway가 DAYZERO_MCP_TOKEN과 비교한다. 이 서버는 토큰을 전달만 한다.
- HTTP(기본, :9103/mcp): 요청 헤더 Authorization: Bearer <토큰>
- stdio(--stdio, Claude Desktop 연결용): 실행 환경변수 DAYZERO_TOKEN(Claude Desktop 설정의 env)

uv run python -m dayzero_mcp.server            # HTTP
uv run python -m dayzero_mcp.server --stdio    # stdio
"""
from __future__ import annotations

import argparse
import os
from urllib.parse import quote

import httpx
import mcp_types as t
import uvicorn
from mcp.server.mcpserver import Context, MCPServer

from shared.config import settings
from shared.mcp_common import READ, error, result

NOTICE = "근거 조회용 도구입니다. 합격·탈락 결정은 평가자가 합니다."
TIMEOUT = 10.0
_mode = {"stdio": False}

mcp = MCPServer(name="dayzero-mcp", version="0.1.0",
                instructions=f"Day Zero 업무 시뮬레이션에서 기록된 지원자의 관찰 코드·근거 원문·연결된 회사 조항을 조회한다. 읽기 전용. {NOTICE} "
                             "적합/부적합 판정, 탈락자 목록, 점수·순위는 제공하지 않는다.")


def _token(ctx: Context | None) -> str:
    if _mode["stdio"]:
        return os.environ.get("DAYZERO_TOKEN", "")
    req = getattr(getattr(ctx, "request_context", None), "request", None) if ctx else None
    auth = req.headers.get("authorization", "") if req is not None else ""
    return auth[7:].strip() if auth.lower().startswith("bearer ") else ""


def _get(path: str, params: dict, ctx: Context | None) -> dict:
    tok = _token(ctx)
    if not tok:
        raise PermissionError("평가자 토큰이 필요합니다")
    headers = {"x-service-token": settings().internal_service_secret, "x-evaluator-token": tok}
    r = httpx.get(f"{settings().gateway_internal_url}/internal/v1/dayzero{path}", params=params, headers=headers, timeout=TIMEOUT)
    if r.status_code in (401, 403):
        raise PermissionError(r.json().get("error", {}).get("message", "권한 없음"))
    if r.status_code == 404:
        raise LookupError(r.json().get("error", {}).get("message", "없음"))
    r.raise_for_status()
    return r.json()


def _call(path: str, params: dict, ctx: Context) -> t.CallToolResult:
    try:
        data = _get(path, params, ctx)
    except PermissionError as e:
        return error("UNAUTHORIZED", str(e))
    except LookupError as e:
        return error("NOT_FOUND", str(e))
    except httpx.TimeoutException:
        return error("TIMEOUT", "gateway 응답 시간 초과", retryable=True)
    except httpx.HTTPError as e:
        return error("INTERNAL_ERROR", f"gateway 호출 실패: {type(e).__name__}", retryable=True)
    return result({"ok": True, "data": data, "error": None, "citations": []})


@mcp.tool(annotations=READ, description=(
    f"{NOTICE} 관찰 코드(예: CO·N1, CO+5, RS+1)가 기록된 지원자 목록과 각자의 근거 메시지 원문·가상 시각·연결된 회사 조항을 조회한다. "
    "event_id(E0~E4)로 장면을 좁힐 수 있다. limit 1~50. 정렬은 세션 종료 시각(최근 순)이며 순위가 아니다. "
    "적합/부적합 판정이나 점수는 없다. 오류: UNAUTHORIZED, INVALID_ARGUMENT."))
async def find_candidates_by_behavior(code: str, ctx: Context, event_id: str | None = None, limit: int = 20) -> t.CallToolResult:
    if not 2 <= len(code) <= 12 or not 1 <= limit <= 50:
        return error("INVALID_ARGUMENT", "code는 2~12자, limit은 1~50입니다")
    return _call("/candidates", {"code": code, "limit": limit, **({"event_id": event_id} if event_id else {})}, ctx)


@mcp.tool(annotations=READ, description=(
    f"{NOTICE} 한 지원자(session_id)의 관찰 리포트 원문을 조회한다: 5역량 카드(관찰됨/관찰 기회 부족/없음), 관찰 코드별 근거 원문, "
    "연결된 회사 조항(근거 첨부, 판정 아님), LLM 추정 표시(llm 분기 라벨), 이벤트 타임라인, 한계. 오류: UNAUTHORIZED, NOT_FOUND."))
async def get_candidate_report(session_id: str, ctx: Context) -> t.CallToolResult:
    return _call(f"/reports/{quote(session_id, safe='')}", {}, ctx)


@mcp.resource("report://{session_id}", name="report", mime_type="application/json",
              description=f"지원자 관찰 리포트 원문(get_candidate_report와 같은 내용). {NOTICE}")
def report_resource(session_id: str, ctx: Context) -> str:
    import json
    return json.dumps(_get(f"/reports/{quote(session_id, safe='')}", {}, ctx), ensure_ascii=False)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stdio", action="store_true", help="Claude Desktop 연결용 stdio 모드(토큰: 환경변수 DAYZERO_TOKEN)")
    ap.add_argument("--port", type=int, default=9103)
    a = ap.parse_args()
    if a.stdio:
        _mode["stdio"] = True
        mcp.run("stdio")
        return
    uvicorn.run(mcp.streamable_http_app(streamable_http_path="/mcp", host="0.0.0.0", stateless_http=True), host="0.0.0.0", port=a.port)


if __name__ == "__main__":
    main()

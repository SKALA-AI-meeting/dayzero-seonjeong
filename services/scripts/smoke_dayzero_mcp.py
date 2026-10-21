"""dayzero-mcp smoke: 실제 MCP SDK 클라이언트로 HTTP(:9103, Bearer 토큰)와 stdio(DAYZERO_TOKEN) 두 모드에서
find_candidates_by_behavior·get_candidate_report·report:// 를 호출하고, 토큰 없이/틀린 토큰은 거부되는지 확인한다.
완료 세션이 필요하다(scripts.seed_candidates). 토큰 값은 출력하지 않는다.

uv run python -m scripts.smoke_dayzero_mcp
"""
from __future__ import annotations

import asyncio
import sys

import httpx2
from mcp import Client
from mcp.client.stdio import StdioServerParameters
from mcp.client.streamable_http import streamable_http_client

from shared.config import ROOT, settings

S = settings()
URL = "http://localhost:9103/mcp"
NOTICE = "근거 조회용 도구입니다. 합격·탈락 결정은 평가자가 합니다."
BANNED_TOOLS = ("rank", "score", "screen", "pass", "fail", "reject", "fit")
results: list[tuple[str, bool, str]] = []


def check(name: str, ok, detail: str = "") -> bool:
    results.append((name, bool(ok), detail))
    print(("PASS " if ok else "FAIL ") + name + (f" — {detail}" if detail else ""), flush=True)
    return bool(ok)


def http(token: str | None) -> Client:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return Client(streamable_http_client(URL, http_client=httpx2.AsyncClient(headers=headers, timeout=30)))


def stdio(token: str | None) -> Client:
    env = {"DAYZERO_TOKEN": token} if token else {}
    return Client(StdioServerParameters(command="uv", args=["run", "python", "-m", "dayzero_mcp.server", "--stdio"],
                                        cwd=str(ROOT / "services"), env=env))


async def exercise(mode: str, client: Client) -> None:
    async with client as c:
        tools = {t.name: t for t in (await c.list_tools()).tools}
        check(f"[{mode}] tools/list = 두 도구(읽기 전용)", set(tools) == {"find_candidates_by_behavior", "get_candidate_report"}
              and all(t.annotations.read_only_hint for t in tools.values()))
        check(f"[{mode}] 도구 description에 '{NOTICE}'", all(NOTICE in (t.description or "") for t in tools.values()))
        check(f"[{mode}] 판정·순위·탈락 도구 없음", not any(b in n for n in tools for b in BANNED_TOOLS))
        r = await c.call_tool("find_candidates_by_behavior", {"code": "CO·N1"})
        d = r.structured_content["data"] if not r.is_error else {}
        items = d.get("items", [])
        check(f"[{mode}] find_candidates_by_behavior(CO·N1) → 지원자 2명 이상", len(items) >= 2,
              ", ".join(f"{i['alias']}" for i in items[:6]))
        ev = [e for i in items for e in i["evidence"]]
        check(f"[{mode}] 각 지원자에 근거 원문·가상 시각·연결 조항", items and all(i["evidence"] for i in items)
              and all(e["quote"] for e in ev) and all(e.get("virtual_time") or e["evidence_kind"] != "message" for e in ev)
              and all(e.get("linked_criterion") for e in ev), (ev[0]["quote"] or "")[:40] if ev else "")
        check(f"[{mode}] 결과에 점수·합불 필드 없음", not any(k in str(d) for k in ("'score'", "합격 여부", "부적합", "'rank'")))
        r = await c.call_tool("find_candidates_by_behavior", {"code": "CO+5", "event_id": "E0"})
        check(f"[{mode}] event_id로 장면 좁히기", not r.is_error and all(e["event_id"] == "E0" for i in r.structured_content["data"]["items"]
                                                                          for e in i["evidence"]))
        r = await c.call_tool("find_candidates_by_behavior", {"code": "CO·N1", "event_id": "E0"})
        rv = [e for i in (r.structured_content["data"]["items"] if not r.is_error else []) for e in i["evidence"]]
        check(f"[{mode}] event_id(E0)로 거르면 문서 수정(revision) 근거도 잡힘·가상 시각 있음",
              any(e["evidence_kind"] == "revision" for e in rv) and all(e["event_id"] == "E0" and e["virtual_time"] for e in rv),
              f"{len(rv)}건, 예: {rv[0]['virtual_time']} {rv[0]['event_id']}" if rv else "0건")
        check(f"[{mode}] 모든 근거에 event_id·virtual_time(메시지·문서 수정)", all(e["event_id"] and e["virtual_time"]
              for e in ev if e["evidence_kind"] in ("message", "revision")))
        sid = items[0]["session_id"] if items else "none"
        r = await c.call_tool("get_candidate_report", {"session_id": sid})
        rep = r.structured_content["data"] if not r.is_error else {}
        comps = rep.get("competencies") or []
        obs = [o for cp in comps for o in cp["observations"]]
        check(f"[{mode}] get_candidate_report → 5역량 카드·근거·회사 조항", len(comps) == 5 and obs and all(o.get("evidence") for o in obs)
              and any(o.get("linked_criterion") for o in obs) and rep.get("company", {}).get("company_id"),
              f"{rep.get('alias')} company={rep.get('company', {}).get('company_id')} codes={len(obs)}")
        check(f"[{mode}] LLM 추정 표시 필드(estimated) 포함", obs and all("estimated" in o for o in obs))
        check(f"[{mode}] 리포트에 점수(score)·순위 필드 없음", not any(k in str(rep) for k in ("'score'", "'rank'")))
        rr = await c.read_resource(f"report://{sid}")
        check(f"[{mode}] resources/read report://{{session_id}}", sid in rr.contents[0].text)
        r = await c.call_tool("get_candidate_report", {"session_id": "00000000-0000-0000-0000-000000000000"})
        check(f"[{mode}] 없는 세션 → NOT_FOUND", r.is_error and r.structured_content["error"]["code"] == "NOT_FOUND")


async def denied(mode: str, client: Client, label: str) -> None:
    async with client as c:
        r = await c.call_tool("find_candidates_by_behavior", {"code": "CO·N1"})
        r2 = await c.call_tool("get_candidate_report", {"session_id": "x"})
        check(f"[{mode}] {label} → 두 도구 모두 UNAUTHORIZED", r.is_error and r.structured_content["error"]["code"] == "UNAUTHORIZED"
              and r2.is_error and r2.structured_content["error"]["code"] == "UNAUTHORIZED")


async def main() -> int:
    tok = S.dayzero_mcp_token
    if not check("DAYZERO_MCP_TOKEN 설정됨(값은 출력하지 않음)", tok):
        return 1
    await exercise("http", http(tok))
    await denied("http", http(None), "토큰 없음")
    await denied("http", http("wrong-token"), "틀린 토큰")
    await exercise("stdio", stdio(tok))
    await denied("stdio", stdio(None), "토큰 없음")
    failed = [n for n, ok, _ in results if not ok]
    print(f"\n결과: {len(results) - len(failed)}/{len(results)} PASS")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

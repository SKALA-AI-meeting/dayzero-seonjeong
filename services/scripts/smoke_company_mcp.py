"""company-mcp smoke: 같은 코드로 띄운 A사(:9201)·B사(:9202) 서버에 같은 질의를 보내 서로 다른 조항이 나오는지 확인한다.

uv run python -m scripts.smoke_company_mcp
"""
from __future__ import annotations

import asyncio
import sys

import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

from shared.config import settings

results: list[tuple[str, bool, str]] = []
PAIRS = [("CO·N1", "동료 문서를 말하지 않고 직접 고침"),
         ("CO+5", "동료 산출물의 문제를 근거와 함께 구체적으로 정정 요청"),
         ("RS+1", "지연·리스크를 마감 전에 먼저 알림")]


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, bool(ok), detail))
    print(("PASS " if ok else "FAIL ") + name + (f" — {detail}" if detail else ""), flush=True)


async def session(url: str):
    return Client(streamable_http_client(url, http_client=httpx2.AsyncClient(timeout=30)))


async def main() -> int:
    urls = settings().company_mcp_urls
    check("COMPANY_MCP_URLS 설정(2개사)", len(urls) >= 2, ", ".join(urls))
    top: dict[str, dict[str, dict]] = {}
    for company_id, url in urls.items():
        async with await session(url) as c:
            tools = {t.name: t for t in (await c.list_tools()).tools}
            check(f"{company_id} tools/list = search_criteria(읽기 전용)", set(tools) == {"search_criteria"}
                  and tools["search_criteria"].annotations.read_only_hint)
            for code, q in PAIRS:
                res = await c.call_tool("search_criteria", {"query": q, "top_k": 3})
                items = res.structured_content["data"]["items"]
                top.setdefault(code, {})[company_id] = items[0]
                check(f"{company_id} {code} 질의 → 조항", items and items[0]["company_id"] == company_id and items[0]["quote"],
                      f"{items[0]['doc_id']} {items[0]['section']} '{items[0]['title']}' ({items[0]['score']})")
            it = top["CO·N1"][company_id]
            rr = await c.read_resource(it["uri"])
            check(f"{company_id} resources/read {it['uri']} = 조항 원문", it["quote"] in rr.contents[0].text)
            bad = await c.call_tool("search_criteria", {"query": "", "top_k": 3})
            check(f"{company_id} 빈 질의 → INVALID_ARGUMENT", bad.is_error and bad.structured_content["error"]["code"] == "INVALID_ARGUMENT")
    ids = list(urls)[:2]
    for code, _ in PAIRS:
        a, b = (top[code][i] for i in ids)
        check(f"바꿔 꽂기: {code} 같은 질의 → 회사마다 다른 조항", (a["doc_id"], a["section"], a["title"]) != (b["doc_id"], b["section"], b["title"]),
              f"{ids[0]} {a['section']} '{a['title']}' ↔ {ids[1]} {b['section']} '{b['title']}'")
    failed = [n for n, ok, _ in results if not ok]
    print(f"\n결과: {len(results) - len(failed)}/{len(results)} PASS")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

"""MCP smoke: real SDK initialize → tools/list → tools/call → resources/read on both servers.

Creates a throwaway candidate session through the public API, then requests a scoped capability
through the internal API (service auth) exactly like the agent does.
"""
from __future__ import annotations

import asyncio
import json
import sys
import uuid
from urllib.parse import parse_qs, urlparse

import httpx
import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

from shared.config import DATA_DIR, settings

S = settings()
API = S.gateway_internal_url + "/api/v1"
INTERNAL = S.gateway_internal_url + "/internal/v1"
SVC = {"x-service-token": S.internal_service_secret}
results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(("PASS " if ok else "FAIL ") + name + (f" — {detail}" if detail else ""))


def make_running_run() -> tuple[str, str]:
    o = {"Origin": S.app_origin}
    a = httpx.Client(base_url=API, headers=o)
    csrf = a.post("/auth/login", json={"email": S.seed_admin_email, "password": S.seed_admin_password}).json()["csrf_token"]
    url = a.post("/invites", json={"alias": "smoke-mcp"}, headers={"X-CSRF-Token": csrf}).json()["invite_url"]
    c = httpx.Client(base_url=API, headers=o)
    e = c.post("/auth/exchange", json={"token": parse_qs(urlparse(url).query)["token"][0]}).json()
    h = {"X-CSRF-Token": e["csrf_token"]}
    c.post(f"/sessions/{e['session_id']}/start", json={"consent": True}, headers=h)
    r = c.post(f"/sessions/{e['session_id']}/messages",
               json={"client_message_id": uuid.uuid4().hex, "channel": "TEAM", "content": "smoke"}, headers=h).json()
    # Claim this run's job so a live agent worker does not race the smoke test, then mark it RUNNING.
    httpx.post(f"{INTERNAL}/runs/{r['run_id']}/state", json={"status": "RUNNING"}, headers=SVC).raise_for_status()
    return e["session_id"], r["run_id"]


def cap(run_id: str, audience: str) -> str:
    r = httpx.post(f"{INTERNAL}/runs/{run_id}/capability", json={"audience": audience}, headers=SVC)
    r.raise_for_status()
    return r.json()["token"]


def client(url: str, token: str | None) -> Client:
    headers = {"x-capability": token} if token else {}
    return Client(streamable_http_client(url, http_client=httpx2.AsyncClient(headers=headers, timeout=30)))


def payload(res) -> dict:
    return res.structured_content or json.loads(res.content[0].text)


async def main() -> int:
    sid, rid = make_running_run()
    btok, rtok = cap(rid, "business-mcp"), cap(rid, "rag-mcp")

    async with client(S.business_mcp_url, btok) as b:
        tools = {t.name: t for t in (await b.list_tools()).tools}
        check("business tools/list 5개", set(tools) == {"get_session_context", "get_funnel_metrics", "get_support_cases",
                                                      "update_task_status", "patch_artifact_section"}, ",".join(sorted(tools)))
        ann = tools["patch_artifact_section"].annotations
        check("변경 도구 destructiveHint=true/readOnlyHint=false", bool(ann and ann.destructive_hint and not ann.read_only_hint))
        ann = tools["get_funnel_metrics"].annotations
        check("조회 도구 readOnlyHint=true/destructiveHint=false", bool(ann and ann.read_only_hint and not ann.destructive_hint))

        p = payload(await b.call_tool("get_funnel_metrics", {"period": "current", "dimension": "overall"}))
        row = p["data"]["rows"][0]
        check("AT-02 current/all 10000/3000/2200, 이탈 0.78",
              (row["cart_sessions"], row["checkout_sessions"], row["orders"], row["abandonment_rate"]) == (10000, 3000, 2200, 0.78), str(row))
        p = payload(await b.call_tool("get_funnel_metrics", {"period": "current", "dimension": "visitor", "filters": {"device": "mobile"}}))
        got = {r["segment"]: (r["cart_sessions"], r["checkout_sessions"], r["orders"]) for r in p["data"]["rows"]}
        check("AT-02 current/mobile × visitor 중첩 필터", got == {"new": (4500, 950, 550), "returning": (2500, 800, 640)}, str(got))
        expected = {("baseline", "device"): {"mobile": (7000, 2100, 1680), "desktop": (3000, 1400, 1320)},
                    ("current", "device"): {"mobile": (7000, 1750, 1190), "desktop": (3000, 1250, 1010)},
                    ("current", "visitor"): {"new": (6000, 1560, 960), "returning": (4000, 1440, 1240)},
                    ("current", "cart_value"): {"low": (5800, 1530, 1080), "high": (4200, 1470, 1120)}}
        for (period, dim), exp in expected.items():
            p = payload(await b.call_tool("get_funnel_metrics", {"period": period, "dimension": dim}))
            got = {r["segment"]: (r["cart_sessions"], r["checkout_sessions"], r["orders"]) for r in p["data"]["rows"]}
            check(f"AT-02 {period}/{dim} 검산", got == exp, str(got))
        p = payload(await b.call_tool("get_funnel_metrics", {"period": "baseline", "dimension": "overall"}))
        check("AT-02 baseline 결제 후 이탈 14.2857%", abs(p["data"]["rows"][0]["checkout_abandonment_rate"] - 0.142857) < 1e-6)

        res = await b.call_tool("get_funnel_metrics", {"period": "current", "dimension": "overall", "filters": {"device": "tablet"}})
        check("잘못된 enum → 오류(프로토콜 검증 또는 INVALID_ARGUMENT)", bool(res.is_error))
        p = payload(await b.call_tool("get_support_cases", {"tags": ["shipping"], "limit": 5}))
        check("get_support_cases shipping 2건(VOC-01,06)", [i["id"] for i in p["data"]["items"]] == ["VOC-01", "VOC-06"])
        res = await b.call_tool("get_support_cases", {"tags": ["a", "b", "c", "d"], "limit": 5})
        check("tags 4개 → INVALID_ARGUMENT", res.is_error and payload(res)["error"]["code"] == "INVALID_ARGUMENT")
        res = await b.call_tool("patch_artifact_section", {"task_id": str(uuid.uuid4()), "section": "evidence", "base_version": 1,
                                                           "content": "x", "citations": []})
        check("승인 없는 변경 도구 → 권한 오류(isError)", bool(res.is_error), payload(res)["error"]["code"])

    async with client(S.business_mcp_url, None) as b:
        res = await b.call_tool("get_session_context", {})
        check("capability 없음 → FORBIDDEN", res.is_error and payload(res)["error"]["code"] == "FORBIDDEN")

    async with client(S.rag_mcp_url, rtok) as r:
        tools = [t.name for t in (await r.list_tools()).tools]
        check("rag tools/list = search_docs", tools == ["search_docs"])
        templates = (await r.list_resource_templates()).resource_templates
        check("rag resources/templates/list doc://{scenario_id}/{document_id}",
              any(t.uri_template == "doc://{scenario_id}/{document_id}" for t in templates))
        evalset = json.loads((DATA_DIR / "retrieval_eval.json").read_text())
        hits = 0
        for case in evalset:
            p = payload(await r.call_tool("search_docs", {"query": case["query"], "top_k": 3}))
            docs = [m["document_id"] for m in p["data"]["matches"]]
            hit = any(d in case["expected"] for d in docs)
            hits += hit
            check(f"AT-16 '{case['query']}' top-3 ⊇ {case['expected']}", hit and p["data"]["search_mode"] == "vector",
                  f"{docs} scores={[m['score'] for m in p['data']['matches']]}")
        check("AT-16 검색 평가 hit율", hits == len(evalset), f"{hits}/{len(evalset)}")
        rr = await r.read_resource("doc://commerce-cart-v1/operating-policy")
        text = rr.contents[0].text
        check("resources/read 원문에 50,000원 무료배송 문장 포함", "최종 장바구니 금액 50,000원 이상은 무료배송이다" in text)
        p = payload(await r.call_tool("search_docs", {"query": "무료배송 기준 금액", "top_k": 1}))
        m = p["data"]["matches"][0]
        check("인용 quote가 원문 연속 부분 문자열", m["quote"] in (await r.read_resource(f"doc://commerce-cart-v1/{m['document_id']}")).contents[0].text)

    async with client(S.rag_mcp_url, btok) as r:  # wrong audience
        res = await r.call_tool("search_docs", {"query": "배송", "top_k": 1})
        check("rag capability audience 불일치 → FORBIDDEN", bool(res.is_error))

    httpx.post(f"{INTERNAL}/runs/{rid}/state", json={"status": "SUCCEEDED"}, headers=SVC)
    failed = [n for n, ok, _ in results if not ok]
    print(f"\n결과: {len(results) - len(failed)}/{len(results)} PASS")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

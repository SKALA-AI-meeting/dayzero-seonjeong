"""company-mcp smoke: 같은 코드로 띄운 A사(:9201)·B사(:9202) 서버에 같은 질의를 보내 서로 다른 조항이 나오는지 확인하고,
같은 세션 리포트를 A사 → B사 기준으로 다시 생성했을 때 linked_criterion이 달라지는지 확인한다(끝나면 A사 기준으로 되돌림).
리포트 확인에는 완료 세션이 필요하다(scripts.seed_candidates).

uv run python -m scripts.smoke_company_mcp
"""
from __future__ import annotations

import asyncio
import sys
import time

import httpx
import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

from shared.config import settings

results: list[tuple[str, bool, str]] = []
PAIRS = [("CO·N1", "동료 문서를 말하지 않고 직접 고침"),
         ("CO+5", "동료 산출물의 문제를 근거와 함께 구체적으로 정정 요청"),
         ("RS+1", "지연·리스크를 마감 전에 먼저 알림")]


def check(name: str, ok, detail: str = "") -> bool:
    results.append((name, bool(ok), detail))
    print(("PASS " if ok else "FAIL ") + name + (f" — {detail}" if detail else ""), flush=True)
    return bool(ok)


async def session(url: str):
    return Client(streamable_http_client(url, http_client=httpx2.AsyncClient(timeout=30)))


def links(body: dict) -> dict:
    return {(c["key"], i, o["code"]): (o.get("linked_criterion") or {})
            for c in body["competencies"] for i, o in enumerate(c["observations"])}


def regenerate(adm: httpx.Client, sid: str, company_id: str) -> dict:
    r = adm.post(f"/reports/{sid}/retry", json={"company_id": company_id})
    if r.status_code != 202:
        return {"status": f"HTTP {r.status_code}"}
    for _ in range(60):
        rep = adm.get(f"/reports/{sid}").json()
        if rep["status"] in ("READY", "FAILED") and (rep.get("body") or {}).get("company", {}).get("company_id") == company_id:
            return rep
        time.sleep(1)
    return rep


def switch_report(ids: list[str]) -> None:
    S = settings()
    adm = httpx.Client(base_url=S.app_origin + "/api/v1", headers={"Origin": S.app_origin}, timeout=30)
    adm.headers["X-CSRF-Token"] = adm.post("/auth/login", json={"email": S.seed_admin_email, "password": S.seed_admin_password}).json()["csrf_token"]
    ready = [x for x in adm.get("/sessions").json()["items"] if x["report_status"] == "READY"]
    sess = next((x for x in ready if x["alias"] == "persona-solo"), ready[0] if ready else None)
    if not check("완료 세션(READY 리포트) 있음", sess, "scripts.seed_candidates 먼저 실행"):
        return
    sid = sess["id"]
    a = regenerate(adm, sid, ids[0])
    b = regenerate(adm, sid, ids[1])
    la, lb = links(a["body"]), links(b["body"])
    check(f"{ids[0]} 기준 리포트: 관찰 코드마다 조항 연결", a["status"] == "READY" and la and all(v.get("quote") for v in la.values()),
          f"{sess['alias']} {len(la)}개 코드")
    check(f"{ids[1]} 기준으로 다시 생성 → READY·회사 표시", b["status"] == "READY" and b["body"]["company"]["company_id"] == ids[1])
    check("관찰 코드·근거는 같음(회사 기준만 바뀜)", list(la) == list(lb))
    diff = [k for k in la if (la[k].get("company_id"), la[k].get("section"), la[k].get("title")) !=
            (lb[k].get("company_id"), lb[k].get("section"), lb[k].get("title"))]
    check("A사 → B사 재생성 시 linked_criterion 달라짐", len(diff) == len(la), f"{len(diff)}/{len(la)} 변경")
    for k in la:
        if k[2] == "CO·N1":
            check("CO·N1 연결 조항 비교", la[k]["title"] != lb[k]["title"], f"{la[k]['text']} ↔ {lb[k]['text']}")
    check("연결 문구는 판정이 아님(점수·합격·탈락 표현 없음)",
          not any(w in v["text"] for v in [*la.values(), *lb.values()] for w in ("점수", "합격", "탈락", "부적합")))
    check("설정에 없는 회사 → 400", adm.post(f"/reports/{sid}/retry", json={"company_id": "no-such"}).status_code == 400)
    regenerate(adm, sid, ids[0])  # 시연 상태(A사 기준)로 되돌림


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
    switch_report(ids)
    for code, _ in PAIRS:
        a, b = (top[code][i] for i in ids)
        check(f"바꿔 꽂기: {code} 같은 질의 → 회사마다 다른 조항", (a["doc_id"], a["section"], a["title"]) != (b["doc_id"], b["section"], b["title"]),
              f"{ids[0]} {a['section']} '{a['title']}' ↔ {ids[1]} {b['section']} '{b['title']}'")
    failed = [n for n, ok, _ in results if not ok]
    print(f"\n결과: {len(results) - len(failed)}/{len(results)} PASS")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

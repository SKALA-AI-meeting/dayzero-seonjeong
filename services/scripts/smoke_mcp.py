"""MCP smoke: real SDK initialize → tools/list → tools/call → resources/read → prompts/get on both servers.

Creates a throwaway candidate session through the public API, then requests a scoped capability
through the internal API (service auth) exactly like the agent does. 오류 처리(잘못된 ID, 다른 세션 접근,
capability 없음·audience 불일치, 승인 없는 변경, gateway 타임아웃)를 함께 확인한다.
"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import time
import uuid
from urllib.parse import parse_qs, urlparse

import httpx
import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

from shared.config import DATA_DIR, ROOT, settings

S = settings()
API = S.gateway_internal_url + "/api/v1"
INTERNAL = S.gateway_internal_url + "/internal/v1"
SVC = {"x-service-token": S.internal_service_secret}
results: list[tuple[str, bool, str]] = []
BUSINESS = {"get_session_context", "get_scenario", "get_next_event", "get_planted_error", "record_observation",
            "update_task_status", "patch_artifact_section"}


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, bool(ok), detail))
    print(("PASS " if ok else "FAIL ") + name + (f" — {detail}" if detail else ""))


def make_running_run(alias: str) -> tuple[str, str, str]:
    o = {"Origin": S.app_origin}
    a = httpx.Client(base_url=API, headers=o)
    csrf = a.post("/auth/login", json={"email": S.seed_admin_email, "password": S.seed_admin_password}).json()["csrf_token"]
    url = a.post("/invites", json={"alias": alias}, headers={"X-CSRF-Token": csrf}).json()["invite_url"]
    c = httpx.Client(base_url=API, headers=o)
    e = c.post("/auth/exchange", json={"token": parse_qs(urlparse(url).query)["token"][0]}).json()
    h = {"X-CSRF-Token": e["csrf_token"]}
    c.post(f"/sessions/{e['session_id']}/start", json={"consent": True}, headers=h)
    r = c.post(f"/sessions/{e['session_id']}/messages",
               json={"client_message_id": uuid.uuid4().hex, "channel": "TEAM", "content": "smoke"}, headers=h).json()
    # Claim this run so a live agent worker does not race the smoke test, then mark it RUNNING.
    httpx.post(f"{INTERNAL}/runs/{r['run_id']}/state", json={"status": "RUNNING"}, headers=SVC).raise_for_status()
    msg = c.get(f"/sessions/{e['session_id']}", headers=h).json()["messages"][-1]["id"]
    return e["session_id"], r["run_id"], msg


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
    sid, rid, my_msg = make_running_run("smoke-mcp")
    sid2, rid2, other_msg = make_running_run("smoke-mcp-2")
    btok, rtok = cap(rid, "business-mcp"), cap(rid, "rag-mcp")

    async with client(S.business_mcp_url, btok) as b:
        tools = {t.name: t for t in (await b.list_tools()).tools}
        check("business tools/list 7개", set(tools) == BUSINESS, ",".join(sorted(tools)))
        ann = tools["patch_artifact_section"].annotations
        check("변경 도구 destructiveHint=true/readOnlyHint=false", bool(ann and ann.destructive_hint and not ann.read_only_hint))
        ann = tools["get_scenario"].annotations
        check("조회 도구 readOnlyHint=true", bool(ann and ann.read_only_hint and not ann.destructive_hint))
        ann = tools["record_observation"].annotations
        check("record_observation: 비파괴·멱등(승인 불필요)", bool(ann and not ann.read_only_hint and not ann.destructive_hint and ann.idempotent_hint))
        p = payload(await b.call_tool("get_session_context", {}))
        check("get_session_context: 턴·경과 시간·보드", p["ok"] and p["data"]["elapsed_seconds"] == "09:00"
              and [t["key"] for t in p["data"]["tasks"]] == ["T1", "T2", "T3"], str(p["data"].get("turn_count")))
        p = payload(await b.call_tool("get_scenario", {}))
        txt = json.dumps(p["data"], ensure_ascii=False)
        check("get_scenario: 이벤트 7개 + 정답(planted_errors) 미포함", p["ok"] and len(p["data"]["events"]) == 7
              and "planted_errors" not in p["data"] and "11/2 ~ 11/31" not in txt)
        p = payload(await b.call_tool("get_next_event", {}))
        check("get_next_event: 다음 E1, 턴 5까지 남은 턴", p["ok"] and p["data"]["next"]["id"] == "E1"
              and p["data"]["next"]["turns_until"] == 5 - p["data"]["turn_count"], str(p["data"]["next"]))
        p = payload(await b.call_tool("get_planted_error", {"error_ids": ["PE-2"]}))
        it = p["data"]["items"][0]
        check("get_planted_error: confidential + 오답/정답/수정 규칙", p["data"]["confidential"] and it["wrong"] == "초대 1명당 5,000P"
              and it["fix"][0]["artifact"] == "T3")
        res = await b.call_tool("get_planted_error", {"error_ids": ["PE-9"]})
        check("잘못된 오류 ID → NOT_FOUND(isError)", res.is_error and payload(res)["error"]["code"] == "NOT_FOUND")
        res = await b.call_tool("record_observation", {"code": "XX+9", "evidence_ref": {"kind": "message", "id": my_msg}})
        check("코드북에 없는 코드 → INVALID_ARGUMENT", res.is_error and payload(res)["error"]["code"] == "INVALID_ARGUMENT")
        res = await b.call_tool("record_observation", {"code": "CO+5", "evidence_ref": {"kind": "message", "id": other_msg}})
        check("다른 세션 근거로 기록 시도 → NOT_FOUND", res.is_error and payload(res)["error"]["code"] == "NOT_FOUND")
        p = payload(await b.call_tool("record_observation", {"code": "CO+5", "evidence_ref": {"kind": "message", "id": my_msg},
                                                              "subject": "PE-1", "note": "smoke"}))
        check("record_observation 기록(승인 없이)", p["ok"] and p["data"]["recorded"] and p["data"]["competency"] == "COLLABORATION")
        p = payload(await b.call_tool("record_observation", {"code": "CO+5", "evidence_ref": {"kind": "message", "id": my_msg},
                                                              "subject": "PE-1", "note": "smoke"}))
        check("같은 코드·대상 재기록은 1회만(멱등)", p["ok"] and not p["data"]["recorded"])
        res = await b.call_tool("patch_artifact_section", {"artifact_key": "T3", "base_version": 1, "content": "x", "targets": ["PE-1"]})
        check("승인 없는 변경 도구 → 권한 오류(isError)", res.is_error, payload(res)["error"]["code"])
        res = await b.call_tool("get_session_context", {"session_id": sid2})
        check("다른 세션 ID 인자 → 거절", res.is_error or "session_id" not in json.dumps(payload(res)))

    async with client(S.business_mcp_url, None) as b:
        res = await b.call_tool("get_session_context", {})
        check("capability 없음 → FORBIDDEN", res.is_error and payload(res)["error"]["code"] == "FORBIDDEN")

    async with client(S.rag_mcp_url, rtok) as r:
        tools = sorted(t.name for t in (await r.list_tools()).tools)
        check("rag tools/list = search_criteria, search_docs", tools == ["search_criteria", "search_docs"], str(tools))
        templates = (await r.list_resource_templates()).resource_templates
        check("rag resources/templates/list doc://{scenario_id}/{document_id}",
              any(t.uri_template == "doc://{scenario_id}/{document_id}" for t in templates))
        prompts = sorted(p.name for p in (await r.list_prompts()).prompts)
        check("rag prompts/list = colleague_persona, manager_persona", prompts == ["colleague_persona", "manager_persona"], str(prompts))
        pr = await r.get_prompt("colleague_persona", {"event_directive": "E2B", "allow_pushback": "true"})
        text = pr.messages[0].content.text
        check("colleague_persona: 설계서 7장 초안 + Graph 플래그 주입", "한서윤" in text and "allow_pushback=true" in text and "E2B" in text)
        evalset = json.loads((DATA_DIR / "retrieval_eval.json").read_text())
        hits = 0
        for case in evalset:
            p = payload(await r.call_tool("search_docs", {"query": case["query"], "top_k": 3}))
            docs = [m["document_id"] for m in p["data"]["matches"]]
            hit = any(d in case["expected"] for d in docs)
            hits += hit
            check(f"검색 '{case['query']}' top-3 ⊇ {case['expected']}", hit and p["data"]["search_mode"] == "vector",
                  f"{docs} scores={[m['score'] for m in p['data']['matches']]}")
        check("검색 평가 hit율", hits == len(evalset), f"{hits}/{len(evalset)}")
        p = payload(await r.call_tool("search_docs", {"query": "도움 요청에 응답 협업 조율 행동 코드", "top_k": 5}))
        check("search_docs는 코드북(내부) 미포함", all(m["document_id"] != "criteria" for m in p["data"]["matches"]))
        for q, code in (("동료 산출물의 문제를 구체적으로 정정 요청", "CO+5"), ("변경 영향 확인 질문", "AD+1")):
            p = payload(await r.call_tool("search_criteria", {"query": q, "top_k": 3}))
            check(f"search_criteria '{q}' → 코드북 행 청크({code})", p["ok"] and p["data"]["matches"]
                  and p["data"]["matches"][0]["quote"].startswith(f"| {code} |"), str([m["quote"][:12] for m in p["data"]["matches"]]))
        text = (await r.read_resource("doc://sc-a/brief")).contents[0].text
        check("resources/read doc://sc-a/brief 원문(정답 기준)", "11/2 ~ 11/15" in text and "3,000P" in text)
        p = payload(await r.call_tool("search_docs", {"query": "리워드 지급 조건", "top_k": 1}))
        m = p["data"]["matches"][0]
        check("인용 quote가 원문 연속 부분 문자열", m["quote"] in (await r.read_resource(f"doc://sc-a/{m['document_id']}")).contents[0].text)
        try:
            await r.read_resource("doc://sc-a/criteria")
            ok = False
        except Exception:  # noqa: BLE001
            ok = True
        check("내부 코드북은 Resource로 읽을 수 없음", ok)
        try:
            await r.read_resource("doc://sc-a/no-such-doc")
            ok = False
        except Exception:  # noqa: BLE001
            ok = True
        check("없는 문서 ID → 오류", ok)

    async with client(S.rag_mcp_url, btok) as r:  # wrong audience
        res = await r.call_tool("search_docs", {"query": "기간", "top_k": 1})
        check("rag capability audience 불일치 → FORBIDDEN", bool(res.is_error))

    check("내부 API 타임아웃 → TIMEOUT(retryable) 구조화 오류", await timeout_check(btok))

    for x in (rid, rid2):
        httpx.post(f"{INTERNAL}/runs/{x}/state", json={"status": "SUCCEEDED"}, headers=SVC)
    failed = [n for n, ok, _ in results if not ok]
    print(f"\n결과: {len(results) - len(failed)}/{len(results)} PASS")
    return 1 if failed else 0


async def timeout_check(btok: str) -> bool:
    """gateway 대신 응답하지 않는 포트를 가리키는 business-mcp를 임시로 띄워 forward()의 TIMEOUT 경로를 확인한다."""
    import socket
    hang = socket.socket(); hang.bind(("127.0.0.1", 0)); hang.listen(1)  # accept하지 않아 응답이 오지 않음
    port = hang.getsockname()[1]
    env = {**os.environ, "GATEWAY_INTERNAL_URL": f"http://127.0.0.1:{port}"}
    code = "import uvicorn; from business_mcp.server import app; uvicorn.run(app, host='127.0.0.1', port=9199, log_level='error')"
    proc = subprocess.Popen([sys.executable, "-c", code], cwd=ROOT / "services", env=env)
    try:
        for _ in range(40):
            try:
                httpx.post("http://127.0.0.1:9199/mcp", json={}, timeout=1)
                break
            except Exception:  # noqa: BLE001
                time.sleep(0.25)
        async with client("http://127.0.0.1:9199/mcp", btok) as b:
            p = payload(await b.call_tool("get_scenario", {}))
        return (not p["ok"]) and p["error"]["code"] == "TIMEOUT" and p["error"]["retryable"]
    finally:
        proc.terminate(); hang.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

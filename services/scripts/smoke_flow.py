"""E2E smoke through the web origin (cookies + CSRF): start → 조사 → 위임 → 거절/승인 → 검토 → 제출 → 리포트."""
from __future__ import annotations

import argparse
import sys
import time
import uuid
from urllib.parse import parse_qs, urlparse

import httpx

from shared.config import settings

S = settings()
res: list[tuple[str, bool, str]] = []


def check(n, ok, d=""):
    res.append((n, ok, d)); print(("PASS " if ok else "FAIL ") + n + (f" — {d}" if d else ""), flush=True)


def wait(c, sid, pred, timeout=60):
    t = time.time()
    while time.time() - t < timeout:
        s = c.get(f"/sessions/{sid}").json()
        if pred(s):
            return s
        time.sleep(1)
    return c.get(f"/sessions/{sid}").json()


def main() -> int:
    ap = argparse.ArgumentParser(); ap.add_argument("--mode", default="fixture"); ap.add_argument("--base", default=S.app_origin)
    a = ap.parse_args()
    B = a.base + "/api/v1"; O = {"Origin": S.app_origin}
    adm = httpx.Client(base_url=B, headers=O, timeout=30)
    csrf = adm.post("/auth/login", json={"email": S.seed_admin_email, "password": S.seed_admin_password}).json()["csrf_token"]
    url = adm.post("/invites", json={"alias": f"smoke-{a.mode}"}, headers={"X-CSRF-Token": csrf}).json()["invite_url"]
    c = httpx.Client(base_url=B, headers=O, timeout=30)
    e = c.post("/auth/exchange", json={"token": parse_qs(urlparse(url).query)["token"][0]}).json()
    sid = e["session_id"]; c.headers["X-CSRF-Token"] = e["csrf_token"]
    c.post(f"/sessions/{sid}/start", json={"consent": True})
    health = httpx.get(B + "/health").json()
    check("health mode 일치", health["mode"] == a.mode, str(health))

    # AT-03 조사
    r = c.post(f"/sessions/{sid}/messages", json={"client_message_id": uuid.uuid4().hex, "channel": "TEAM",
                                                  "content": "current 기간 모바일 신규 고객의 장바구니 이탈 지표와 배송 관련 고객 문의를 조사해 주세요"})
    check("AT-03 202", r.status_code == 202)
    s = wait(c, sid, lambda s: any(m["actor"] == "COLLEAGUE" for m in s["messages"]) and not s["active_run"])
    col = [m for m in s["messages"] if m["actor"] == "COLLEAGUE"]
    check("AT-03 동료 근거 응답", bool(col) and len(col[-1]["citations"]) > 0, (col[-1]["content"][:160] if col else "응답 없음"))
    with c.stream("GET", f"/sessions/{sid}/events?after_seq=0") as st:
        types = []
        for line in st.iter_lines():
            if line.startswith("event: "): types.append(line[7:])
            if "DONE" in types or len(types) > 30: break
    check("AT-03 SSE RUN_STARTED→TOOL_START/END→COLLEAGUE_MESSAGE→DONE",
          all(t in types for t in ("RUN_STARTED", "TOOL_START", "TOOL_END", "COLLEAGUE_MESSAGE", "DONE")), ",".join(types))

    # AT-04 위임 제안 → 확인
    r = c.post(f"/sessions/{sid}/messages", json={"client_message_id": uuid.uuid4().hex, "channel": "TEAM",
                                                  "content": "모바일 신규 고객 조사는 도현님께 위임할게요"})
    s = wait(c, sid, lambda s: any(m["meta"].get("delegation_proposal") for m in s["messages"]) and not s["active_run"])
    prop = next((m["meta"]["delegation_proposal"] for m in s["messages"] if m["meta"].get("delegation_proposal")), None)
    check("AT-04 위임 제안 카드", bool(prop), str(prop))
    if not prop: return 1
    art_v = s["artifact"]["version"]; key = uuid.uuid4().hex
    body = {k: prop[k] for k in ("source_message_id", "title", "target_section", "allowed_tools", "filters")}
    d1 = c.post(f"/sessions/{sid}/delegations", json=body, headers={"Idempotency-Key": key})
    d2 = c.post(f"/sessions/{sid}/delegations", json=body, headers={"Idempotency-Key": key})
    check("AT-04 delegation 201 + 같은 key 멱등", d1.status_code == 201 and d1.json() == d2.json(), str(d1.status_code))
    s = wait(c, sid, lambda s: len(s["approvals"]) == 1)
    check("AT-05 승인 대기 카드", len(s["approvals"]) == 1 and s["artifact"]["version"] == art_v)
    check("AT-05 승인 전 문서 무변경", s["artifact"]["sections"]["evidence"] == "")
    a1 = s["approvals"][0]
    r = c.post(f"/sessions/{sid}/approvals/{a1['id']}/decision", json={"decision": "REJECT"})
    s = wait(c, sid, lambda s: not s["active_run"] and any(t["owner"] == "COLLEAGUE" and t["status"] == "REVIEW" for t in s["tasks"]))
    check("AT-05 거절 후 무변경", s["artifact"]["version"] == art_v and s["artifact"]["sections"]["evidence"] == "")
    task = next(t for t in s["tasks"] if t["owner"] == "COLLEAGUE")
    r = c.post(f"/sessions/{sid}/tasks/{task['id']}/review", json={"decision": "REVISE", "comment": "다시 제안해 주세요", "source_refs": []})
    check("REVISE → 새 run", r.status_code == 200 and r.json()["run_id"], r.text[:120])
    s = wait(c, sid, lambda s: len(s["approvals"]) == 1)
    a2 = s["approvals"][0]
    r1 = c.post(f"/sessions/{sid}/approvals/{a2['id']}/decision", json={"decision": "APPROVE"})
    r2 = c.post(f"/sessions/{sid}/approvals/{a2['id']}/decision", json={"decision": "APPROVE"})
    s = wait(c, sid, lambda s: not s["active_run"] and s["artifact"]["version"] > art_v)
    check("AT-05 승인 후 revision 1개, 중복 결정 무해", s["artifact"]["version"] == art_v + 1 and r2.status_code == 202,
          f"v{art_v}→v{s['artifact']['version']}")
    check("AT-05 evidence에 동료 요약 반영", "동료 조사" in s["artifact"]["sections"]["evidence"])
    r3 = c.post(f"/sessions/{sid}/approvals/{a2['id']}/decision", json={"decision": "REJECT"})
    check("다른 결정 재전송 409", r3.status_code == 409, r3.text[:80])

    # 직접 작성 + 제출
    v = s["artifact"]["version"]
    for sec, txt in (("problem", "모바일 신규 고객의 결제 진입 후 이탈 증가"), ("options", "배송비 사전 안내와 가입 마찰 완화 비교"),
                     ("experiment", "배송비 안내 A/B, 성공지표 주문 전환, 보호지표 문의")):
        v = c.patch(f"/sessions/{sid}/artifact", json={"base_version": v, "section": sec, "content": txt, "source_refs": []}).json()["artifact"]["version"]
    t = next(t for t in c.get(f"/sessions/{sid}").json()["tasks"] if t["owner"] == "COLLEAGUE")
    c.post(f"/sessions/{sid}/tasks/{t['id']}/review", json={"decision": "ACCEPT", "comment": "", "source_refs": []})
    r = c.post(f"/sessions/{sid}/submit", json={"base_version": v, "summary": ""})
    check("AT-07 제출 202", r.status_code == 202, r.text[:100])
    late = c.patch(f"/sessions/{sid}/artifact", json={"base_version": v, "section": "risks", "content": "late", "source_refs": []})
    check("AT-12 제출 후 쓰기 차단", late.status_code == 409, late.text[:80])
    t0 = time.time(); rep = {}
    while time.time() - t0 < 30:
        rep = adm.get(f"/reports/{sid}").json()
        if rep.get("status") == "READY": break
        time.sleep(1)
    check("AT-07 리포트 READY", rep.get("status") == "READY", rep.get("status", ""))
    txt = str(rep.get("body", ""))
    check("AT-07 score/rank/pass/fail 필드 없음", not any(k in txt for k in ("'score'", "'rank'", "'pass'", "'fail'")))
    check("AT-11 지원자는 리포트 조회 불가", c.get(f"/reports/{sid}").status_code == 403)
    deb = c.get(f"/sessions/{sid}/debrief")
    check("디브리핑 200", deb.status_code == 200, str([o["event_id"] for o in deb.json().get("occurred_events", [])]))
    failed = [n for n, ok, _ in res if not ok]
    print(f"\n결과: {len(res) - len(failed)}/{len(res)} PASS (session {sid})")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

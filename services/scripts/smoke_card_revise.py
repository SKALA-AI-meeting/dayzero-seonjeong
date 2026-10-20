"""확인 카드의 '검토 사항 + 재수정 요청' 재현 스모크(live 권장). PYTHONPATH=. uv run python -m scripts.smoke_card_revise"""
import sys, time, uuid
from urllib.parse import parse_qs, urlparse
import httpx
from shared.config import settings
S = settings(); B = S.app_origin + "/api/v1"; O = {"Origin": S.app_origin}
adm = httpx.Client(base_url=B, headers=O, timeout=30)
adm.headers["X-CSRF-Token"] = adm.post("/auth/login", json={"email": S.seed_admin_email, "password": S.seed_admin_password}).json()["csrf_token"]
url = adm.post("/invites", json={"alias": "smoke-card-revise"}).json()["invite_url"]
c = httpx.Client(base_url=B, headers=O, timeout=30)
e = c.post("/auth/exchange", json={"token": parse_qs(urlparse(url).query)["token"][0]}).json(); sid = e["session_id"]; c.headers["X-CSRF-Token"] = e["csrf_token"]
c.post(f"/sessions/{sid}/start", json={"consent": True})
snap = lambda: c.get(f"/sessions/{sid}").json()
def wait(pred, t=180):
    t0 = time.time()
    while time.time() - t0 < t:
        s = snap()
        if pred(s): return s
        time.sleep(1.5)
    return snap()
ok = []
def check(n, cond, d=""):
    ok.append(cond); print(("PASS " if cond else "FAIL ") + n + (f" — {d}" if d else ""))
adm.post(f"/sessions/{sid}/demo/advance", json={"to_event": "T-SPLIT"})
s = snap(); c.post(f"/sessions/{sid}/split", json={"decision": "ACCEPT", "assignments": s["split"]["assignments"]})
s = wait(lambda s: len(s["approvals"]) == 2); a = {x["before_after"]["section"]: x for x in s["approvals"]}
first = a["similar_cases"]
r = c.post(f"/sessions/{sid}/approvals/{first['id']}/decision", json={"decision": "REVISE", "comment": ""})
check("검토 사항 없이 재수정 요청 → 422", r.status_code == 422, str(r.status_code))
note = "효과 수치가 없는 '가능성' 표현은 빼고, 두 사례를 비교 기준(첫 참가자 지원, 일정 안내) 중심으로 정리해 주세요"
r = c.post(f"/sessions/{sid}/approvals/{first['id']}/decision", json={"decision": "REVISE", "comment": note})
check("재수정 요청 202", r.status_code == 202, r.text[:80])
s = wait(lambda s: any(x["before_after"]["section"] == "similar_cases" and x["id"] != first["id"] for x in s["approvals"]))
new = next((x for x in s["approvals"] if x["before_after"]["section"] == "similar_cases" and x["id"] != first["id"]), None)
check("현재 초안은 문서에 반영되지 않음", s["artifact"]["sections"]["similar_cases"] == "")
check("새 확인 카드 생성", bool(new))
if new:
    check("새 초안이 이전 초안과 다름", new["before_after"]["after"] != first["before_after"]["after"])
    check("'가능성' 표현 제거", "가능성" not in new["before_after"]["after"], new["before_after"]["after"].replace("\n", " ")[:200])
msg = [m for m in s["messages"] if m["actor"] == "COLLEAGUE" and "검토 사항" in m["content"]]
check("동료 안내 메시지", bool(msg), msg[-1]["content"] if msg else "")
print(f"\n결과: {sum(ok)}/{len(ok)} PASS (session {sid})")
sys.exit(0 if all(ok) else 1)

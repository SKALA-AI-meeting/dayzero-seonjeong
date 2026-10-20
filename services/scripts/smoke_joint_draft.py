"""공동 섹션(핵심 기능) 초안에 지원자의 채팅 제안이 반영되는지 재현 스모크(live). PYTHONPATH=. uv run python -m scripts.smoke_joint_draft"""
import sys, time, uuid
from urllib.parse import parse_qs, urlparse
import httpx
from shared.config import settings
S = settings(); B = S.app_origin + "/api/v1"; O = {"Origin": S.app_origin}
adm = httpx.Client(base_url=B, headers=O, timeout=30)
adm.headers["X-CSRF-Token"] = adm.post("/auth/login", json={"email": S.seed_admin_email, "password": S.seed_admin_password}).json()["csrf_token"]
url = adm.post("/invites", json={"alias": "smoke-joint"}).json()["invite_url"]
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
def say(text):
    wait(lambda s: not any(r["kind"] == "COLLEAGUE" and r["status"] in ("QUEUED", "RUNNING") for r in s["active_runs"]))
    n = len([m for m in snap()["messages"] if m["actor"] == "COLLEAGUE"])
    r = c.post(f"/sessions/{sid}/messages", json={"client_message_id": uuid.uuid4().hex, "channel": "TEAM", "content": text})
    assert r.status_code == 202, r.text
    s = wait(lambda s: len([m for m in s["messages"] if m["actor"] == "COLLEAGUE"]) > n)
    return [m for m in s["messages"] if m["actor"] == "COLLEAGUE"][-1]["content"]
adm.post(f"/sessions/{sid}/demo/advance", json={"to_event": "T-INTERVIEW"})
s = snap(); c.post(f"/sessions/{sid}/split", json={"decision": "ACCEPT", "assignments": s["split"]["assignments"]})
s = wait(lambda s: len(s["approvals"]) == 2)
for a in s["approvals"]: c.post(f"/sessions/{sid}/approvals/{a['id']}/decision", json={"decision": "APPROVE"})
say("핵심 기능 좀 생각해보셨나요?")
say("사용자 인터뷰를 보면 정확한 모임 출발 위치를 당일에야 알 수 있어서 망설인다는 의견이 있어요. 운영 정책상 동네 단위까지만 공개하니까, "
    "모임 하루 전에 동네 단위 집결 장소를 미리 안내하는 기능을 제안하고 싶어요. 그리고 첫 참가자에게 리더가 환영 메시지를 보내는 기능도요.")
say("다음 모임 일정 알림도 같이 넣으면 좋을까요?")
say("인터뷰에서 페이스가 안 맞았다는 의견도 있었죠?")
n = len(snap()["approvals"])
rep = say("초안 작성 부탁드리겠습니다. 아까 제가 제안드린 기능도 반영해주실수 있나요??")
s = wait(lambda s: any(a["before_after"]["section"] == "features" for a in s["approvals"]))
f = next((a for a in s["approvals"] if a["before_after"]["section"] == "features"), None)
after = f["before_after"]["after"] if f else ""
ok = [bool(f), any(w in after for w in ("집결", "출발", "위치")), "환영" in after]
print("동료 답변:", rep)
print("핵심 기능 초안:\n" + after)
print(("PASS" if all(ok) else "FAIL"), "카드 생성 / 출발 위치 제안 반영 / 환영 메시지 제안 반영 =", ok)
sys.exit(0 if all(ok) else 1)

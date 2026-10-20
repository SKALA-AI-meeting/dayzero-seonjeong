"""확인 카드 승인/거절 후 태스크 상태, 거절 후 재작성 요청, 대화 맥락 기반 초안 요청 재현 스모크(live 권장). PYTHONPATH=. uv run python -m scripts.smoke_task"""
import time, uuid, httpx
from urllib.parse import urlparse, parse_qs
from shared.config import settings
S = settings(); B = S.app_origin + "/api/v1"; O = {"Origin": S.app_origin}
adm = httpx.Client(base_url=B, headers=O, timeout=30)
adm.headers["X-CSRF-Token"] = adm.post("/auth/login", json={"email": S.seed_admin_email, "password": S.seed_admin_password}).json()["csrf_token"]
url = adm.post("/invites", json={"alias": "smoke-task"}).json()["invite_url"]
c = httpx.Client(base_url=B, headers=O, timeout=30)
e = c.post("/auth/exchange", json={"token": parse_qs(urlparse(url).query)["token"][0]}).json(); sid = e["session_id"]; c.headers["X-CSRF-Token"] = e["csrf_token"]
c.post(f"/sessions/{sid}/start", json={"consent": True})
snap = lambda: c.get(f"/sessions/{sid}").json()
task = lambda s, k: next(t for t in s["tasks"] if t["template_key"] == k)
def wait(pred, t=180):
    t0 = time.time()
    while time.time() - t0 < t:
        s = snap()
        if pred(s): return s
        time.sleep(1.5)
    return snap()
def say(text):
    n = len([m for m in snap()["messages"] if m["actor"] == "COLLEAGUE"])
    c.post(f"/sessions/{sid}/messages", json={"client_message_id": uuid.uuid4().hex, "channel": "TEAM", "content": text})
    s = wait(lambda s: len([m for m in s["messages"] if m["actor"] == "COLLEAGUE"]) > n)
    return [m for m in s["messages"] if m["actor"] == "COLLEAGUE"][-1]["content"]
adm.post(f"/sessions/{sid}/demo/advance", json={"to_event": "T-SPLIT"})
s = snap(); c.post(f"/sessions/{sid}/split", json={"decision": "ACCEPT", "assignments": s["split"]["assignments"]})
s = wait(lambda s: len(s["approvals"]) == 2); a = {x["before_after"]["section"]: x for x in s["approvals"]}
c.post(f"/sessions/{sid}/approvals/{a['similar_cases']['id']}/decision", json={"decision": "APPROVE"})
c.post(f"/sessions/{sid}/approvals/{a['metrics_timeline']['id']}/decision", json={"decision": "REJECT"})
s = wait(lambda s: task(s, "similar_cases")["status"] == "DONE" and (task(s, "metrics_timeline")["result"] or {}).get("rejected"))
print("[승인] 유사 사례 태스크:", task(s, "similar_cases")["status"])
print("[거절] 성공 지표 태스크:", task(s, "metrics_timeline")["status"], "rejected=", (task(s, "metrics_timeline")["result"] or {}).get("rejected"))
t = task(s, "metrics_timeline")
r = c.post(f"/sessions/{sid}/tasks/{t['id']}/review", json={"decision": "REVISE", "comment": "목표치 없이 핵심 지표와 측정 방법 위주로 다시 써 주세요", "source_refs": []})
print("[거절 후 다시 작성 요청]", r.status_code)
s = wait(lambda s: any(x["before_after"]["section"] == "metrics_timeline" for x in s["approvals"]))
print("    새 확인 카드:", [x["before_after"]["section"] for x in s["approvals"]])
for x in s["approvals"]: c.post(f"/sessions/{sid}/approvals/{x['id']}/decision", json={"decision": "APPROVE"})
s = wait(lambda s: task(s, "metrics_timeline")["status"] == "DONE")
print("    승인 후 태스크:", task(s, "metrics_timeline")["status"])
print("[핵심 기능 대화]", say("핵심 기능 좀 생각해보셨나요???")[:120].replace("\n", " "))
n = len(snap()["approvals"])
rep = say("넵 먼저 초안 작성 해주시면 제가 수정해서 최종으로 작성 제출 하겠습니다.")
print("[초안 요청 답변]", rep.replace("\n", " "))
s = wait(lambda s: len(s["approvals"]) > n)
print("    실제 확인 카드:", [x["before_after"]["section"] for x in s["approvals"]])
f = next((x for x in s["approvals"] if x["before_after"]["section"] == "features"), None)
if f: print("    핵심 기능 초안:\n" + f["before_after"]["after"])
print("session", sid)

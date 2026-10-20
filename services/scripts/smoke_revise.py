"""수정 요청 재작성·채팅 수정 요청·피드백 요청 재현 스모크 (live 권장). PYTHONPATH=. uv run python -m scripts.smoke_revise"""
import time, uuid, httpx
from urllib.parse import urlparse, parse_qs
from shared.config import settings
S = settings(); B = S.app_origin + "/api/v1"; O = {"Origin": S.app_origin}
adm = httpx.Client(base_url=B, headers=O, timeout=30)
adm.headers["X-CSRF-Token"] = adm.post("/auth/login", json={"email": S.seed_admin_email, "password": S.seed_admin_password}).json()["csrf_token"]
url = adm.post("/invites", json={"alias": "smoke-revise"}).json()["invite_url"]
c = httpx.Client(base_url=B, headers=O, timeout=30)
e = c.post("/auth/exchange", json={"token": parse_qs(urlparse(url).query)["token"][0]}).json(); sid = e["session_id"]; c.headers["X-CSRF-Token"] = e["csrf_token"]
c.post(f"/sessions/{sid}/start", json={"consent": True})
snap = lambda: c.get(f"/sessions/{sid}").json()
def wait(pred, t=150):
    t0 = time.time()
    while time.time() - t0 < t:
        s = snap()
        if pred(s): return s
        time.sleep(1.5)
    return snap()
adm.post(f"/sessions/{sid}/demo/advance", json={"to_event": "T-SPLIT"})
s = snap(); c.post(f"/sessions/{sid}/split", json={"decision": "ACCEPT", "assignments": s["split"]["assignments"]})
s = wait(lambda s: len(s["approvals"]) == 2)
a = {x["before_after"]["section"]: x for x in s["approvals"]}
c.post(f"/sessions/{sid}/approvals/{a['similar_cases']['id']}/decision", json={"decision": "APPROVE"})
s = wait(lambda s: s["artifact"]["sections"]["similar_cases"].strip() != "" and any(t["template_key"] == "similar_cases" and t["status"] == "REVIEW" for t in s["tasks"]))
v1 = s["artifact"]["sections"]["similar_cases"]
t = next(t for t in s["tasks"] if t["template_key"] == "similar_cases")
c.post(f"/sessions/{sid}/tasks/{t['id']}/review", json={"decision": "REVISE", "comment": "두 사례의 효과 수치가 확인되지 않았는데 어떻게 가능성을 보인다는 건지 연결이 안 되는 것 같습니다. 확인하고 수정 부탁드리겠습니다", "source_refs": []})
s = wait(lambda s: any(x["before_after"]["section"] == "similar_cases" for x in s["approvals"]))
ap = next(x for x in s["approvals"] if x["before_after"]["section"] == "similar_cases")
after = ap["before_after"]["after"]
print("[1] REVISE 확인 카드 생성:", bool(ap))
print("    변경 전 = 현재 섹션:", ap["before_after"]["before"] == v1)
print("    변경 후가 기존 내용 + 덧붙임 아님:", not after.startswith(v1.strip()))
print("    '가능성' 표현 잔존:", "가능성" in after)
print("    변경 후 본문:\n" + after)
c.post(f"/sessions/{sid}/approvals/{ap['id']}/decision", json={"decision": "APPROVE"})
s = wait(lambda s: s["artifact"]["sections"]["similar_cases"] == after)
print("    승인 후 섹션 = 재작성본(덧붙임 없음):", s["artifact"]["sections"]["similar_cases"] == after)
t = next(t for t in s["tasks"] if t["template_key"] == "similar_cases")
print("    태스크 상태/요약 갱신:", t["status"], (t["result"] or {}).get("summary", "")[:60].replace("\n", " "))
adm.post(f"/sessions/{sid}/demo/advance", json={"to_event": "T-PIVOT"})
n_before = len(snap()["approvals"])
c.post(f"/sessions/{sid}/messages", json={"client_message_id": uuid.uuid4().hex, "channel": "TEAM", "content": "도현님 공지확인하셨나요??? 제가 다른 작업 중이라서 그런데 수정해야하는 부분 확인하고 수정까지 부탁드릴수 있을까요???"})
s = wait(lambda s: any(m["actor"] == "COLLEAGUE" and "다시 작성" in m["content"] for m in s["messages"]))
reply = [m for m in s["messages"] if m["actor"] == "COLLEAGUE"][-1]["content"]
print("[2] 동료 답변:", reply)
s = wait(lambda s: len(s["approvals"]) > n_before, 200)
print("    실제 확인 카드 생성:", [x["before_after"]["section"] for x in s["approvals"]])
p = next((x for x in s["approvals"] if x["before_after"]["section"] == "problem"), None)
if p: print("    문제 정의 변경 후:\n" + p["before_after"]["after"])
print("session", sid)
v = snap()["artifact"]["version"]
for sec, txt in (("problem", "3개월 이상 모임에 참여하지 않은 휴면 사용자가 다시 모임에 돌아오지 않는 문제"), ("interview_evidence", "아는 사람이 없어 어색하다는 의견(INT-01, INT-03, INT-06)과 다음 일정을 놓쳤다는 의견(INT-02, INT-05, INT-07)")):
    r = c.patch(f"/sessions/{sid}/artifact", json={"base_version": v, "section": sec, "content": txt, "source_refs": []}); v = r.json()["artifact"]["version"] if r.status_code == 200 else snap()["artifact"]["version"]
n = len([m for m in snap()["messages"] if m["actor"] == "COLLEAGUE"])
c.post(f"/sessions/{sid}/messages", json={"client_message_id": uuid.uuid4().hex, "channel": "TEAM", "content": "1,2번 작성 완료했습니다 확인하고 피드백 주시면 감사하겠습니다"})
s = wait(lambda s: len([m for m in s["messages"] if m["actor"] == "COLLEAGUE"]) > n)
fb = [m for m in s["messages"] if m["actor"] == "COLLEAGUE"][-1]["content"]
print("[3] 피드백 답변:", fb)
print("    미루는 말 없음:", not any(w in fb for w in ("잠시만", "기다려", "확인해볼게", "확인해 볼게")))

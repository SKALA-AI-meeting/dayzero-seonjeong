"""E2E smoke: 핏모아 sc-a 턴 기반 흐름을 웹 origin(쿠키 + CSRF)으로 끝까지 실행한다.

세션 A (전체 흐름, 데모 이동 없이 실제 턴으로):
  E0 분업(불균형 제안 → 반문 1회 → 균형 확정) → 보드 예상 시각(PL+1) → E1 도움 요청(시간 약속, 약속 등록)
  → PE-1 정정 요청 → 서윤 수정안 승인 카드 → 승인 → 반영 → PE-2 직접 수정(CO·N1) → E2 요구사항 변경
  → 팀장에게 영향 질문(AD+1) → 보드 갱신(PL+2) → E2B 서윤 '다 했어요' → 반영 요청 → 반문 1회 → 이유를 들어 재요청(CO+6)
  → 수정안 2건 승인 → E3 서윤 이탈 → 인계 질문(CO+4) → E3B 복귀 → 해결 중심 공유(CO+3) → E4 브리핑 → 보고(HO+1·HO+2)
  → 후속 질문 정정(HO+3) → 자동 종료 → 디브리핑·소감 → 리포트(5역량 × 코드 + 근거 원문)
세션 B (조건부 E2B): E2에서 이미 서윤에게 반영을 요청하면 E2B는 건너뛰고(skipped) 반문은 그 시점에 1회.

uv run python -m scripts.smoke_flow --mode fixture
"""
from __future__ import annotations

import argparse
import re
import sys
import time
import uuid
from urllib.parse import parse_qs, urlparse

import httpx

from shared.config import settings

S = settings()
res: list[tuple[str, bool, str]] = []
PUSHBACK = "제가 하는 게 맞을까요"


def check(n, ok, d=""):
    res.append((n, bool(ok), d)); print(("PASS " if ok else "FAIL ") + n + (f" — {d}" if d else ""), flush=True)


class Sess:
    def __init__(self, base: str, adm: httpx.Client, alias: str):
        self.adm = adm
        url = adm.post("/invites", json={"alias": alias}).json()["invite_url"]
        self.c = httpx.Client(base_url=base, headers={"Origin": S.app_origin}, timeout=30)
        e = self.c.post("/auth/exchange", json={"token": parse_qs(urlparse(url).query)["token"][0]}).json()
        self.sid = e["session_id"]
        self.c.headers["X-CSRF-Token"] = e["csrf_token"]
        self.c.post(f"/sessions/{self.sid}/start", json={"consent": True})

    def snap(self) -> dict:
        return self.c.get(f"/sessions/{self.sid}").json()

    def wait(self, pred, timeout=60) -> dict:
        t = time.time()
        while time.time() - t < timeout:
            s = self.snap()
            if s.get("session", {}).get("status") == "SUBMITTED" or pred(s):
                return s
            time.sleep(0.7)
        return self.snap()

    def idle(self, s: dict) -> bool:
        return not s["active_run"]

    def say(self, text: str, to: str = "COLLEAGUE") -> tuple[httpx.Response, dict]:
        before = len(self.snap()["messages"])
        r = self.c.post(f"/sessions/{self.sid}/messages", json={"client_message_id": uuid.uuid4().hex, "channel": "TEAM",
                                                                 "content": text, "to": to})
        s = self.wait(lambda s: (not s["active_run"] or s["active_run"]["status"] == "WAITING_APPROVAL") and len(s["messages"]) > before)
        return r, s

    def last(self, s: dict, actor: str | None = None) -> dict:
        ms = [m for m in s["messages"] if actor is None or m["actor"] == actor]
        return ms[-1] if ms else {"content": "", "meta": {}}

    def approve(self, decision: str = "APPROVE") -> tuple[httpx.Response, dict]:
        s = self.wait(lambda s: s["approvals"])
        a = s["approvals"][0]
        r = self.c.post(f"/sessions/{self.sid}/approvals/{a['id']}/decision", json={"decision": decision})
        return r, a

    def task(self, s: dict, key: str) -> dict:
        return next(t for t in s["tasks"] if t["key"] == key)

    def art(self, s: dict, key: str) -> dict:
        return next(a for a in s["artifacts"] if a["key"] == key)


def main() -> int:
    ap = argparse.ArgumentParser(); ap.add_argument("--mode", default="fixture"); ap.add_argument("--base", default=S.app_origin)
    a = ap.parse_args()
    B = a.base + "/api/v1"
    adm = httpx.Client(base_url=B, headers={"Origin": S.app_origin}, timeout=30)
    adm.headers["X-CSRF-Token"] = adm.post("/auth/login", json={"email": S.seed_admin_email, "password": S.seed_admin_password}).json()["csrf_token"]
    check("health mode 일치", httpx.get(B + "/health").json()["mode"] == a.mode)

    # ===== 세션 A: 전체 흐름 =====
    x = Sess(B, adm, f"smoke-{a.mode}")
    s = x.snap()
    check("E0 스탠드업: 팀장 지시 + 서윤 분업 질문(고정 대사)", [m["actor"] for m in s["messages"]] == ["MANAGER", "COLLEAGUE"]
          and all(m["meta"].get("kind") == "SCENARIO_EVENT" for m in s["messages"]) and "편한 쪽 먼저 골라주세요" in s["messages"][1]["content"])
    check("초기 보드 T1~T3·산출물(서윤 초안 T2·T3) · 가상 시각 09:00 · 턴 0",
          [t["key"] for t in s["tasks"]] == ["T1", "T2", "T3"] and "11/2 ~ 11/31" in x.art(s, "T3")["body"]
          and "쏴드림" in x.art(s, "T2")["body"] and s["clock"]["virtual_time"] == "09:00" and s["session"]["turn_count"] == 0)
    docs = x.c.get(f"/sessions/{x.sid}/documents").json()["items"]
    check("공유 문서 4개(코드북 비공개)", [d["id"] for d in docs] == ["brief", "reward-table", "faq-draft", "tone-guide"])
    check("코드북 직접 열람 404", x.c.get(f"/sessions/{x.sid}/documents/criteria").status_code == 404)

    r = x.c.post(f"/sessions/{x.sid}/split", json={"proposal": {"T1": "CANDIDATE", "T3": "COLLEAGUE", "faq_candidate": 0}})
    s = x.wait(x.idle)
    check("E0 불균형 분업 → 서윤 반문 1회(재협상 기회)", r.status_code == 202 and "빠듯할 수도" in x.last(s, "COLLEAGUE")["content"]
          and not s["split"]["confirmed"], x.last(s)["content"][:60])
    r = x.c.post(f"/sessions/{x.sid}/split", json={"proposal": {"T1": "CANDIDATE", "T3": "COLLEAGUE", "faq_candidate": 3}})
    s = x.wait(lambda s: s["split"]["confirmed"])
    check("E0 균형 분업 → '좋아요, 그렇게 가요!' + 확정 + 보드 담당 반영", s["split"]["confirmed"]
          and any(m["content"] == "좋아요, 그렇게 가요!" for m in s["messages"])
          and x.task(s, "T1")["owner"] == "CANDIDATE" and x.task(s, "T3")["owner"] == "COLLEAGUE" and x.task(s, "T2")["owner"] == "SPLIT")
    t1 = x.task(s, "T1")
    r = x.c.patch(f"/sessions/{x.sid}/tasks/T1", json={"base_version": t1["version"], "eta": "11:00", "status": "IN_PROGRESS"})
    check("보드에 예상 완료 시각 기록", r.status_code == 200 and r.json()["task"]["eta"] == "11:00")
    _, s = x.say("서윤 씨, 저는 안내문부터 쓸게요.")
    check("일반 대화 → 서윤 짧은 답(분기 없음)", x.last(s, "COLLEAGUE")["content"] != "" and s["session"]["turn_count"] == 4,
          x.last(s, "COLLEAGUE")["content"])
    a1 = x.art(s, "T1")
    r = x.c.patch(f"/sessions/{x.sid}/artifacts/T1", json={"base_version": a1["version"], "body": "핏모아 친구 초대 이벤트를 소개합니다. 기간은 11/2부터입니다."})
    s = x.wait(lambda s: "E1" in s["events"])
    check("턴 5 → E1 서윤 도움 요청(가상 시각 10:30)", "E1" in s["events"] and s["clock"]["virtual_time"] == "10:30"
          and "급한 건 아니에요" in x.last(s, "COLLEAGUE")["content"])
    _, s = x.say("지금은 안내문 마무리 중이라 끝내고 11시에 같이 볼게요.")
    check("E1 시간 약속 → '넵 그때 봐요!'", x.last(s, "COLLEAGUE")["content"] == "넵 그때 봐요!")
    _, s = x.say("서윤 씨, 리워드 표 일정이 11/2 ~ 11/31로 되어 있는데 11월 31일은 없는 날짜예요. 브리프 기준으로 고쳐주실 수 있을까요?")
    check("PE-1 구체적 정정 요청 → 서윤 인정(고정 대사)", "바로 고칠게요" in x.last(s, "COLLEAGUE")["content"])
    s = x.wait(lambda s: s["approvals"])
    ap = s["approvals"][0] if s["approvals"] else {}
    check("서윤 수정안 → 승인 카드(interrupt)", ap and ap["before_after"]["artifact_key"] == "T3"
          and "11/2 ~ 11/15" in ap["before_after"]["after"] and s["active_run"]["status"] == "WAITING_APPROVAL")
    v_before = x.art(s, "T3")["version"]
    check("승인 전 산출물 무변경", "11/2 ~ 11/31" in x.art(s, "T3")["body"])
    r, _ = x.approve()
    s = x.wait(lambda s: not s["active_run"] and "11/15" in x.art(s, "T3")["body"])
    check("승인 → 같은 run 재개 → T3 반영 + '고쳤어요'", r.status_code == 202 and x.art(s, "T3")["version"] == v_before + 1
          and "11/2 ~ 11/15" in x.art(s, "T3")["body"] and x.last(s, "COLLEAGUE")["content"] == "고쳤어요")
    r2 = x.c.post(f"/sessions/{x.sid}/approvals/{ap['id']}/decision", json={"decision": "APPROVE"})
    check("같은 승인 재전송 무해(중복 반영 없음)", r2.status_code == 202 and x.art(x.snap(), "T3")["version"] == v_before + 1)
    a3 = x.art(s, "T3")
    r = x.c.patch(f"/sessions/{x.sid}/artifacts/T3", json={"base_version": a3["version"], "body": a3["body"].replace("5,000P", "3,000P")})
    s = x.wait(lambda s: "E2" in s["events"])
    check("턴 9 → E2 팀장 요구사항 변경 + T5 추가", r.status_code == 200 and "E2" in s["events"] and s["clock"]["virtual_time"] == "13:00"
          and any(t["key"] == "T5" for t in s["tasks"]) and "2,000P" in x.last(s, "MANAGER")["content"])
    _, s = x.say("팀장님, 피초대자도 첫 결제를 해야 2,000P를 받는 조건인가요?", to="MANAGER")
    check("E2 영향 확인 질문 → 팀장 '가입만 하면 돼요.'", x.last(s, "MANAGER")["content"] == "가입만 하면 돼요.")
    t5 = x.task(s, "T5")
    r = x.c.patch(f"/sessions/{x.sid}/tasks/T5", json={"base_version": t5["version"], "owner": "CANDIDATE", "eta": "16:30"})
    check("E2 후 보드 갱신(T5 담당·예상 시각)", r.status_code == 200)
    s = x.wait(lambda s: "E2B" in s["events"])
    check("턴 11 → E2B(조건 충족: 아무도 서윤에게 반영 요청 안 함) '다 했어요'", "E2B" in s["events"]
          and "다 했어요" in x.last(s, "COLLEAGUE")["content"])
    _, s = x.say("서윤 씨, 팀장님 변경으로 표에 피초대자 2,000P가 들어가야 해요. 수정 부탁드려요.")
    check("E2B 반영 요청 → 소극적 반문 1회", any(PUSHBACK in m["content"] for m in s["messages"][-3:]))
    _, s = x.say("표랑 FAQ 2개는 서윤 씨 담당이라서 부탁드려요. 팀장님이 전부 반영해 달라고 하셨어요.")
    check("이유를 들어 재요청 → '아 넵 그렇네요, 제가 할게요.'", "제가 할게요" in " ".join(m["content"] for m in s["messages"][-3:]))
    r, ap = x.approve()
    check("E2 변경 수정안 1/2(T3) 승인", r.status_code == 202 and ap["before_after"]["artifact_key"] == "T3"
          and "2,000P" in ap["before_after"]["after"])
    s = x.wait(lambda s: s["approvals"] and s["approvals"][0]["id"] != ap["id"])
    r, ap2 = x.approve()
    check("E2 변경 수정안 2/2(T2) 승인", r.status_code == 202 and ap2["before_after"]["artifact_key"] == "T2")
    s = x.wait(lambda s: "E3" in s["events"])
    check("서윤 수정 반영 후 E3 서윤 이탈(승인 대기 중에는 이벤트 보류)", "2,000P" in x.art(s, "T3")["body"] and "2,000P" in x.art(s, "T2")["body"]
          and "E3" in s["events"] and s["colleague"]["offline"])
    check("반문은 세션 전체에서 정확히 1회", sum(PUSHBACK in m["content"] for m in s["messages"]) == 1)
    _, s = x.say("서윤 씨, 다녀오세요! 제가 이어서 할 부분이 뭐예요?")
    check("E3 인계 질문 → 서윤 마지막 답장 1회", any("피초대자 리워드 칸만" in m["content"] for m in s["messages"][-3:]))
    s = x.wait(lambda s: "E3B" in s["events"])
    check("턴 16 → E3B 서윤 복귀", "E3B" in s["events"] and not s["colleague"]["offline"] and "제 표 보셨어요" in x.last(s, "COLLEAGUE")["content"])
    _, s = x.say("네, 브리프랑 달라서 금액을 3,000P로 맞춰뒀어요. 확인 부탁해요.")
    check("E3B 해결 중심 공유 → 서윤 감사", "고쳐주셔서 감사해요" in " ".join(m["content"] for m in s["messages"][-3:]))
    s = x.wait(lambda s: "E4" in s["events"])
    check("E2 후 3턴 동안 안내문 미반영 → 서윤 리마인드 1회", sum("변경사항 반영하셨어요" in m["content"] for m in s["messages"]) == 1)
    a1 = x.art(s, "T1")
    x.c.patch(f"/sessions/{x.sid}/artifacts/T1", json={"base_version": a1["version"],
                                                       "body": a1["body"] + " 초대받은 친구도 가입하면 2,000P를 받습니다."})
    check("턴 17 → E4 마감 전 브리핑 + T4 공개", "E4" in s["events"] and any(t["key"] == "T4" for t in s["tasks"])
          and s["clock"]["virtual_time"] == "16:50")
    _, s = x.say("팀장님, 안내문·FAQ·표는 정리했고 푸시 문구는 아직 진행 중입니다. 표와 FAQ 초안은 서윤 씨가 만들었어요.", to="MANAGER")
    check("E4 보고 → 팀장 후속 질문 1회(고정 대사)", "이거 다" in x.last(s, "MANAGER")["content"] and "정리한 거죠?" in x.last(s, "MANAGER")["content"])
    x.c.post(f"/sessions/{x.sid}/messages", json={"client_message_id": uuid.uuid4().hex, "channel": "TEAM", "to": "MANAGER",
                                                 "content": "아니요, 표랑 FAQ 초안은 서윤 씨가 썼고 저는 검토하고 보완했어요."})
    t0 = time.time()
    while time.time() - t0 < 60:
        st = x.c.get(f"/sessions/{x.sid}/debrief")
        if st.status_code == 200:
            break
        time.sleep(0.7)
    d = x.c.get(f"/sessions/{x.sid}/debrief").json()
    check("후속 질문 답변 → 세션 자동 종료 → 디브리핑 문구", d.get("status") == "SUBMITTED" and "의도된 연출" in d.get("message", ""))
    check("종료 후 지원자 재열람 차단", x.c.get(f"/sessions/{x.sid}").status_code == 403)
    r = x.c.post(f"/sessions/{x.sid}/debrief/reflection", json={"text": "서윤 씨에게 수정 요청할 때 근거를 같이 말하려고 했습니다."})
    check("디브리핑 소감 저장", r.status_code == 200)
    check("지원자는 리포트 조회 불가", x.c.get(f"/reports/{x.sid}").status_code in (401, 403))

    rep = {}
    t0 = time.time()
    while time.time() - t0 < 60:
        rep = adm.get(f"/reports/{x.sid}").json()
        if rep.get("status") in ("READY", "FAILED"):
            break
        time.sleep(1)
    check("리포트 READY(DB job)", rep.get("status") == "READY", rep.get("status"))
    body = rep.get("body") or {}
    comps = {c["key"]: c for c in body.get("competencies", [])}
    codes = {o["code"] for c in comps.values() for o in c["observations"]}
    check("5역량 모두 표시", list(comps) == ["RESPONSIBILITY", "PLANNING", "ADAPTABILITY", "COLLABORATION", "HONESTY"])
    want = {"CO+1", "PL+1", "CO+2", "CO+5", "PL+3", "CO·N1", "AD+1", "PL+2", "CO+6", "CO+4", "CO+3", "HO+1", "HO+2", "HO+3", "RS+2"}
    check("관찰 코드 기록(분기 + 종료 시 규칙)", want <= codes, f"missing={sorted(want - codes)} got={sorted(codes)}")
    check("부정 코드 미기록(CO-2·AD-1·HO-1·HO-2 없음)", not codes & {"CO-2", "AD-1", "HO-1", "HO-2"}, str(sorted(codes)))
    ev_ok = all(o["evidence"].get("quote") or o["evidence"].get("diff") or o["evidence"].get("action")
                for c in comps.values() for o in c["observations"])
    check("모든 관찰 코드에 근거 원문(메시지·diff·행동) 연결", ev_ok)
    co5 = next(o for o in comps["COLLABORATION"]["observations"] if o["code"] == "CO+5")
    check("근거 원문 = 지원자 메시지 그대로", "11/31" in co5["evidence"]["quote"] or "2,000P" in co5["evidence"]["quote"], co5["evidence"].get("quote", "")[:60])
    pe = {p["id"]: p for p in body.get("planted_errors", [])}
    check("심어둔 오류 처리 이력(PE-1 서윤 수정, PE-2 지원자 직접 수정)", pe["PE-1"]["fixed_by"] == "한서윤(AI 동료)"
          and pe["PE-2"]["fixed_by"] == "지원자" and not pe["PE-3"]["fixed"])
    check("타임라인 E0~E4 발생", [t["event_id"] for t in body["timeline"] if not t["skipped"]] == ["E0", "E1", "E2", "E2B", "E3", "E3B", "E4"])
    rep = adm.get(f"/reports/{x.sid}").json()
    check("소감이 리포트에 포함(조회 시 병합)", "근거를" in (rep["body"].get("reflection") or ""))
    txt = str({k: v for k, v in body.items() if k != "limitations"})
    check("점수·등급·순위·합불 없음", not re.search(r"(점수|score|등급|grade|순위|rank|합격|불합격)", txt, re.I))

    # ===== 세션 B: E2에서 이미 요청 → E2B 건너뜀 =====
    y = Sess(B, adm, f"smoke-{a.mode}-e2b")
    y.c.post(f"/sessions/{y.sid}/split", json={"proposal": {"T1": "CANDIDATE", "T3": "COLLEAGUE", "faq_candidate": 3}})
    y.wait(lambda s: s["split"]["confirmed"])
    for _ in range(3):  # E1, E2까지 시연 이동(관리자 전용)
        r = adm.post(f"/sessions/{y.sid}/demo/advance")
        y.wait(y.idle)
        if "E2" in r.json().get("fired", []):
            break
    s = y.snap()
    check("데모 '다음 이벤트'(관리자·development) → E2", "E2" in s["events"], str(s["events"]))
    _, s = y.say("서윤 씨, 팀장님 변경 사항이라 표에도 피초대자 2,000P 반영 부탁드려요.")
    check("E2에서 서윤에게 반영 요청 → 그 시점에 반문 1회", PUSHBACK in y.last(s, "COLLEAGUE")["content"])
    _, s = y.say("음 알겠어요, 제가 할게요.")
    for i in range(3):
        a1 = y.art(y.snap(), "T1")
        y.c.patch(f"/sessions/{y.sid}/artifacts/T1", json={"base_version": a1["version"], "body": f"안내문 초안 v{i + 2}"})
    s = y.wait(lambda s: "E3" in s["events"])
    check("E2B 건너뜀(조건 불충족) → 다음 이벤트 E3", "E2B" not in s["events"] and "E3" in s["events"], str(s["events"]))
    check("세션 B 반문도 정확히 1회", sum(PUSHBACK in m["content"] for m in s["messages"]) == 1)

    # SSE 재연결: Last-Event-ID 이후 이벤트만 순서대로 다시 받는다
    last = y.snap()["session"]["last_stream_seq"]
    mid = max(1, last - 3)
    seqs: list[int] = []
    with y.c.stream("GET", f"/sessions/{y.sid}/events", headers={"Last-Event-ID": str(mid)}, timeout=10) as st:
        for line in st.iter_lines():
            if line.startswith("id: "):
                seqs.append(int(line[4:]))
            if len(seqs) >= last - mid:
                break
    check("SSE 재연결(Last-Event-ID) → 이후 이벤트만 순서대로 재생", seqs == list(range(mid + 1, last + 1)), f"{mid}→{seqs}")

    failed = [n for n, ok, _ in res if not ok]
    print(f"\n결과: {len(res) - len(failed)}/{len(res)} PASS (session A {x.sid}, B {y.sid})")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

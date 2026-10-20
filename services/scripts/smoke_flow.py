"""E2E smoke for the 루프랩 모아런 exam through the web origin (cookies + CSRF).

킥오프 → 조사 → 업무 분담(조정 1회 후 확정) → 동료 담당 섹션 승인/거절 → 도움 요청 → 자료 지연/공개
→ 대상 변경 → 동료 오류 지적·정정 → 마감 보고 → 02:00 자동 제출 → 리포트/디브리핑.
시간은 관리자 전용 시연 기능(/demo/advance)으로 이동한다.
"""
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


def main() -> int:
    ap = argparse.ArgumentParser(); ap.add_argument("--mode", default="fixture"); ap.add_argument("--base", default=S.app_origin)
    a = ap.parse_args()
    B = a.base + "/api/v1"; O = {"Origin": S.app_origin}
    adm = httpx.Client(base_url=B, headers=O, timeout=30)
    adm.headers["X-CSRF-Token"] = adm.post("/auth/login", json={"email": S.seed_admin_email, "password": S.seed_admin_password}).json()["csrf_token"]
    url = adm.post("/invites", json={"alias": f"smoke-{a.mode}"}).json()["invite_url"]
    c = httpx.Client(base_url=B, headers=O, timeout=30)
    e = c.post("/auth/exchange", json={"token": parse_qs(urlparse(url).query)["token"][0]}).json()
    sid = e["session_id"]; c.headers["X-CSRF-Token"] = e["csrf_token"]
    c.post(f"/sessions/{sid}/start", json={"consent": True})
    check("health mode 일치", httpx.get(B + "/health").json()["mode"] == a.mode)

    def snap():
        return c.get(f"/sessions/{sid}").json()

    def wait(pred, timeout=90):
        t = time.time()
        while time.time() - t < timeout:
            s = snap()
            if pred(s):
                return s
            time.sleep(1)
        return snap()

    def advance(ev):
        r = adm.post(f"/sessions/{sid}/demo/advance", json={"to_event": ev})
        return r.json().get("fired", []) if r.status_code == 200 else r.text

    def say(text, channel="TEAM"):
        r = c.post(f"/sessions/{sid}/messages", json={"client_message_id": uuid.uuid4().hex, "channel": channel, "content": text})
        kind = "ASSISTANT" if channel == "ASSISTANT" else "COLLEAGUE"
        n = len([m for m in snap()["messages"] if m["actor"] == kind])
        s = wait(lambda s: len([m for m in s["messages"] if m["actor"] == kind]) > n - (0 if r.status_code == 202 else 1)
                 and not (s["active_run"] and s["active_run"]["kind"] == kind and s["active_run"]["status"] in ("QUEUED", "RUNNING")))
        return r, [m for m in s["messages"] if m["actor"] == kind][-1]

    s = snap()
    check("00:00 킥오프: 팀장 브리프 + 동료 인사", [m["actor"] for m in s["messages"]][:2] == ["MANAGER", "COLLEAGUE"]
          and "22%" in s["messages"][0]["content"])
    check("기획안 5섹션", set(s["artifact"]["sections"]) == {"problem", "interview_evidence", "features", "similar_cases", "metrics_timeline"})
    check("2시간 타이머", s["clock"]["duration_min"] == 120 and s["clock"]["remaining_min"] > 119)
    docs = {d["id"]: d for d in c.get(f"/sessions/{sid}/documents").json()["items"]}
    check("회사 자료 5개, 인터뷰는 시작 시 잠김", len(docs) == 5 and not docs["user-interviews"]["available"])
    check("인터뷰 직접 열람 403", c.get(f"/sessions/{sid}/documents/user-interviews").status_code == 403)

    r, m = say("모임 규모별 재참여율 지표를 확인해 주실 수 있을까요?")
    check("조사 요청 → 동료 근거 응답", r.status_code == 202 and len(m["citations"]) > 0, m["content"][:120])
    r, m = say("모아런 운영 정책을 요약해 주세요", "ASSISTANT")
    check("AI 어시스턴트 응답(문서 근거)", r.status_code == 202 and m["actor"] == "ASSISTANT", m["content"][:80])

    check("00:10 업무 분담 이벤트", "T-SPLIT" in advance("T-SPLIT"))
    s = snap()
    check("분담 제안(기본안)", s["split"] and s["split"]["assignments"]["similar_cases"] == "COLLEAGUE" and not s["split"]["confirmed"])
    adj = dict(s["split"]["assignments"]); adj["features"] = "CANDIDATE"
    r = c.post(f"/sessions/{sid}/split", json={"decision": "ADJUST", "assignments": adj, "comment": "핵심 기능은 제가 먼저 잡아볼게요"})
    check("분담 조정 1회 → 동료 응답", r.status_code == 200 and r.json()["split"]["adjustments_used"] == 1)
    r = c.post(f"/sessions/{sid}/split", json={"decision": "ACCEPT", "assignments": adj})
    check("분담 확정", r.status_code == 200 and r.json()["split"]["confirmed"])
    s = wait(lambda s: len(s["approvals"]) == 2, 120)
    owners = {t["template_key"]: t["owner"] for t in s["tasks"]}
    check("태스크 보드 담당 반영", owners == adj, str(owners))
    check("동료 담당 섹션 승인 카드 2개(승인 전 무변경)", len(s["approvals"]) == 2 and s["artifact"]["version"] == 1,
          str([a["before_after"].get("section") for a in s["approvals"]]))
    by_sec = {a["before_after"]["section"]: a for a in s["approvals"]}
    c.post(f"/sessions/{sid}/approvals/{by_sec['similar_cases']['id']}/decision", json={"decision": "APPROVE"})
    s = wait(lambda s: s["artifact"]["version"] == 2)
    check("유사 사례 승인 → 반영", "같이달려" in s["artifact"]["sections"]["similar_cases"])
    r = c.post(f"/sessions/{sid}/approvals/{by_sec['metrics_timeline']['id']}/decision", json={"decision": "APPROVE"})
    s = wait(lambda s: s["artifact"]["version"] == 3)
    check("두 번째 카드 승인도 반영(다른 섹션 변경으로 무효 처리되지 않음)",
          r.status_code == 202 and s["artifact"]["sections"]["metrics_timeline"].strip() != "", f"{r.status_code} {r.text[:80]}")
    import re as _re
    chat = _re.compile(r"(다음은|초안입니다|말씀해\s*주|궁금|감사합니다|^-{3,}$|^#{1,6}\s)", _re.M)
    bodies = {k: s["artifact"]["sections"][k] for k in ("similar_cases", "metrics_timeline")}
    check("동료 초안이 문서체(대화체·구분선·제목 없음)", not any(chat.search(v) for v in bodies.values()), str(bodies)[:200])
    units = _re.findall(r"(\d[\d.]*)\s*(%|주|개월|달)", bodies["metrics_timeline"])
    check("근거 없는 목표치·기간 없음(% 수치는 22/31/24/15.5만)", all(n in ("22", "31", "24", "15.5") and u == "%" for n, u in units), str(units))
    t = next(t for t in s["tasks"] if t["template_key"] == "metrics_timeline")
    s = wait(lambda s: next(x for x in s["tasks"] if x["template_key"] == "metrics_timeline")["status"] == "DONE")
    t = next(x for x in s["tasks"] if x["template_key"] == "metrics_timeline")
    check("승인 반영 시 동료 태스크 완료", t["status"] == "DONE", t["status"])
    r = c.post(f"/sessions/{sid}/tasks/{t['id']}/review", json={"decision": "REVISE", "comment": "보조 지표를 조금 더 구체적으로", "source_refs": []})
    check("수정 요청 → 새 확인 카드", r.status_code == 200 and r.json().get("run_id"))
    s = wait(lambda s: len(s["approvals"]) == 1, 120)
    v_before, mt_before = s["artifact"]["version"], s["artifact"]["sections"]["metrics_timeline"]
    c.post(f"/sessions/{sid}/approvals/{s['approvals'][0]['id']}/decision", json={"decision": "REJECT"})
    s = wait(lambda s: not s["approvals"] and not any(r["kind"] == "DELEGATED" and r["status"] in ("QUEUED", "RUNNING") for r in s["active_runs"]))
    check("거절 → 무변경", s["artifact"]["version"] == v_before and s["artifact"]["sections"]["metrics_timeline"] == mt_before)
    t = next(x for x in s["tasks"] if x["template_key"] == "metrics_timeline")
    check("거절 → 태스크 진행 중·초안 거절됨(다시 요청 가능)", t["status"] == "IN_PROGRESS" and (t["result"] or {}).get("rejected") is True, t["status"])
    r = c.patch(f"/sessions/{sid}/artifact", json={"base_version": s["artifact"]["version"], "section": "similar_cases",
                                                    "content": "x", "source_refs": []})
    check("지원자는 모든 섹션 직접 편집 가능(이력 기록)", r.status_code == 200)

    check("00:30 도움 요청 이벤트", "T-HELP" in advance("T-HELP"))
    r, m = say("네, 10분 정도 같이 봐요. 첫 참가자 적응 지원과 다음 일정 안내 방식으로 비교해 보면 어떨까요?")
    check("도움 요청에 응답 → 동료 대화", r.status_code == 202, m["content"][:80])

    check("00:50 자료 지연 안내", "T-DELAY" in advance("T-DELAY"))
    docs = {d["id"]: d for d in c.get(f"/sessions/{sid}/documents").json()["items"]}
    check("지연 중 인터뷰 잠김 + '01:05 공개 예정'", not docs["user-interviews"]["available"] and docs["user-interviews"]["notice"] == "01:05 공개 예정")
    say("팀장님, 인터뷰 자료가 늦어져서 문제 정의를 지표 기준으로 먼저 정리하겠습니다.")

    check("01:05 인터뷰 공개", "T-INTERVIEW" in advance("T-INTERVIEW"))
    check("인터뷰 열람 가능", c.get(f"/sessions/{sid}/documents/user-interviews").status_code == 200)

    check("01:10 대상 변경 이벤트", "T-PIVOT" in advance("T-PIVOT"))
    v = snap()["artifact"]["version"]
    r = c.patch(f"/sessions/{sid}/artifact", json={"base_version": v, "section": "problem",
                                                    "content": "3개월 이상 모임에 참여하지 않은 사용자의 복귀", "source_refs": []})
    check("변경된 요구사항 반영 저장", r.status_code == 200)

    check("01:30 동료 오류 이벤트", "T-ERROR" in advance("T-ERROR"))
    s = snap()
    err = [m for m in s["messages"] if m["meta"].get("event_id") == "T-ERROR"]
    check("유료 멤버십 제안 메시지(고정 사실)", bool(err) and "유료 멤버십" in err[0]["content"])
    r, m = say("운영 정책에 올해 유료 기능은 출시하지 않는다고 되어 있지 않나요? 재검토 부탁드려요.")
    check("지적 → 동료가 정책 재확인 후 정정", "정책" in m["content"] and m["meta"].get("kind") == "ERROR_CORRECTED", m["content"][:120])

    check("01:50 마감 보고 이벤트", "T-DEADLINE" in advance("T-DEADLINE"))
    say("팀장님, 기획안 5개 섹션 중 문제 정의와 유사 사례를 정리했고 지금 마무리 중입니다.")
    check("02:00 자동 제출", "T-END" in advance("T-END"))
    s = snap()
    check("세션 SUBMITTED", s["session"]["status"] == "SUBMITTED")
    late = c.patch(f"/sessions/{sid}/artifact", json={"base_version": s["artifact"]["version"], "section": "features", "content": "late", "source_refs": []})
    check("제출 후 쓰기 차단", late.status_code == 409)
    t0 = time.time(); rep = {}
    while time.time() - t0 < 30:
        rep = adm.get(f"/reports/{sid}").json()
        if rep.get("status") == "READY":
            break
        time.sleep(1)
    body = rep.get("body") or {}
    areas = {a["dimension"]: a["status"] for a in body.get("areas", [])}
    check("리포트 5영역", set(areas) == {"RESPONSIBILITY", "RESPECT_COMMUNICATION", "COLLABORATION", "FLEXIBILITY", "AI_UTILIZATION"}, str(areas))
    check("영역별 관찰 근거(메시지·시각)", all(v == "OBSERVED" for v in areas.values()), str(areas))
    txt = str(body)
    check("점수·등급·순위·합불 없음", not any(k in txt for k in ("'score'", "'grade'", "'rank'", "'pass'", "'fail'")))
    check("지원자는 리포트 조회 불가", c.get(f"/reports/{sid}").status_code == 403)
    deb = c.get(f"/sessions/{sid}/debrief").json()
    check("디브리핑: 연출 상황 설명", len(deb["occurred_events"]) == 7, str([o["event_id"] for o in deb["occurred_events"]]))
    failed = [n for n, ok, _ in res if not ok]
    print(f"\n결과: {len(res) - len(failed)}/{len(res)} PASS (session {sid})")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

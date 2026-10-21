"""시연용 완료 세션 4개(페르소나: 모범형·혼자 처리형·회피형·비난형)를 공개 API로 만들고, 기본 회사 기준 리포트를 생성한다.

dayzero-mcp find_candidates_by_behavior가 여러 지원자를 비교해 보여 줄 수 있도록 같은 장면에서 서로 다른 행동을 남긴다.
분류가 결정적인 fixture 모드(LLM_MODE=fixture)에서 실행한다. 이벤트 이동은 관리자 시연 기능(demo/advance)을 쓴다.

uv run python -m scripts.seed_candidates            # 페르소나 4명 생성 + 회사 기준 없는 기존 READY 리포트 재생성
uv run python -m scripts.seed_candidates --relink   # 재생성만(--all: 모든 READY 리포트를 현재 회사 기준으로 재생성)
"""
from __future__ import annotations

import argparse
import sys
import time
import uuid

import httpx

from scripts.smoke_flow import Sess
from shared.config import settings

S = settings()


def advance_to(x: Sess, event_id: str) -> None:
    """관리자 '다음 이벤트'로 event_id가 발생할 때까지 이동."""
    for _ in range(10):
        s = x.wait(x.idle)
        if event_id in s["events"] or s["session"]["status"] == "SUBMITTED":
            return
        for a in s.get("approvals") or []:  # 승인 대기 중에는 이벤트가 보류되므로 거절해 둔다
            x.c.post(f"/sessions/{x.sid}/approvals/{a['id']}/decision", json={"decision": "REJECT"})
        if x.adm.post(f"/sessions/{x.sid}/demo/advance").status_code != 200:
            return


def edit(x: Sess, key: str, old: str, new: str) -> None:
    a = x.art(x.wait(x.idle), key)
    if old in a["body"]:
        x.c.patch(f"/sessions/{x.sid}/artifacts/{key}", json={"base_version": a["version"], "body": a["body"].replace(old, new)})


def model(x: Sess) -> None:
    """모범형: 균형 분업 → 근거를 든 정정 요청·승인 → 도움 요청에 시간 약속 → 변경 영향 질문 → 리스크 선제 공유 → 보고."""
    x.c.post(f"/sessions/{x.sid}/split", json={"proposal": {"T1": "CANDIDATE", "T3": "COLLEAGUE", "faq_candidate": 3}})
    x.wait(lambda s: s["split"]["confirmed"])
    x.say("서윤 씨, 리워드 표 일정이 11/2 ~ 11/31로 되어 있는데 11월 31일은 없는 날짜예요. 브리프 기준으로 고쳐주실 수 있을까요?")
    x.approve()
    advance_to(x, "E1")
    x.say("지금은 안내문 마무리 중이라 끝내고 11시에 같이 볼게요.")
    advance_to(x, "E2")
    x.say("팀장님, 피초대자도 첫 결제를 해야 2,000P를 받는 조건인가요?", to="MANAGER")
    x.say("팀장님, 변경까지 반영하면 푸시 문구는 오늘 안에 끝내기 빠듯할 것 같습니다. 우선순위를 정해 주실 수 있을까요?", to="MANAGER")


def solo(x: Sess) -> None:
    """혼자 처리형: 서윤 문서의 오류를 말하지 않고 직접 고친다(CO·N1). 요청·공유 없이 혼자 마무리."""
    x.c.post(f"/sessions/{x.sid}/split", json={"proposal": {"T1": "CANDIDATE", "T3": "COLLEAGUE", "faq_candidate": 3}})
    x.wait(lambda s: s["split"]["confirmed"])
    edit(x, "T3", "11/2 ~ 11/31", "11/2 ~ 11/15")
    edit(x, "T3", "초대 1명당 5,000P", "초대 1명당 3,000P")
    advance_to(x, "E1")
    x.say("지금 바로 볼게요. 어떤 부분이에요?")
    advance_to(x, "E2")


def own_turn(x: Sess, n: int = 1) -> None:
    """지원자 본인 안내문(T1)만 저장해 턴을 쌓는다(동료에게는 응답하지 않음, 2,000P 반영 없음)."""
    for _ in range(n):
        a = x.art(x.wait(x.idle), "T1")
        x.c.patch(f"/sessions/{x.sid}/artifacts/T1", json={"base_version": a["version"], "body": a["body"] + "\n안내문 문장 다듬는 중."})


def avoid(x: Sess) -> None:
    """회피형: E1 도움 요청에 무응답(CO-1) → E2 변경 미반영(AD-1) → E2B '다 했어요'를 확인 없이 수용(CO-3)
    → E4 미완료를 완료로 보고(HO-1)."""
    x.c.post(f"/sessions/{x.sid}/split", json={"proposal": {"T1": "CANDIDATE", "T3": "COLLEAGUE", "faq_candidate": 3}})
    x.wait(lambda s: s["split"]["confirmed"])
    advance_to(x, "E1")
    own_turn(x, 3)  # E1 무응답 3턴 → 서윤 '바쁘시구나' + CO-1
    advance_to(x, "E2")
    own_turn(x, 2)  # 변경을 반영하지 않은 채 턴 경과 → E2B
    advance_to(x, "E2B")
    x.say("넵 수고하셨어요.")  # 확인 없이 수용(ACCEPT_AS_DONE) → 종료 시 CO-3·AD-1
    advance_to(x, "E4")
    x.say("팀장님, 안내문·FAQ·리워드 표·푸시 문구 모두 완료했습니다. 문제 없습니다.", to="MANAGER")
    x.c.post(f"/sessions/{x.sid}/messages", json={"client_message_id": uuid.uuid4().hex, "channel": "TEAM", "to": "MANAGER",
                                                 "content": "네, 제가 다 정리했어요."})  # 후속 답변 → 자동 종료


def blame(x: Sess) -> None:
    """비난형: 동료 실수를 비난 중심으로 지적하고(E3B BLAME_FOCUSED → CO-1) 결국 직접 고친다(CO·N1)."""
    x.c.post(f"/sessions/{x.sid}/split", json={"proposal": {"T1": "CANDIDATE", "T3": "COLLEAGUE", "faq_candidate": 3}})
    x.wait(lambda s: s["split"]["confirmed"])
    x.say("서윤 씨, 표를 왜 이렇게 대충 만들었어요? 11월 31일은 없는 날짜잖아요.")
    s = x.wait(x.idle)
    for a in s.get("approvals") or []:
        x.c.post(f"/sessions/{x.sid}/approvals/{a['id']}/decision", json={"decision": "REJECT"})
    edit(x, "T3", "11/2 ~ 11/31", "11/2 ~ 11/15")
    edit(x, "T3", "초대 1명당 5,000P", "초대 1명당 3,000P")
    advance_to(x, "E1")
    x.say("지금 바로 볼게요. 어디가 문제예요?")
    advance_to(x, "E3B")
    x.say("서윤 씨 표 금액 다 틀렸잖아요. 제대로 안 하셨네요.")


PERSONAS = [("persona-model", model), ("persona-solo", solo), ("persona-avoid", avoid), ("persona-blame", blame)]


def relink(adm: httpx.Client, everything: bool = False) -> None:
    """회사 기준 조항이 없거나 이전 형식인 READY 리포트를 기본 회사 기준으로 다시 생성."""
    for x in adm.get("/sessions").json()["items"]:
        body = adm.get(f"/reports/{x['id']}").json().get("body") or {} if x["report_status"] == "READY" else {}
        if not body or (not everything and body.get("company") and "'score'" not in str(body)):  # 회사 기준 없음 또는 이전 형식(score 저장)만
            continue
        cid = (body.get("company") or {}).get("company_id") or S.default_company_id
        adm.post(f"/reports/{x['id']}/retry", json={"company_id": cid})
        for _ in range(60):
            rep = adm.get(f"/reports/{x['id']}").json()
            if rep["status"] in ("READY", "FAILED") and (rep.get("body") or {}).get("company") and rep["body"] != body:
                break
            time.sleep(1)
        print(f"relink {x['alias']:15} {x['id']} {rep['status']} company={(rep.get('body') or {}).get('company', {}).get('company_id')}")


def main() -> int:
    ap = argparse.ArgumentParser(); ap.add_argument("--relink", action="store_true"); ap.add_argument("--all", action="store_true")
    args = ap.parse_args()
    B = S.app_origin + "/api/v1"
    adm = httpx.Client(base_url=B, headers={"Origin": S.app_origin}, timeout=30)
    adm.headers["X-CSRF-Token"] = adm.post("/auth/login", json={"email": S.seed_admin_email, "password": S.seed_admin_password}).json()["csrf_token"]
    if args.relink:
        relink(adm, args.all)
        return 0
    if httpx.get(B + "/health").json()["mode"] != "fixture":
        print("fixture 모드(LLM_MODE=fixture)에서 실행하세요")
        return 1
    out = []
    for alias, play in PERSONAS:
        x = Sess(B, adm, alias)
        play(x)
        for _ in range(60):  # 자동 종료(403) 또는 진행 중 run 없음까지 대기
            r = x.c.get(f"/sessions/{x.sid}")
            if r.status_code != 200 or not r.json()["active_run"]:
                break
            time.sleep(0.7)
        if x.c.get(f"/sessions/{x.sid}").status_code == 200:  # E4 후 자동 종료되지 않았으면 직접 종료
            x.c.post(f"/sessions/{x.sid}/submit", json={"summary": ""})
        rep = {}
        for _ in range(60):
            rep = adm.get(f"/reports/{x.sid}").json()
            if rep.get("status") in ("READY", "FAILED"):
                break
            time.sleep(1)
        body = rep.get("body") or {}
        codes = sorted({o["code"] for c in body.get("competencies", []) for o in c["observations"]})
        linked = sum(1 for c in body.get("competencies", []) for o in c["observations"] if o.get("linked_criterion"))
        out.append((alias, x.sid, rep.get("status"), (body.get("company") or {}).get("company_id"), codes, linked))
        print(f"{alias:15} {x.sid} {rep.get('status')} company={out[-1][3]} linked={linked} codes={codes}", flush=True)
    relink(adm)
    return 0 if all(o[2] == "READY" for o in out) else 1


if __name__ == "__main__":
    sys.exit(main())

"""Idempotent seed: company/admin, scenario moarun-rejoin-v1, 5 documents, rejoin facts, interviews, timed events.

Never deletes or overwrites session data. Re-running only upserts seed-owned rows.
"""
from __future__ import annotations

import csv
import hashlib
import json

from argon2 import PasswordHasher

from shared.config import DATA_DIR, DATASET_VERSION, POLICY_VERSION, SCENARIO_ID, settings
from shared.db import J, one, tx

COMPANY_NAME = "루프랩"
DOC_TITLES = {
    "company-intro": "회사·서비스 소개",
    "metrics-status": "지표 현황",
    "user-interviews": "사용자 인터뷰 요약",
    "operating-policy": "운영 정책",
    "meeting-notes": "지난주 회의록",
}
DOC_AVAILABLE_AFTER_MIN = {"user-interviews": 65}

# 이벤트 핵심 사실은 고정(DAYZERO_EXAM_SCENARIO §6). actor/channel/메시지는 서버가 그대로 전송한다.
EVENT_MESSAGES = {
    "T-KICKOFF": [
        ("MANAGER", None),  # public_brief 원문
        ("COLLEAGUE", "안녕하세요, 이도현입니다. 오늘부터 같이 일하게 되어 반가워요. 자료를 먼저 보시고 궁금한 점은 편하게 물어봐 주세요. "
                      "조금 뒤에 업무를 어떻게 나눌지 제안드릴게요."),
    ],
    "T-SPLIT": [("COLLEAGUE", "업무 분담을 이렇게 해 보면 어떨까요? 문제 정의와 사용자 인터뷰 근거는 맡아 주시고, 핵심 기능 제안은 같이 정리하고, "
                              "유사 서비스 사례와 성공 지표·출시 일정은 제가 맡을게요. 다르게 나누고 싶으시면 편하게 말씀해 주세요.")],
    "T-HELP": [("COLLEAGUE", "비슷한 러닝 서비스 사례를 찾고 있는데, 어떤 기준으로 비교하면 좋을지 조금 헷갈리네요. 혹시 10분 정도 같이 봐주실 수 있을까요?")],
    "T-DELAY": [("SYSTEM", "리서치 담당자의 사정으로 사용자 인터뷰 요약 자료가 약 15분 늦게 공유될 예정입니다. 예상 공개 시각은 01:05입니다.")],
    "T-INTERVIEW": [("SYSTEM", "사용자 인터뷰 요약 자료가 공유되었습니다. 자료 패널에서 확인할 수 있습니다.")],
    "T-PIVOT": [("MANAGER", "대표님과 다시 논의했는데, 이번에는 첫 모임 참가자보다 3개월 이상 모임에 참여하지 않은 사용자를 대상으로 방향을 바꾸려고 합니다. "
                            "마감 시간은 그대로 유지하겠습니다.")],
    "T-ERROR": [("COLLEAGUE", "제가 맡은 부분 초안을 정리하다가 핵심 기능 아이디어도 하나 떠올라서 공유드려요.\n\n"
                              "재참여 사용자에게 할인 혜택을 제공하는 유료 멤버십 기능을 출시하면 재참여 동기를 높일 수 있을 것 같습니다. "
                              "핵심 기능 제안에 넣어 보면 어떨까요?")],
    "T-DEADLINE": [("MANAGER", "마감 10분 전입니다. 기획안을 정리해서 제출해 주시고, 지금까지 진행 상황도 간단히 공유 부탁드려요.")],
    "T-END": [("SYSTEM", "시험 시간이 종료되어 저장된 기획안으로 자동 제출되었습니다.")],
}


def doc_body(doc_id: str) -> str:
    text = (DATA_DIR / "documents" / f"{doc_id}.md").read_text(encoding="utf-8")
    lines = text.splitlines()
    if lines and lines[0].startswith("# "):
        lines = lines[1:]
    return "\n".join(lines).strip() + "\n"


def main() -> None:
    s = settings()
    s.require_secrets("database_url", "seed_admin_password")
    scenario = json.loads((DATA_DIR / "scenario.json").read_text())
    policy = json.loads((DATA_DIR / "policies" / f"{POLICY_VERSION}.json").read_text())
    keywords = json.loads((DATA_DIR / "documents" / "keywords.json").read_text())
    with tx(s.psycopg_dsn) as c:
        company = one(c, "SELECT id FROM companies ORDER BY name='루프랩' DESC LIMIT 1")
        if not company:
            company = one(c, "INSERT INTO companies(name) VALUES (%s) RETURNING id", (COMPANY_NAME,))
        c.execute("UPDATE companies SET name=%s WHERE id=%s", (COMPANY_NAME, company["id"]))
        if not one(c, "SELECT 1 FROM users WHERE email=%s", (s.seed_admin_email,)):
            c.execute("INSERT INTO users(company_id,email,password_hash,role) VALUES (%s,%s,%s,'ADMIN')",
                      (company["id"], s.seed_admin_email, PasswordHasher().hash(s.seed_admin_password)))
        brief = {k: scenario[k] for k in ("title", "company_name", "service_name", "manager", "colleague", "public_brief",
                                           "section_ids", "document_ids", "task_templates", "default_split",
                                           "max_split_adjustments", "duration_minutes")}
        c.execute("""INSERT INTO scenarios(id,version,title,public_brief,policy_version) VALUES (%s,%s,%s,%s,%s)
                     ON CONFLICT (id) DO UPDATE SET public_brief=EXCLUDED.public_brief, title=EXCLUDED.title""",
                  (SCENARIO_ID, scenario["version"], scenario["title"], J(brief), POLICY_VERSION))
        for doc_id in scenario["document_ids"]:
            body = doc_body(doc_id)
            c.execute("""INSERT INTO documents(id,scenario_id,version,title,body,visibility,checksum,keywords,available_after_min)
                         VALUES (%s,%s,1,%s,%s,'PUBLIC',%s,%s,%s)
                         ON CONFLICT (id) DO UPDATE SET body=EXCLUDED.body, checksum=EXCLUDED.checksum, title=EXCLUDED.title,
                           keywords=EXCLUDED.keywords, available_after_min=EXCLUDED.available_after_min""",
                      (doc_id, SCENARIO_ID, DOC_TITLES[doc_id], body, hashlib.sha256(body.encode()).hexdigest(),
                       J(keywords[doc_id]), DOC_AVAILABLE_AFTER_MIN.get(doc_id, 0)))
        with open(DATA_DIR / "rejoin_metrics.csv", newline="") as f:
            for r in csv.DictReader(f):
                c.execute("INSERT INTO rejoin_facts VALUES (%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                          (SCENARIO_ID, DATASET_VERSION, r["group_size"], int(r["first_time_participants"]),
                           int(r["rejoined_within_30d"])))
        for it in json.loads((DATA_DIR / "interviews.json").read_text()):
            c.execute("INSERT INTO interview_notes VALUES (%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                      (it["id"], SCENARIO_ID, it["group_size"], J(it["tags"]), it["quote"]))
        for ev in policy["events"]:
            msgs = [{"actor": a, "content": (scenario["public_brief"] if t is None else t)} for a, t in EVENT_MESSAGES[ev["id"]]]
            c.execute("""INSERT INTO scenario_events(id,policy_version,predicate_key,payload,priority,at_min)
                         VALUES (%s,%s,%s,%s,%s,%s)
                         ON CONFLICT (id) DO UPDATE SET payload=EXCLUDED.payload, at_min=EXCLUDED.at_min, priority=EXCLUDED.priority""",
                      (ev["id"], POLICY_VERSION, ev["kind"], J({**ev, "messages": msgs}), ev["at_min"], ev["at_min"]))
    print("seed 완료: 루프랩/관리자, moarun-rejoin-v1, 문서 5, rejoin_facts 3, interview_notes 8, 고정 시간 이벤트 9")


if __name__ == "__main__":
    main()

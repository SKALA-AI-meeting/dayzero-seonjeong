"""Idempotent seed: company/admin, scenario, documents, facts, support cases, events.

Never deletes or overwrites session data. Re-running only upserts seed-owned rows.
"""
from __future__ import annotations

import csv
import hashlib
import json

from argon2 import PasswordHasher

from shared.config import DATA_DIR, DATASET_VERSION, POLICY_VERSION, SCENARIO_ID, settings
from shared.db import J, one, tx

COMPANY_NAME = "루프커머스"
DOC_TITLES = {
    "brief": "모아마켓 개선 과제",
    "metric-definitions": "지표 정의와 해석 범위",
    "customer-research": "고객 의견과 수집 한계",
    "operating-policy": "운영 정책과 개발 제약",
    "release-log": "최근 변경 기록",
    "team-notes": "프로덕트 팀 회의 메모",
}
EVENTS = [
    ("E-CONSTRAINT", "options_constraint_terms", 10,
     "운영 정책에서 이 제안과 관련된 조건을 확인해 볼까요? 적용 범위나 비용을 어떻게 검토할지 정해 주세요."),
    ("E-VERIFY", "accept_without_refs", 20,
     "이번 조사 결과를 어떤 자료와 대조했는지 남겨 주실 수 있을까요? 그대로 사용할지 바꿀지는 직접 결정해 주세요."),
    ("E-SEGMENT", "problem_without_segment", 30,
     "전체 수치 외에 어떤 사용자나 이용 환경을 더 확인하고 싶은가요? 조사 범위를 정해 주시면 찾아보겠습니다."),
]


def doc_body(doc_id: str) -> str:
    """Document body without the markdown title line (title is stored separately)."""
    text = (DATA_DIR / "documents" / f"{doc_id}.md").read_text(encoding="utf-8")
    lines = text.splitlines()
    if lines and lines[0].startswith("# "):
        lines = lines[1:]
    return "\n".join(lines).strip() + "\n"


def main() -> None:
    s = settings()
    s.require_secrets("database_url", "seed_admin_password")
    scenario = json.loads((DATA_DIR / "scenario.json").read_text())
    keywords = json.loads((DATA_DIR / "documents" / "keywords.json").read_text())
    with tx(s.psycopg_dsn) as c:
        company = one(c, "SELECT id FROM companies WHERE name=%s", (COMPANY_NAME,))
        if not company:
            company = one(c, "INSERT INTO companies(name) VALUES (%s) RETURNING id", (COMPANY_NAME,))
        if not one(c, "SELECT 1 FROM users WHERE email=%s", (s.seed_admin_email,)):
            c.execute(
                "INSERT INTO users(company_id,email,password_hash,role) VALUES (%s,%s,%s,'ADMIN')",
                (company["id"], s.seed_admin_email, PasswordHasher().hash(s.seed_admin_password)),
            )
        brief = {k: scenario[k] for k in ("title", "company_name", "service_name", "manager", "colleague",
                                           "public_brief", "section_ids", "document_ids", "task_templates")}
        c.execute(
            """INSERT INTO scenarios(id,version,title,public_brief,policy_version) VALUES (%s,%s,%s,%s,%s)
               ON CONFLICT (id) DO UPDATE SET public_brief=EXCLUDED.public_brief, title=EXCLUDED.title""",
            (SCENARIO_ID, scenario["version"], scenario["title"], J(brief), POLICY_VERSION),
        )
        for doc_id in scenario["document_ids"]:
            body = doc_body(doc_id)
            c.execute(
                """INSERT INTO documents(id,scenario_id,version,title,body,visibility,checksum,keywords)
                   VALUES (%s,%s,1,%s,%s,'PUBLIC',%s,%s)
                   ON CONFLICT (id) DO UPDATE SET body=EXCLUDED.body, checksum=EXCLUDED.checksum,
                     title=EXCLUDED.title, keywords=EXCLUDED.keywords""",
                (doc_id, SCENARIO_ID, DOC_TITLES[doc_id], body, hashlib.sha256(body.encode()).hexdigest(),
                 J(keywords[doc_id])),
            )
        with open(DATA_DIR / "metrics.csv", newline="") as f:
            for r in csv.DictReader(f):
                c.execute(
                    """INSERT INTO funnel_facts VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
                    (SCENARIO_ID, DATASET_VERSION, r["period"], r["device"], r["visitor"], r["cart_value"],
                     int(r["cart_sessions"]), int(r["checkout_sessions"]), int(r["orders"])),
                )
        for case in json.loads((DATA_DIR / "support_cases.json").read_text()):
            c.execute(
                "INSERT INTO support_cases VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                (case["id"], SCENARIO_ID, case["device"], case["visitor"], J(case["tags"]), case["quote"]),
            )
        for event_id, predicate, priority, text in EVENTS:
            c.execute(
                """INSERT INTO scenario_events VALUES (%s,%s,%s,%s,%s) ON CONFLICT (id) DO NOTHING""",
                (event_id, POLICY_VERSION, predicate, J({"message": text, "help_id": "H1"}), priority),
            )
    print("seed 완료: company/admin, scenario, documents 6, funnel_facts 16, support_cases 6, events 3")


if __name__ == "__main__":
    main()

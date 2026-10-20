"""Idempotent seed: company/admin, scenario fitmoa-invite-v1(sc-a), 공유 문서 4개 + 관찰 코드북(내부).

세션 데이터는 지우거나 덮어쓰지 않는다. 다시 실행하면 seed 소유 행만 upsert한다.
"""
from __future__ import annotations

import hashlib
import json

from argon2 import PasswordHasher

from shared.config import CRITERIA_DOCUMENT_ID, DATA_DIR, PUBLIC_DOCUMENT_IDS, SCENARIO_ID, SCENARIO_KEY, settings
from shared.db import J, one, tx

COMPANY_NAME = "핏모아"


def doc_body(doc_id: str) -> tuple[str, str]:
    text = (DATA_DIR / "documents" / f"{doc_id}.md").read_text(encoding="utf-8")
    lines = text.splitlines()
    title = lines[0][2:].strip() if lines and lines[0].startswith("# ") else doc_id
    return title, "\n".join(lines[1:]).strip() + "\n"


def main() -> None:
    s = settings()
    s.require_secrets("database_url", "seed_admin_password")
    sc = json.loads((DATA_DIR / "scenario.json").read_text(encoding="utf-8"))
    assert sc["scenario_id"] == SCENARIO_KEY, f"scenario.json scenario_id={sc['scenario_id']} ≠ {SCENARIO_KEY}"
    fixes = json.loads((DATA_DIR / "colleague_fixes.json").read_text(encoding="utf-8"))["fixes"]
    with tx(s.psycopg_dsn) as c:
        company = one(c, "SELECT id FROM companies ORDER BY name=%s DESC LIMIT 1", (COMPANY_NAME,))
        if not company:
            company = one(c, "INSERT INTO companies(name) VALUES (%s) RETURNING id", (COMPANY_NAME,))
        c.execute("UPDATE companies SET name=%s WHERE id=%s", (COMPANY_NAME, company["id"]))
        if not one(c, "SELECT 1 FROM users WHERE email=%s", (s.seed_admin_email,)):
            c.execute("INSERT INTO users(company_id,email,password_hash,role) VALUES (%s,%s,%s,'ADMIN')",
                      (company["id"], s.seed_admin_email, PasswordHasher().hash(s.seed_admin_password)))
        c.execute("""INSERT INTO scenarios(id,scenario_key,version,title,definition,fixes) VALUES (%s,%s,1,%s,%s,%s)
                     ON CONFLICT (id) DO UPDATE SET definition=EXCLUDED.definition, fixes=EXCLUDED.fixes, title=EXCLUDED.title""",
                  (SCENARIO_ID, SCENARIO_KEY, sc["title"], J(sc), J(fixes)))
        for i, doc_id in enumerate(PUBLIC_DOCUMENT_IDS + [CRITERIA_DOCUMENT_ID]):
            title, body = doc_body(doc_id)
            vis = "INTERNAL" if doc_id == CRITERIA_DOCUMENT_ID else "PUBLIC"
            c.execute("""INSERT INTO documents(id,scenario_id,version,title,body,visibility,checksum,ordinal)
                         VALUES (%s,%s,1,%s,%s,%s,%s,%s)
                         ON CONFLICT (id) DO UPDATE SET body=EXCLUDED.body, checksum=EXCLUDED.checksum, title=EXCLUDED.title,
                           visibility=EXCLUDED.visibility, ordinal=EXCLUDED.ordinal""",
                      (doc_id, SCENARIO_ID, title, body, vis, hashlib.sha256(body.encode()).hexdigest(), i))
    print(f"seed 완료: {COMPANY_NAME}/관리자, {SCENARIO_ID}({SCENARIO_KEY}), 공유 문서 {len(PUBLIC_DOCUMENT_IDS)}개 + 코드북 1개, "
          f"이벤트 {len(sc['events'])}개, 심어둔 오류 {len(sc['planted_errors'])}개")


if __name__ == "__main__":
    main()

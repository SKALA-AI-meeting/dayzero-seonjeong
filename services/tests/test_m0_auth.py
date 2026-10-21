"""AT-01 / AT-11 / AT-12 일부: 실제 gateway HTTP + 쿠키/CSRF. 실행 중인 gateway가 필요하다."""
from __future__ import annotations

import uuid
from datetime import timedelta
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from shared.config import settings
from shared.db import tx

BASE = settings().gateway_internal_url + "/api/v1"
ORIGIN = {"Origin": settings().app_origin}


def _up() -> bool:
    try:
        return httpx.get(BASE + "/health", timeout=2).status_code == 200
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _up(), reason="gateway not running")


def admin_client() -> tuple[httpx.Client, str]:
    c = httpx.Client(base_url=BASE, headers=ORIGIN)
    r = c.post("/auth/login", json={"email": settings().seed_admin_email, "password": settings().seed_admin_password})
    assert r.status_code == 200, r.text
    return c, r.json()["csrf_token"]


def new_invite(alias: str = "지원자A") -> str:
    c, csrf = admin_client()
    r = c.post("/invites", json={"alias": alias}, headers={"X-CSRF-Token": csrf})
    assert r.status_code == 201, r.text
    return parse_qs(urlparse(r.json()["invite_url"]).query)["token"][0]


def candidate(token: str) -> tuple[httpx.Client, dict]:
    c = httpx.Client(base_url=BASE, headers=ORIGIN)
    r = c.post("/auth/exchange", json={"token": token})
    assert r.status_code == 200, r.text
    return c, r.json()


def test_login_rejects_bad_password():
    r = httpx.post(BASE + "/auth/login", json={"email": settings().seed_admin_email, "password": "wrong"})
    assert r.status_code == 401 and r.json()["error"]["code"] == "UNAUTHENTICATED"


def test_invite_single_use_and_start_idempotent():
    token = new_invite()
    c, body = candidate(token)
    sid, csrf = body["session_id"], body["csrf_token"]
    # 동의 전 업무 API 차단
    r = c.post(f"/sessions/{sid}/messages", json={"client_message_id": uuid.uuid4().hex, "channel": "TEAM",
                                                   "content": "안녕하세요"}, headers={"X-CSRF-Token": csrf})
    assert r.status_code == 403
    # 다른 브라우저에서 재사용 → 409
    r2 = httpx.post(BASE + "/auth/exchange", json={"token": token}, headers=ORIGIN)
    assert r2.status_code == 409 and r2.json()["error"]["code"] == "ALREADY_USED"
    # 같은 브라우저 재교환 → 같은 세션
    assert c.post("/auth/exchange", json={"token": token}).json()["session_id"] == sid
    # start 2회 → E0 스탠드업/보드 1회
    for _ in range(2):
        r = c.post(f"/sessions/{sid}/start", json={"consent": True}, headers={"X-CSRF-Token": csrf})
        assert r.status_code == 200 and r.json()["session"]["status"] == "ACTIVE"
    snap = c.get(f"/sessions/{sid}").json()
    assert [m["actor"] for m in snap["messages"]] == ["MANAGER", "COLLEAGUE"]  # E0 1회(팀장 지시 + 서윤 분업 질문)
    assert [t["key"] for t in snap["tasks"]] == ["T1", "T2", "T3"]  # T4는 E4, T5는 E2에서 추가
    assert {a["key"]: a["version"] for a in snap["artifacts"]} == {"T1": 1, "T2": 1, "T3": 1}
    assert snap["session"]["turn_count"] == 0 and snap["clock"]["elapsed_seconds"] <= 1


def test_csrf_and_origin_required():
    c, body = candidate(new_invite())
    sid = body["session_id"]
    assert c.post(f"/sessions/{sid}/start", json={"consent": True}).status_code == 403
    r = c.post(f"/sessions/{sid}/start", json={"consent": True},
               headers={"X-CSRF-Token": body["csrf_token"], "Origin": "http://evil.example"})
    assert r.status_code == 403


def test_foreign_session_404_and_admin_only():
    a, ab = candidate(new_invite("A"))
    b, bb = candidate(new_invite("B"))
    assert a.get(f"/sessions/{bb['session_id']}").status_code == 404
    assert a.get("/sessions").status_code == 403
    assert a.post("/invites", json={"alias": "x"}, headers={"X-CSRF-Token": ab["csrf_token"]}).status_code == 403
    # 임의 필드로 권한 상승 불가 (extra 필드 거절)
    r = a.post(f"/sessions/{ab['session_id']}/start", json={"consent": True, "role": "ADMIN"},
               headers={"X-CSRF-Token": ab["csrf_token"]})
    assert r.status_code == 422
    # internal API는 브라우저 쿠키로 호출 불가
    r = a.post(settings().gateway_internal_url + "/internal/v1/jobs/claim", json={"worker_id": "x", "kinds": ["AGENT"]})
    assert r.status_code in (403, 404)


def test_expired_invite_410():
    token = new_invite("만료")
    from gateway.app.auth import hash_token
    with tx(settings().psycopg_dsn) as c:
        c.execute("UPDATE invites SET expires_at=now()-%s WHERE token_hash=%s", (timedelta(hours=1), hash_token(token)))
    r = httpx.post(BASE + "/auth/exchange", json={"token": token}, headers=ORIGIN)
    assert r.status_code == 410 and r.json()["error"]["code"] == "INVITE_EXPIRED"


def test_session_list_has_no_token():
    c, csrf = admin_client()
    r = c.get("/sessions")
    assert r.status_code == 200
    assert "token" not in r.text.lower().replace("next_cursor", "")

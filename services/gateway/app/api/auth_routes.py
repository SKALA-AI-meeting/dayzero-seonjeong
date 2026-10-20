from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from shared.config import SCENARIO_ID, SCENARIO_VERSION, settings
from shared.db import all_, one, tx

from ..auth import (Principal, admin, clear_cookie, hash_token, issue_cookie, new_invite_token,
                    optional_principal, principal, verify_password)
from ..domain import now
from ..errors import ApiError

router = APIRouter()


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LoginIn(Strict):
    email: str = Field(max_length=200)
    password: str = Field(max_length=200)


class ExchangeIn(Strict):
    token: str = Field(min_length=10, max_length=200)


class InviteIn(Strict):
    alias: str = Field(min_length=1, max_length=60)


def dsn() -> str:
    return settings().psycopg_dsn


@router.post("/auth/login")
def login(body: LoginIn, response: Response):
    with tx(dsn()) as c:
        u = one(c, "SELECT * FROM users WHERE email=%s", (body.email,))
    if not u or not verify_password(u["password_hash"], body.password):
        raise ApiError(401, "UNAUTHENTICATED", "이메일 또는 비밀번호가 올바르지 않습니다")
    csrf = issue_cookie(response, sub=str(u["id"]), role="ADMIN", company_id=str(u["company_id"]), session_id=None)
    return {"user": {"id": str(u["id"]), "role": "ADMIN"}, "csrf_token": csrf}


@router.post("/auth/exchange")
def exchange(body: ExchangeIn, request: Request, response: Response):
    current = optional_principal(request)
    with tx(dsn()) as c:
        inv = one(c, "SELECT * FROM invites WHERE token_hash=%s FOR UPDATE", (hash_token(body.token),))
        if not inv:
            raise ApiError(404, "NOT_FOUND", "초대를 찾을 수 없습니다")
        if inv["consumed_at"]:
            # Same browser that already exchanged it → resume that session.
            if current and current.role == "CANDIDATE" and current.session_id == str(inv["session_id"]):
                return {"session_id": current.session_id, "csrf_token": current.csrf}
            raise ApiError(409, "ALREADY_USED", "이미 사용된 초대입니다")
        if inv["expires_at"] < now():
            raise ApiError(410, "INVITE_EXPIRED", "만료된 초대입니다")
        part = one(c, "INSERT INTO participants(company_id,alias) VALUES (%s,%s) RETURNING id",
                   (inv["company_id"], inv["alias"]))
        s = one(c, """INSERT INTO sessions(company_id,participant_id,scenario_id,scenario_version)
                      VALUES (%s,%s,%s,%s) RETURNING id""",
                (inv["company_id"], part["id"], SCENARIO_ID, SCENARIO_VERSION))
        c.execute("UPDATE participants SET session_id=%s WHERE id=%s", (s["id"], part["id"]))
        c.execute("UPDATE invites SET consumed_at=now(), session_id=%s WHERE id=%s", (s["id"], inv["id"]))
    csrf = issue_cookie(response, sub=str(part["id"]), role="CANDIDATE", company_id=str(inv["company_id"]),
                        session_id=str(s["id"]))
    return {"session_id": str(s["id"]), "csrf_token": csrf}


@router.post("/auth/logout", status_code=204)
def logout(response: Response, p: Principal = Depends(principal)):
    clear_cookie(response)
    response.status_code = 204
    return None


@router.get("/auth/me")
def me(p: Principal = Depends(principal)):
    out = {"id": p.sub, "role": p.role, "csrf_token": p.csrf}
    if p.session_id:
        out["session_id"] = p.session_id
    return out


@router.post("/invites", status_code=201)
def create_invite(body: InviteIn, p: Principal = Depends(admin)):
    raw = new_invite_token()
    expires = now() + timedelta(hours=72)
    with tx(dsn()) as c:
        inv = one(c, "INSERT INTO invites(company_id,alias,token_hash,expires_at) VALUES (%s,%s,%s,%s) RETURNING id",
                  (p.company_id, body.alias, hash_token(raw), expires))
    return {"invite_id": str(inv["id"]), "invite_url": f"{settings().app_origin}/join?token={raw}",
            "expires_at": expires.isoformat()}


@router.get("/sessions")
def list_sessions(cursor: str | None = None, p: Principal = Depends(admin)):
    with tx(dsn()) as c:
        rows = all_(c, """SELECT s.id, s.status, s.phase, s.created_at, s.submitted_at, pa.alias,
                                 r.status AS report_status
                          FROM sessions s JOIN participants pa ON pa.id=s.participant_id
                          LEFT JOIN reports r ON r.session_id=s.id
                          WHERE s.company_id=%s AND (%s::timestamptz IS NULL OR s.created_at < %s::timestamptz)
                          ORDER BY s.created_at DESC LIMIT 101""", (p.company_id, cursor, cursor))
        invites = all_(c, """SELECT id, alias, expires_at, consumed_at FROM invites WHERE company_id=%s
                             AND consumed_at IS NULL ORDER BY expires_at DESC LIMIT 20""", (p.company_id,))
    items = [{"id": str(r["id"]), "alias": r["alias"], "status": r["status"], "phase": r["phase"],
              "report_status": r["report_status"], "created_at": r["created_at"].isoformat(),
              "submitted_at": r["submitted_at"].isoformat() if r["submitted_at"] else None} for r in rows[:100]]
    return {"items": items, "next_cursor": rows[99]["created_at"].isoformat() if len(rows) > 100 else None,
            "pending_invites": [{"id": str(i["id"]), "alias": i["alias"], "expires_at": i["expires_at"].isoformat()}
                                for i in invites]}

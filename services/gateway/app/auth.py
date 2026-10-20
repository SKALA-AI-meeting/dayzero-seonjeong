"""Cookie JWT auth, CSRF/Origin checks, internal service auth, scoped MCP capabilities."""
from __future__ import annotations

import hashlib
import hmac
import secrets
import time
import uuid
from dataclasses import dataclass

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import Depends, Request, Response

from shared.config import settings

from .errors import ApiError

COOKIE = "dz_session"
TTL_SECONDS = 8 * 3600
CAPABILITY_TTL = 120
_hasher = PasswordHasher()


@dataclass
class Principal:
    sub: str
    role: str
    company_id: str
    session_id: str | None
    csrf: str


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def new_invite_token() -> str:
    return secrets.token_urlsafe(32)


def verify_password(hash_: str, password: str) -> bool:
    try:
        return _hasher.verify(hash_, password)
    except VerifyMismatchError:
        return False
    except Exception:
        return False


def issue_cookie(response: Response, *, sub: str, role: str, company_id: str, session_id: str | None) -> str:
    s = settings()
    csrf = secrets.token_urlsafe(24)
    now = int(time.time())
    claims = {"sub": sub, "role": role, "company_id": company_id, "exp": now + TTL_SECONDS,
              "iat": now, "jti": str(uuid.uuid4()), "csrf": csrf}
    if session_id:
        claims["session_id"] = session_id
    token = jwt.encode(claims, s.jwt_secret, algorithm="HS256")
    response.set_cookie(COOKIE, token, httponly=True, samesite="lax", max_age=TTL_SECONDS,
                        secure=s.app_origin.startswith("https://"), path="/")
    return csrf


def clear_cookie(response: Response) -> None:
    response.delete_cookie(COOKIE, path="/")


def _decode(request: Request) -> Principal | None:
    raw = request.cookies.get(COOKIE)
    if not raw:
        return None
    try:
        c = jwt.decode(raw, settings().jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        return None
    return Principal(sub=c["sub"], role=c["role"], company_id=c["company_id"],
                     session_id=c.get("session_id"), csrf=c["csrf"])


def optional_principal(request: Request) -> Principal | None:
    return _decode(request)


def _check_mutation(request: Request, p: Principal) -> None:
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return
    origin = request.headers.get("origin")
    if origin and origin != settings().app_origin:
        raise ApiError(403, "FORBIDDEN", "허용되지 않은 Origin입니다")
    token = request.headers.get("x-csrf-token", "")
    if not hmac.compare_digest(token, p.csrf):
        raise ApiError(403, "FORBIDDEN", "CSRF 토큰이 유효하지 않습니다")


def principal(request: Request) -> Principal:
    p = _decode(request)
    if not p:
        raise ApiError(401, "UNAUTHENTICATED", "로그인이 필요합니다")
    _check_mutation(request, p)
    return p


def admin(p: Principal = Depends(principal)) -> Principal:
    if p.role != "ADMIN":
        raise ApiError(403, "FORBIDDEN", "관리자 권한이 필요합니다")
    return p


def candidate(p: Principal = Depends(principal)) -> Principal:
    if p.role != "CANDIDATE":
        raise ApiError(403, "FORBIDDEN", "지원자 권한이 필요합니다")
    return p


# ---- internal service auth -------------------------------------------------

def internal_service(request: Request) -> None:
    """Service-to-service auth. Browser cookies are never accepted here."""
    token = request.headers.get("x-service-token", "")
    if not settings().internal_service_secret or not hmac.compare_digest(token, settings().internal_service_secret):
        raise ApiError(403, "FORBIDDEN", "내부 서비스 인증 실패")


def issue_capability(*, audience: str, session_id: str, run_id: str, actor: str,
                     allowed_tools: list[str], delegation_id: str | None) -> tuple[str, int]:
    exp = int(time.time()) + CAPABILITY_TTL
    claims = {"aud": audience, "session_id": session_id, "run_id": run_id, "actor": actor,
              "allowed_tools": allowed_tools, "delegation_id": delegation_id, "exp": exp, "typ": "capability"}
    return jwt.encode(claims, settings().internal_service_secret, algorithm="HS256"), exp


def verify_capability(token: str, audience: str) -> dict:
    try:
        c = jwt.decode(token, settings().internal_service_secret, algorithms=["HS256"], audience=audience)
    except jwt.PyJWTError as e:
        raise ApiError(403, "FORBIDDEN", f"capability 검증 실패: {type(e).__name__}") from e
    if c.get("typ") != "capability":
        raise ApiError(403, "FORBIDDEN", "capability 형식 오류")
    return c

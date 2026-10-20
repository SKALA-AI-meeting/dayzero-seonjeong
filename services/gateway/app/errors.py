from __future__ import annotations

import uuid

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

RETRYABLE = {"RATE_LIMITED", "UPSTREAM_UNAVAILABLE", "TIMEOUT"}


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str):
        self.status, self.code, self.message = status, code, message


def body(code: str, message: str) -> dict:
    return {"error": {"code": code, "message": message, "retryable": code in RETRYABLE,
                      "trace_id": str(uuid.uuid4())}}


def install(app) -> None:
    @app.exception_handler(ApiError)
    async def _api(_: Request, e: ApiError):
        return JSONResponse(body(e.code, e.message), status_code=e.status)

    @app.exception_handler(RequestValidationError)
    async def _val(_: Request, e: RequestValidationError):
        fields = [".".join(str(x) for x in err.get("loc", [])) for err in e.errors()]
        return JSONResponse(body("VALIDATION_ERROR", f"요청 형식 오류: {', '.join(fields)[:300]}"), status_code=422)

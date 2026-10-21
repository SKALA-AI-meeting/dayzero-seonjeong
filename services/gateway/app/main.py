from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, suppress
import logging
import httpx
from fastapi import FastAPI

from shared.config import settings
from shared.db import one, tx

from . import errors
from .api import auth_routes, sessions

s = settings()
s.require_secrets("database_url", "jwt_secret", "internal_service_secret")

async def clock_loop():
    from . import engine
    while True:
        try:
            def advance():
                with tx(s.psycopg_dsn) as c:
                    rows = c.execute("SELECT * FROM sessions WHERE status='ACTIVE' FOR UPDATE SKIP LOCKED").fetchall()
                    for session in rows:
                        engine.tick(c, session, on_action=False)
            await asyncio.to_thread(advance)
        except Exception:
            logging.getLogger(__name__).exception("Exam clock tick failed")
        await asyncio.sleep(0.5)


@asynccontextmanager
async def lifespan(app):
    task = asyncio.create_task(clock_loop())
    yield
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task


app = FastAPI(lifespan=lifespan, title="Day Zero gateway", version="0.1.0")
errors.install(app)
API = "/api/v1"
app.include_router(auth_routes.router, prefix=API)
app.include_router(sessions.router, prefix=API)

try:  # routers added in later milestones
    from .api import work
    app.include_router(work.router, prefix=API)
except ImportError:  # pragma: no cover
    pass
try:
    from .internal import routes as internal_routes
    app.include_router(internal_routes.router, prefix="/internal/v1")
    from .internal import dayzero as dayzero_routes
    app.include_router(dayzero_routes.router, prefix="/internal/v1")
except ImportError:  # pragma: no cover
    pass


@app.get(f"{API}/health")
def health():
    out = {"status": "ok", "db": "down", "agent": "down", "mcp": {}, "mode": None}
    try:
        with tx(s.psycopg_dsn) as c:
            one(c, "SELECT 1")
        out["db"] = "up"
    except Exception:
        out["status"] = "degraded"
    try:
        r = httpx.get(f"{s.agent_internal_url}/health", timeout=2)
        body = r.json()
        out["agent"] = "up"
        out["mode"] = body.get("mode")
        out["mcp"] = body.get("mcp", {})
    except Exception:
        out["status"] = "degraded"
    return out

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI

from shared.config import settings

from . import worker

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
S = settings()
S.require_secrets("checkpoint_database_url", "internal_service_secret")
if S.llm_mode == "live":
    if not os.environ.get("OPENAI_API_KEY"):
        raise RuntimeError("LLM_MODE=live 이지만 OPENAI_API_KEY가 없습니다")
if S.langsmith_enabled:
    os.environ.setdefault("LANGSMITH_TRACING", "true")
    os.environ.setdefault("LANGSMITH_PROJECT", S.langsmith_project)
else:
    os.environ["LANGSMITH_TRACING"] = "false"


@asynccontextmanager
async def lifespan(_: FastAPI):
    worker.start()
    yield
    w = worker.current()
    if w:
        w.stop.set()


app = FastAPI(title="Day Zero agent", lifespan=lifespan)


@app.get("/health")
def health():
    mcp = {}
    for name, url in (("business", S.business_mcp_url), ("rag", S.rag_mcp_url)):
        try:
            httpx.post(url, json={}, timeout=2)
            mcp[name] = "up"
        except Exception:  # noqa: BLE001
            mcp[name] = "down"
    w = worker.current()
    from shared import mq
    queue = {"enabled": mq.enabled()}
    if mq.enabled():
        try:
            queue["counts"] = mq.queue_counts()
        except Exception as e:  # noqa: BLE001
            queue["error"] = type(e).__name__
    return {"status": "ok" if w else "starting", "mode": S.llm_mode, "queue": queue, "model": S.openai_model, "mcp": mcp,
            "langsmith": "enabled" if S.langsmith_enabled else "not_configured",
            "worker_last_error": w.last_error if w else None}

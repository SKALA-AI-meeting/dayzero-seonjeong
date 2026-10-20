"""DB job worker: claims AGENT / POLICY_CHECK / REPORT jobs via gateway internal API (1s poll, single worker)."""
from __future__ import annotations

import logging
import os
import threading
import time
import traceback
import uuid

from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.types import Command
from psycopg import Connection
from psycopg.rows import dict_row

from shared.config import settings

from . import graph as G
from .clients import Gateway

log = logging.getLogger("agent.worker")
S = settings()
WORKER_ID = f"agent-{os.getpid()}-{uuid.uuid4().hex[:6]}"


class Worker:
    def __init__(self) -> None:
        self.gw = Gateway()
        self.stop = threading.Event()
        self.conn = Connection.connect(S.checkpoint_database_url, autocommit=True, prepare_threshold=0, row_factory=dict_row)
        self.saver = PostgresSaver(self.conn)
        self.saver.setup()  # idempotent, creates tables in the checkpoints schema
        self.app = G.build(self.saver)
        self.last_error: str | None = None

    def run_forever(self) -> None:
        log.info("worker %s started (mode=%s)", WORKER_ID, S.llm_mode)
        while not self.stop.is_set():
            try:
                job = self.gw.post("/jobs/claim", {"worker_id": WORKER_ID, "kinds": ["AGENT", "REPORT"]})["job"]
            except Exception as e:  # noqa: BLE001
                self.last_error = f"claim: {e}"
                time.sleep(2)
                continue
            if not job:
                time.sleep(1)
                continue
            try:
                outcome = self.handle(job)
                self.gw.post(f"/jobs/{job['id']}/complete", {"worker_id": WORKER_ID, "outcome": outcome})
            except Exception as e:  # noqa: BLE001
                log.error("job %s failed: %s", job["id"], traceback.format_exc())
                self.last_error = str(e)[:300]
                try:
                    self.gw.post(f"/jobs/{job['id']}/complete", {"worker_id": WORKER_ID, "outcome": "FAILED", "error": str(e)[:300]})
                except Exception:  # noqa: BLE001
                    pass

    def handle(self, job: dict) -> str:
        if job["kind"] == "REPORT":
            return self.run_report(job)
        return self.run_agent(job)

    def run_report(self, job: dict) -> str:
        """REPORT job은 DB jobs 경로 하나로만 처리. 실패하면 리포트를 FAILED로 표시해 관리자 '다시 생성'으로 재시도."""
        from .report import run_report
        try:
            run_report(self.gw, job)
            return "DONE"
        except Exception as e:  # noqa: BLE001
            log.error("report job %s failed: %s", job["id"], traceback.format_exc())
            self.gw.post(f"/reports/{job['session_id']}/failed", {"report_id": job["input"]["report_id"], "error": str(e)[:300]})
            return "FAILED"

    def run_agent(self, job: dict) -> str:
        rid, sid = job["run_id"], job["session_id"]
        config = {"configurable": {"thread_id": f"{sid}:{rid}"},
                  "metadata": {"run_id": rid, "session_id": sid}, "run_name": f"dayzero-{job['input'].get('kind', 'run')}",
                  "tags": ["dayzero", S.llm_mode]}
        resume = job["input"].get("resume")
        try:
            if resume:
                self.gw.state(rid, "RUNNING")
                result = self.app.invoke(Command(resume=resume), config)
            else:
                snap = self.app.get_state(config)
                self.gw.state(rid, "RUNNING")
                # lease 만료로 재claim된 경우 checkpoint에서 이어서 실행
                result = self.app.invoke(None if snap and snap.next else {"run_id": rid, "session_id": sid}, config)
        except Exception as e:  # noqa: BLE001
            code = "LLM_UNAVAILABLE" if G.H.is_retryable(e) else "AGENT_ERROR"
            log.error("run %s failed: %s", rid, traceback.format_exc())
            self.gw.state(rid, "FAILED", error_code=code, result={"error": type(e).__name__})
            return "FAILED"
        if result.get("__interrupt__"):
            self.gw.state(rid, "WAITING_APPROVAL", result=G.summarize_result(result), token_usage=result.get("token_usage"))
            return "WAITING_APPROVAL"
        self.gw.state(rid, "SUCCEEDED", result=G.summarize_result(result), token_usage=result.get("token_usage"),
                      error_code=result.get("error_code"))
        return "DONE"


_worker: Worker | None = None


def _ticker(w: Worker) -> None:
    """Exam clock: ask the gateway to fire due scenario events (server-owned facts, at most once each)."""
    while not w.stop.is_set():
        try:
            w.gw.post("/timeline/tick", {})
        except Exception as e:  # noqa: BLE001
            w.last_error = f"tick: {e}"
        time.sleep(2)


def start() -> Worker:
    global _worker
    _worker = Worker()
    threading.Thread(target=_worker.run_forever, name="job-worker", daemon=True).start()
    threading.Thread(target=_ticker, args=(_worker,), name="exam-ticker", daemon=True).start()
    return _worker


def current() -> Worker | None:
    return _worker

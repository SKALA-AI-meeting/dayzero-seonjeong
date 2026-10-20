"""Environment settings shared by all services. Values come from process env, then ../.env."""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data" / "moarun-rejoin-v1"
PROMPTS_DIR = ROOT / "prompts"


def _load_dotenv() -> None:
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if value and key not in os.environ:
            os.environ[key] = value


_load_dotenv()


class Settings:
    def __init__(self) -> None:
        g = os.environ.get
        self.app_env = g("APP_ENV", "development")
        self.app_origin = g("APP_ORIGIN", "http://localhost:3100")
        self.database_url = g("DATABASE_URL", "")
        self.checkpoint_database_url = g("CHECKPOINT_DATABASE_URL", "")
        self.rag_database_url = g("RAG_DATABASE_URL", "")
        self.indexer_database_url = g("INDEXER_DATABASE_URL", "")
        self.gateway_internal_url = g("GATEWAY_INTERNAL_URL", "http://localhost:8000")
        self.agent_internal_url = g("AGENT_INTERNAL_URL", "http://localhost:8001")
        self.business_mcp_url = g("BUSINESS_MCP_URL", "http://localhost:9101/mcp")
        self.rag_mcp_url = g("RAG_MCP_URL", "http://localhost:9102/mcp")
        self.rag_mode = g("RAG_MODE", "vector")
        self.embedding_model = g("EMBEDDING_MODEL", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
        self.embedding_dimension = int(g("EMBEDDING_DIMENSION", "384"))
        self.index_version = g("INDEX_VERSION", "moarun-index-v1")
        self.llm_mode = g("LLM_MODE", "fixture")
        self.openai_model = g("OPENAI_MODEL", "gpt-4o-mini")
        self.jwt_secret = g("JWT_SECRET", "")
        self.internal_service_secret = g("INTERNAL_SERVICE_SECRET", "")
        self.seed_admin_email = g("SEED_ADMIN_EMAIL", "admin@dayzero.local")
        self.seed_admin_password = g("SEED_ADMIN_PASSWORD", "")
        self.langsmith_enabled = bool(g("LANGSMITH_API_KEY")) and g("LANGSMITH_TRACING", "true") == "true"
        self.langsmith_project = g("LANGSMITH_PROJECT", "dayzero-seonjeong-mvp")

    @property
    def psycopg_dsn(self) -> str:
        return self.database_url.replace("postgresql+psycopg://", "postgresql://")

    def require_secrets(self, *names: str) -> None:
        missing = [n for n in names if not getattr(self, n)]
        if missing:
            raise RuntimeError(f"필수 환경변수가 비어 있어 시작을 거절합니다: {', '.join(missing)}")


@lru_cache
def settings() -> Settings:
    return Settings()


SCENARIO_ID = "moarun-rejoin-v1"
SCENARIO_VERSION = 1
POLICY_VERSION = "exam-v1"
DATASET_VERSION = "rejoin-data-v1"
SECTION_IDS = ["problem", "interview_evidence", "features", "similar_cases", "metrics_timeline"]
EXAM_MINUTES = 120

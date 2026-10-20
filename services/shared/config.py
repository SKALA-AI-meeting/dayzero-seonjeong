"""Environment settings shared by all services. Values come from process env, then ../.env."""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data" / "fitmoa-invite-v1"
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
        self.index_version = g("INDEX_VERSION", "fitmoa-index-v1")
        self.llm_mode = g("LLM_MODE", "fixture")
        self.openai_model = g("OPENAI_MODEL", "gpt-4o-mini")
        self.jwt_secret = g("JWT_SECRET", "")
        self.internal_service_secret = g("INTERNAL_SERVICE_SECRET", "")
        self.seed_admin_email = g("SEED_ADMIN_EMAIL", "admin@dayzero.local")
        self.seed_admin_password = g("SEED_ADMIN_PASSWORD", "")
        self.langsmith_enabled = bool(g("LANGSMITH_API_KEY")) and g("LANGSMITH_TRACING", "true") == "true"
        self.langsmith_project = g("LANGSMITH_PROJECT", "dayzero-seonjeong-mvp")
        # E4(마감 전 브리핑)는 optional 이벤트. 기본 켬(설계서 D7)
        self.event_e4_enabled = g("EVENT_E4_ENABLED", "true").lower() != "false"
        # 회사 기준(company-mcp): company_id=url 목록. gateway만 읽어 리포트 job에 URL을 넣는다(Agent는 URL만 받음)
        self.company_mcp_urls = dict(kv.split("=", 1) for kv in g("COMPANY_MCP_URLS", "").split(",") if "=" in kv)
        self.default_company_id = g("DEFAULT_COMPANY_ID", "") or next(iter(self.company_mcp_urls), "")
        # dayzero-mcp(평가자용 근거 조회) 토큰. 값은 로그·문서에 남기지 않는다
        self.dayzero_mcp_token = g("DAYZERO_MCP_TOKEN", "")

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


# DB·데이터 폴더 ID(fitmoa-invite-v1) ↔ 시나리오 JSON의 scenario_id(sc-a, doc://sc-a/...) 매핑
SCENARIO_ID = "fitmoa-invite-v1"
SCENARIO_KEY = "sc-a"
SCENARIO_ALIASES = {SCENARIO_ID: SCENARIO_ID, SCENARIO_KEY: SCENARIO_ID}
SCENARIO_VERSION = 1
POLICY_VERSION = "sc-a-v0.1"
PUBLIC_DOCUMENT_IDS = ["brief", "reward-table", "faq-draft", "tone-guide"]
CRITERIA_DOCUMENT_ID = "criteria"

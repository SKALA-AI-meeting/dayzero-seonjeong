# Day Zero 개인 MVP — 모아마켓 장바구니 이탈 협업 과제

지원자가 AI 동료(이도현)와 함께 가상 커머스의 장바구니 이탈 문제를 조사하고 개선 기획안을 제출합니다. 기업 담당자는 점수가 아닌 행동 근거 리포트를 확인합니다. 명세는 [docs/](docs/)(PRD·ARCHITECTURE·AGENT_GUIDE·SCENARIO_DATA)를 따릅니다.

앱 루트는 이 저장소입니다(`dayzero-seonjeong`). 현재 상태와 검증 결과는 [evidence/](evidence/)에 있습니다.

## 구성

| 서비스 | 포트 | 실행 모듈 |
|---|---|---|
| web (Next.js 15.5) | 3100 | `frontend` — `/api/**`를 gateway로 프록시 |
| gateway (FastAPI) | 8000 | `gateway.app.main:app` — 인증·업무 API·SSE·내부 API, 업무 DB 쓰기 단독 |
| agent (FastAPI + LangGraph) | 8001 | `agent.app.main:app` — DB job worker, PostgreSQL checkpoint |
| business-mcp | 9101 `/mcp` | `business_mcp.server` — gateway 내부 API로만 전달 |
| rag-mcp | 9102 `/mcp` | `rag_mcp.server` — pgvector 검색(읽기 전용 role) |
| db | 5434(호스트) | `pgvector/pgvector:pg17` |

확정 버전(MD 지침 대신 로컬 환경 기준): Python 3.11.9(uv), Node 26.7, Next 15.5, FastAPI 0.150, LangGraph 1.2, langgraph-checkpoint-postgres 3.2, mcp 2.3, sentence-transformers 6.1, PostgreSQL 17 + pgvector 0.8.7. 호스트 5432·5433은 이미 사용 중이라 DB 호스트 포트는 5434입니다.

## 로컬 실행 (현재 검증된 방법)

```bash
# 0) 최초 1회
cp .env.example .env   # DSN의 @db:5432 → @localhost:5434, 내부 URL → localhost, 비밀값 직접 설정
docker run -d --name dayzero-db -e POSTGRES_USER=dayzero -e POSTGRES_PASSWORD=local_demo_only \
  -e POSTGRES_DB=dayzero -p 5434:5432 -v dayzero_pgdata:/var/lib/postgresql/data pgvector/pgvector:pg17
cd services && uv sync
uv run alembic upgrade head
uv run python -m scripts.seed
uv run python -m scripts.index_documents --scenario commerce-cart-v1   # 임베딩 모델 다운로드 + 색인
cd ../frontend && npm ci

# 1) 서비스 실행 (각각 별도 터미널, services/ 에서)
uv run uvicorn gateway.app.main:app --host 127.0.0.1 --port 8000
uv run python -m business_mcp.server
uv run python -m rag_mcp.server
uv run uvicorn agent.app.main:app --host 127.0.0.1 --port 8001          # fixture
LLM_MODE=live uv run uvicorn agent.app.main:app --host 127.0.0.1 --port 8001   # 실제 gpt-4o-mini
# frontend/ 에서
npm run dev    # http://localhost:3100

# 2) 검증
curl http://localhost:8000/api/v1/health
uv run pytest -q tests/test_m0_auth.py
uv run python -m scripts.smoke_mcp
uv run python -m scripts.smoke_flow --mode fixture   # agent 모드와 일치시켜 실행
```

관리자 로그인: `http://localhost:3100/admin/login`, 이메일 `admin@dayzero.local`, 비밀번호는 `.env`의 `SEED_ADMIN_PASSWORD`. 초대 링크를 만든 뒤 다른 브라우저(또는 시크릿 창)에서 열면 지원자로 입장합니다.

Docker Compose 실행(`compose.yaml`)은 아직 작성 전입니다(M5).

## 근거와 구현 가정

- 근거 S1~S5와 구현 가정 A1~A7은 [docs/PRD.md](docs/PRD.md) §2~3을 그대로 따릅니다. 공식 교안 평가표는 인쇄 73쪽(PDF 74페이지) 표 6-14에서 확인한 것이며, 배점 확인과 이 앱의 평가 통과는 별개입니다.
- 교안 53쪽 레퍼런스 스택(Vue 3/Spring Boot 3)과 달리 Next.js/FastAPI를 사용합니다(A2, 개인 구현 가정).
- 웹 실시간 전송은 REST 202 + SSE(A3), 모델은 `gpt-4o-mini` 고정(A5), 임베딩은 로컬 384차원 모델(A6).
- 위임 run이 끝나면(승인 반영 또는 거절) gateway가 동료 태스크를 REVIEW로 전환합니다. 동료가 `update_task_status`로 직접 바꾸려면 변경별 승인이 하나 더 필요해 시연 흐름이 길어지므로 내린 구현 결정입니다. DONE은 지원자 검토로만 결정됩니다.
- 임베딩 입력은 "문서 제목: 청크"이고, 저장·인용 본문은 원문 그대로입니다(SCENARIO_DATA §4의 모델용 표현과 원문 인용 분리).

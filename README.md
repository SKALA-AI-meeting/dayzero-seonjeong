# Day Zero 개인 MVP — 루프랩 모아런 재참여율 개선 과제

지원자가 가상 리모트 스타트업 루프랩의 프로덕트팀에 합류해, AI 동료 이도현과 2시간 동안 "모아런 재참여율 개선 신규 기능 기획안"을 만듭니다. 업무 분담·도움 요청·자료 지연·요구사항 변경·동료 오류 같은 상황이 모든 지원자에게 같은 시각에 일어나고, 기업 담당자는 점수가 아닌 5개 영역(책임감·존중소통·협력·유연성·AI 활용)의 행동 근거 리포트를 확인합니다.

시험 내용의 최우선 기준은 [DAYZERO_EXAM_SCENARIO.md](DAYZERO_EXAM_SCENARIO.md)이고, 기술 계약은 [docs/](docs/)(PRD·ARCHITECTURE·AGENT_GUIDE·SCENARIO_DATA)를 따릅니다.

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
uv run python -m scripts.index_documents --scenario moarun-rejoin-v1   # 임베딩 모델 다운로드 + 색인
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

시험은 실제 2시간 기준으로 진행되며 이벤트(00:10 업무 분담 ~ 02:00 자동 제출)는 서버 시계로 발생합니다. 시연할 때는 관리자 세션 목록의 "시연: 이벤트로 이동" 메뉴로 다음 이벤트 시각으로 건너뛸 수 있습니다(`APP_ENV=development`에서만 표시, 지원자 화면에는 노출되지 않음).

Docker Compose(`compose.yaml`, `services/Dockerfile`, `frontend/Dockerfile`)는 작성했지만 컨테이너 빌드·기동은 아직 검증하지 않았습니다. 검증된 실행 방법은 위의 로컬 실행입니다.

```bash
# (미검증) Compose
cp .env.example .env   # 비밀값 설정
docker compose up -d db && docker compose run --rm gateway uv run alembic upgrade head
docker compose run --rm gateway uv run python -m scripts.seed
docker compose --profile tools run --rm indexer
docker compose up -d
```

## 검증 상태

AT-01~AT-17 판정과 근거는 [evidence/verification.md](evidence/verification.md)에 있습니다(PASS 13 / PARTIAL 4). Harness 8요소 평가: `uv run python -m scripts.eval_harness --suite harness-v1 --label <label>` → `evals/results/`.

## 근거와 구현 가정

- 근거 S1~S5와 구현 가정 A1~A7은 [docs/PRD.md](docs/PRD.md) §2~3을 그대로 따릅니다. 공식 교안 평가표는 인쇄 73쪽(PDF 74페이지) 표 6-14에서 확인한 것이며, 배점 확인과 이 앱의 평가 통과는 별개입니다.
- 교안 53쪽 레퍼런스 스택(Vue 3/Spring Boot 3)과 달리 Next.js/FastAPI를 사용합니다(A2, 개인 구현 가정).
- 웹 실시간 전송은 REST 202 + SSE(A3), 모델은 `gpt-4o-mini` 고정(A5), 임베딩은 로컬 384차원 모델(A6).
- 업무 분담이 확정되면 동료 담당 섹션마다 위임(delegation)과 Agent run이 생깁니다. 동료는 MCP로 자료를 조회해 초안을 만들고, 문서에 넣기 전에 확인 카드(LangGraph interrupt)로 승인을 받습니다. run이 끝나면 gateway가 동료 태스크를 REVIEW로 전환합니다(`update_task_status`까지 승인을 받으면 흐름이 길어지기 때문에 내린 구현 결정). DONE은 지원자 검토로만 결정됩니다.
- 01:30 동료 오류(유료 멤버십 제안)는 고정 메시지로 발생합니다. 지원자가 정책·재검토를 언급하면 동료가 운영 정책 문서를 다시 검색해 정정하고, 지적이 없으면 스스로 고치지 않습니다.
- 임베딩 입력은 "문서 제목: 청크"이고, 저장·인용 본문은 원문 그대로입니다(SCENARIO_DATA §4의 모델용 표현과 원문 인용 분리).

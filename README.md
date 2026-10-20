# Day Zero 개인 MVP — 루프랩 모아런 재참여율 개선 과제

지원자가 가상 리모트 스타트업 루프랩의 프로덕트팀에 합류해, AI 동료 이도현과 2시간 동안 "모아런 재참여율 개선 신규 기능 기획안"을 만듭니다. 업무 분담·도움 요청·자료 지연·요구사항 변경·동료 오류 같은 상황이 모든 지원자에게 같은 시각에 일어나고, 기업 담당자는 점수가 아닌 5개 영역(책임감·존중소통·협력·유연성·AI 활용)의 행동 근거 리포트를 확인합니다.

시험 내용의 최우선 기준은 [docs/DAYZERO_EXAM_SCENARIO.md](docs/DAYZERO_EXAM_SCENARIO.md)이고, 기술 계약·디자인·검증 기준은 [docs/](docs/README.md)(PRD·ARCHITECTURE·SCENARIO_DATA·AGENT_GUIDE·DESIGN_GUIDE)를 따릅니다.

앱 루트는 이 저장소입니다(`dayzero-seonjeong`). 현재 상태와 검증 결과는 [evidence/](evidence/)에 있습니다.

## 폴더 구조

```text
dayzero-seonjeong/
  README.md              실행 방법·구성·검증 상태
  compose.yaml           (미검증) 컨테이너 실행
  infra/                 로컬 실행 스크립트(dev-up / dev-status / dev-down)
  docs/                  명세·지침 원본(문서 안내: docs/README.md)
  data/moarun-rejoin-v1/ 시나리오 seed(회사 자료 5개, 지표, 인터뷰, 이벤트 정책, 검색 평가셋)
  prompts/               버전 관리되는 시스템 프롬프트(동료·어시스턴트·섹션 작성·요약·리포트)
  services/              Python(gateway, agent, business_mcp, rag_mcp, shared, scripts, tests)
  frontend/              Next.js 웹(포트 3100)
  evals/                 Harness 8요소 평가셋과 결과(evals/results/)
  evidence/              검증 기록(verification.md), 스모크 결과, 화면 캡처
```

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

## 실행 방법

### 준비물
- Docker Desktop(실행 중), Python 3.11 + [uv](https://docs.astral.sh/uv/), Node.js(22 이상)
- 사용 포트: 3100(web), 8000(gateway), 8001(agent), 9101/9102(MCP), 5434(PostgreSQL)

### 최초 1회: 환경 파일
```bash
cp .env.example .env
```
`.env`에서 다음을 로컬 값으로 바꿉니다.
- 컨테이너 주소 `@db:5432` → `@localhost:5434`
- `GATEWAY_INTERNAL_URL`, `AGENT_INTERNAL_URL`, `BUSINESS_MCP_URL`, `RAG_MCP_URL` → `http://localhost:포트`
- 비밀값 `JWT_SECRET`, `INTERNAL_SERVICE_SECRET`, `SEED_ADMIN_PASSWORD`(빈 값이면 서버가 시작을 거절함)
- 실제 LLM: `OPENAI_API_KEY`, 관측: `LANGSMITH_API_KEY`(선택)

### 한 번에 실행 / 종료 (검증된 방법)
```bash
./infra/dev-up.sh                  # fixture 모드(.env의 LLM_MODE)
LLM_MODE=live ./infra/dev-up.sh    # 실제 gpt-4o-mini
./infra/dev-status.sh              # web·gateway·agent·MCP 상태
./infra/dev-down.sh                # 서비스 종료(DB 데이터 유지)
./infra/dev-down.sh --infra        # 컨테이너까지 정지(볼륨은 삭제하지 않음)
```
`dev-up.sh`가 하는 일: DB(pgvector pg17) 컨테이너 기동 → `uv sync` → 마이그레이션 → seed → (색인이 없으면) 벡터 색인 → gateway·business-mcp·rag-mcp·agent·web 백그라운드 실행 → 상태 확인. 로그는 `.run/logs/*.log`에 남습니다. 이미 떠 있는 서비스는 건너뜁니다.

### 사용해 보기
1. http://localhost:3100/admin/login: `admin@dayzero.local` / `.env`의 `SEED_ADMIN_PASSWORD`
2. "새 초대 만들기" → 링크 복사 → **다른 브라우저 또는 시크릿 창**에서 열어 지원자로 입장
3. 시연 시간 이동: 관리자 세션 목록의 "시연: 이벤트로 이동"(00:10 분담 ~ 02:00 자동 제출, `APP_ENV=development`에서만 표시)
4. 제출 후 관리자 "리포트 열기"

### 테스트·검증 (services/ 에서)
```bash
uv run pytest -q tests/test_m0_auth.py                    # 인증 6건
uv run python -m scripts.smoke_mcp                        # MCP 22건
uv run python -m scripts.smoke_flow --mode live           # 시나리오 전체(agent 모드와 일치시킬 것)
uv run python -m scripts.eval_harness --suite harness-v1 --label baseline   # Harness 8요소
uv run python -m scripts.restart_resume prepare && ./../infra/dev-down.sh && ./../infra/dev-up.sh && uv run python -m scripts.restart_resume decide  # AT-08
```

### 수동 실행(서비스별로 직접 띄울 때)
```bash
cd services
uv run uvicorn gateway.app.main:app --host 127.0.0.1 --port 8000
uv run python -m business_mcp.server
uv run python -m rag_mcp.server
LLM_MODE=live uv run uvicorn agent.app.main:app --host 127.0.0.1 --port 8001
cd ../frontend && npm run dev
```

Docker Compose(`compose.yaml`, `services/Dockerfile`, `frontend/Dockerfile`)는 작성했지만 컨테이너 빌드·기동은 아직 검증하지 않았습니다. 검증된 실행 방법은 위의 로컬 실행입니다.

```bash
# (미검증) Compose
cp .env.example .env   # 비밀값 설정
docker compose up -d db && docker compose run --rm gateway uv run alembic upgrade head
docker compose run --rm gateway uv run python -m scripts.seed
docker compose --profile tools run --rm indexer
docker compose up -d
```

## 향후 고도화

여러 회사에 맞는 시험을 만드는 기능(기업 요구사항 입력 → 맞춤 시나리오 생성·검증·배포)은 [docs/archive/ROADMAP_MULTI_COMPANY.md](docs/archive/ROADMAP_MULTI_COMPANY.md)에 정리했습니다(P1 이후, 미구현).

## 검증 상태

AT-01~AT-17 판정과 근거는 [evidence/verification.md](evidence/verification.md)에 있습니다(리팩터링 중: 새 시나리오 기준으로 다시 작성 예정). Harness 8요소 평가: `uv run python -m scripts.eval_harness --suite harness-v1 --label <label>` → `evals/results/`.

## 근거와 구현 가정

- 근거 S1~S5와 구현 가정 A1~A7은 [docs/PRD.md](docs/PRD.md) §2~3을 그대로 따릅니다. 공식 교안 평가표는 인쇄 73쪽(PDF 74페이지) 표 6-14에서 확인한 것이며, 배점 확인과 이 앱의 평가 통과는 별개입니다.
- 교안 53쪽 레퍼런스 스택(Vue 3/Spring Boot 3)과 달리 Next.js/FastAPI를 사용합니다(A2, 개인 구현 가정).
- 웹 실시간 전송은 REST 202 + SSE(A3), 모델은 `gpt-4o-mini` 고정(A5), 임베딩은 로컬 384차원 모델(A6).
- 업무 분담이 확정되면 동료 담당 섹션마다 위임(delegation)과 Agent run이 생깁니다. 동료는 MCP로 자료를 조회해 초안을 만들고, 문서에 넣기 전에 확인 카드(LangGraph interrupt)로 승인을 받습니다. run이 끝나면 gateway가 동료 태스크를 REVIEW로 전환합니다(`update_task_status`까지 승인을 받으면 흐름이 길어지기 때문에 내린 구현 결정). DONE은 지원자 검토로만 결정됩니다.
- 01:30 동료 오류(유료 멤버십 제안)는 고정 메시지로 발생합니다. 지원자가 정책·재검토를 언급하면 동료가 운영 정책 문서를 다시 검색해 정정하고, 지적이 없으면 스스로 고치지 않습니다.
- 임베딩 입력은 "문서 제목: 청크"이고, 저장·인용 본문은 원문 그대로입니다(SCENARIO_DATA §4의 모델용 표현과 원문 인용 분리).

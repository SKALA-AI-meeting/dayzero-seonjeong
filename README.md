# Day Zero 개인 MVP — 핏모아 친구 초대 이벤트 협업 시뮬레이션

지원자가 가상 피트니스 앱 회사 **핏모아(FitMoa) 운영팀** 신입이 되어, AI 동료 **한서윤**과 함께 친구 초대 이벤트의 고객 안내 자료(안내문·FAQ 5개·리워드 표)를 준비합니다. 분업, 도움 요청, 요구사항 변경, 동료의 '다 했어요'(실제로는 미반영), 동료 이탈·복귀, 마감 전 보고 같은 상황이 **턴(행동 수) 기준**으로 모든 지원자에게 같은 순서로 일어나고, 서윤의 초안에는 오류 4개가 심어져 있습니다. 기업 담당자는 점수가 아닌 **5역량(책임감·계획성·적응성·협업·정직 보고)별 관찰 코드와 근거 원문** 리포트를 확인하고 사람이 판단합니다.

시나리오 기준은 [docs/SCENARIO_SC_A.md](docs/SCENARIO_SC_A.md)와 [data/fitmoa-invite-v1/scenario.json](data/fitmoa-invite-v1/scenario.json), 제품·기술 계약은 [docs/](docs/README.md)(PRD·ARCHITECTURE·AGENT_GUIDE·DESIGN_GUIDE)를 따릅니다. 검증 결과는 [evidence/verification.md](evidence/verification.md)에 있습니다.

## 폴더 구조

```text
dayzero-seonjeong/
  README.md                 실행 방법·구성·검증 상태
  compose.yaml              (미검증) 컨테이너 실행
  infra/                    로컬 실행 스크립트(dev-up / dev-status / dev-down / dev-reset-db / check-no-queue)
  docs/                     명세·지침 원본(문서 안내: docs/README.md)
  data/fitmoa-invite-v1/    시나리오 시드(scenario.json, 공유 문서 4개 + 관찰 코드북, 서윤 수정 규칙, 검색 평가셋)
  prompts/                  버전 관리되는 프롬프트(서윤·팀장 페르소나, 분기 분류기, 요약, 리포트 요약)
  services/                 Python(gateway, agent, business_mcp, rag_mcp, shared, scripts, tests)
  frontend/                 Next.js 웹(포트 3100)
  evals/                    Harness 8요소 평가셋과 결과(evals/results/)
  evidence/                 검증 기록(verification.md), UI 확인 스크립트, 화면 캡처
```

## 구성

| 서비스 | 포트 | 실행 모듈 |
|---|---|---|
| web (Next.js 15.5) | 3100 | `frontend` — `/api/**`를 gateway로 프록시 |
| gateway (FastAPI) | 8000 | `gateway.app.main:app` — 인증·업무 API·SSE·턴 이벤트 엔진·종료 판정·리포트, 업무 DB 쓰기 단독 |
| agent (FastAPI + LangGraph) | 8001 | `agent.app.main:app` — DB job worker(서윤·팀장 응답 run, 리포트), PostgreSQL checkpoint |
| business-mcp | 9101 `/mcp` | `business_mcp.server` — 시나리오·턴 조회, 관찰 기록, 승인 후 변경(gateway 내부 API로만) |
| rag-mcp | 9102 `/mcp` | `rag_mcp.server` — pgvector 검색(공유 문서·코드북), 문서 Resource, 페르소나 Prompt |
| company-mcp ×2 | 9201(A사)·9202(B사) `/mcp` | `company_mcp.server --company-dir …` — 회사 인재상·평가 매뉴얼 조항 검색(같은 코드, 데이터만 다름) |
| dayzero-mcp | 9103 `/mcp` 또는 stdio | `dayzero_mcp.server` — 평가자용 지원자 근거 조회(읽기 전용, 평가자 토큰, gateway 내부 API로만) |
| db | 5434(호스트) | `pgvector/pgvector:pg17` — 이 프로젝트가 띄우는 유일한 컨테이너 |

로컬 확정 버전: Python 3.11.9(uv), Node 26.7, Next 15.5, FastAPI 0.150, LangGraph 1.2, langgraph-checkpoint-postgres 3.2, mcp 2.3, sentence-transformers 6.1, PostgreSQL 17 + pgvector 0.8.7. 호스트 5432·5433은 이미 사용 중이라 DB 호스트 포트는 5434입니다.

## 실행 방법

### 준비물
- Docker Desktop(실행 중), Python 3.11 + [uv](https://docs.astral.sh/uv/), Node.js(22 이상)
- 사용 포트: 3100(web), 8000(gateway), 8001(agent), 9101/9102(MCP), 9201/9202(company-mcp), 9103(dayzero-mcp), 5434(PostgreSQL)

### 최초 1회: 환경 파일
```bash
cp .env.example .env
```
`.env`에서 다음을 로컬 값으로 바꿉니다.
- 컨테이너 주소 `@db:5432` → `@localhost:5434`
- `GATEWAY_INTERNAL_URL`, `AGENT_INTERNAL_URL`, `BUSINESS_MCP_URL`, `RAG_MCP_URL` → `http://localhost:포트`
- 비밀값 `JWT_SECRET`, `INTERNAL_SERVICE_SECRET`, `SEED_ADMIN_PASSWORD`(빈 값이면 서버가 시작을 거절함)
- 실제 LLM: `OPENAI_API_KEY`, 관측: `LANGSMITH_API_KEY`(선택), E4 브리핑 끄기: `EVENT_E4_ENABLED=false`
- 회사 기준: `COMPANY_MCP_URLS`(company_id=url, 쉼표 구분)·`DEFAULT_COMPANY_ID`, 평가자 토큰: `DAYZERO_MCP_TOKEN`(`openssl rand -hex 24`로 생성, 문서·로그에 값을 쓰지 않음)

### 한 번에 실행 / 종료 (검증된 방법)
```bash
./infra/dev-up.sh                  # fixture 모드(.env의 LLM_MODE, LLM 없이 결정적으로 동작)
LLM_MODE=live ./infra/dev-up.sh    # 실제 gpt-4o-mini
./infra/dev-status.sh              # web·gateway·agent·MCP 상태
./infra/dev-down.sh                # 서비스 종료(DB 데이터 유지)
./infra/dev-down.sh --infra        # DB 컨테이너까지 정지(볼륨은 삭제하지 않음)
```
`dev-up.sh`: DB 컨테이너 기동 → `uv sync` → 마이그레이션 → seed → (색인이 없으면) 벡터 색인 → 서비스 5개 백그라운드 실행 → 상태 확인. 로그는 `.run/logs/*.log`.

**이전 시나리오 DB를 쓰던 환경**은 스키마가 바뀌어 한 번 초기화해야 합니다(데이터 삭제):
```bash
./infra/dev-down.sh && ./infra/dev-reset-db.sh && ./infra/dev-up.sh
```

### 사용해 보기
1. http://localhost:3100/admin/login: `admin@dayzero.local` / `.env`의 `SEED_ADMIN_PASSWORD`
2. "새 초대 만들기" → 링크 복사 → **다른 브라우저 또는 시크릿 창**에서 열어 지원자로 입장
3. 메시지·보드 변경·산출물 저장마다 턴이 쌓이고 턴 5/9/11/13/16/17에 이벤트가 일어납니다. 시연 때는 관리자 세션 목록의 "시연: 다음 이벤트"(`APP_ENV=development`에서만)로 건너뛸 수 있습니다.
4. E4 보고 후 자동 종료(또는 '업무 종료') → 디브리핑 → 관리자 "리포트 열기"

### 테스트·검증 (services/ 에서, 서비스가 떠 있는 상태)
```bash
uv run pytest -q                                           # 인증·소유권
uv run python -m scripts.smoke_mcp                         # MCP 2개 서버 계약·오류 처리
uv run python -m scripts.smoke_flow --mode fixture         # E0→E4→디브리핑→리포트, E2B 건너뜀, SSE 재생
uv run python -m scripts.eval_harness --suite harness-v1 --label <label>   # Harness 8요소 → evals/results/
uv run python -m scripts.restart_resume prepare && ../infra/dev-down.sh && ../infra/dev-up.sh && uv run python -m scripts.restart_resume decide
../infra/check-no-queue.sh                                 # 이전 메시지 큐 잔재 0건 확인
```
UI 확인(실제 브라우저, 프로젝트 의존성 아님): 저장소 루트에서 `uv run --no-project --with playwright python evidence/ui_check.py "$PWD"`.

### 회사 기준 바꿔 꽂기 · 평가자용 MCP (services/ 에서)
`dev-up.sh`가 아래 3개도 함께 띄웁니다. 직접 띄울 때:
```bash
uv run python -m company_mcp.server --company-dir ../data/companies/a-startup --port 9201   # A사(가상 스타트업)
uv run python -m company_mcp.server --company-dir ../data/companies/b-finance --port 9202   # B사(가상 금융사)
uv run python -m dayzero_mcp.server                 # HTTP :9103/mcp (Authorization: Bearer <YOUR_TOKEN>)
uv run python -m dayzero_mcp.server --stdio         # stdio (환경변수 DAYZERO_TOKEN=<YOUR_TOKEN>)
```
- 회사 데이터는 `data/companies/<company_id>/`(company.json, values.md, eval-manual.md). 회사를 추가하려면 폴더를 만들고 포트를 하나 더 띄운 뒤 `COMPANY_MCP_URLS`에 추가합니다. Agent·gateway 코드는 바꾸지 않습니다.
- 리포트는 기본 회사 기준(`DEFAULT_COMPANY_ID`)으로 관찰 코드마다 조항을 연결합니다. 관리자 리포트 화면 상단 "기준 선택 → 이 기준으로 다시 생성", 또는 API `POST /api/v1/reports/{sid}/retry {"company_id":"b-finance"}`. 연결은 근거 첨부이며 판정이 아닙니다.
- 시연용 완료 세션(페르소나 4명): `uv run python -m scripts.seed_candidates`(fixture 모드). 기존 리포트만 다시 연결: `--relink`
- 검증: `uv run python -m scripts.smoke_company_mcp`(A사·B사 같은 질의 → 다른 조항, 같은 세션 A→B 재생성), `uv run python -m scripts.smoke_dayzero_mcp`(HTTP·stdio, 토큰 없음/틀린 토큰 거부)

**MCP Inspector로 확인**
```bash
npx @modelcontextprotocol/inspector
```
- company-mcp: Transport `Streamable HTTP`, URL `http://localhost:9201/mcp`(B사는 9202) → Tools `search_criteria`, Resources `policy://eval-manual#4.1`
- dayzero-mcp: URL `http://localhost:9103/mcp`, Authentication에 Header `Authorization` = `Bearer <YOUR_TOKEN>` → `find_candidates_by_behavior`(예: `CO·N1`), `get_candidate_report`
- 또는 Transport `STDIO`, Command `uv`, Arguments `--directory <저장소 절대 경로>/services run python -m dayzero_mcp.server --stdio`, 환경변수 `DAYZERO_TOKEN=<YOUR_TOKEN>`

**Claude Desktop 연결(stdio)** — `~/Library/Application Support/Claude/claude_desktop_config.json`
```json
{
  "mcpServers": {
    "dayzero": {
      "command": "/절대/경로/uv",
      "args": ["--directory", "/절대/경로/dayzero-seonjeong/services", "run", "python", "-m", "dayzero_mcp.server", "--stdio"],
      "env": { "DAYZERO_TOKEN": "<YOUR_TOKEN>" }
    }
  }
}
```
- `command`는 `which uv` 결과(Claude Desktop은 셸 PATH를 쓰지 않음). gateway(8000)가 떠 있어야 하고, 서버는 `.env`의 `INTERNAL_SERVICE_SECRET`으로 gateway 내부 API를 호출합니다.
- `<YOUR_TOKEN>`은 `.env`의 `DAYZERO_MCP_TOKEN`과 같은 값. 저장 후 Claude Desktop을 재시작하고 "CO·N1 행동이 나온 지원자와 근거를 보여 줘"처럼 요청합니다. 도구는 근거 조회용이며 합격·탈락 결정은 평가자가 합니다.

### 수동 실행(서비스별로 직접 띄울 때)
```bash
cd services
uv run uvicorn gateway.app.main:app --host 127.0.0.1 --port 8000
uv run python -m business_mcp.server
uv run python -m rag_mcp.server
uv run uvicorn agent.app.main:app --host 127.0.0.1 --port 8001
cd ../frontend && npm run dev
```

Docker Compose(`compose.yaml`, `services/Dockerfile`, `frontend/Dockerfile`)는 서비스 구성만 맞춰 두었고 컨테이너 빌드·기동은 검증하지 않았습니다. 검증된 실행 방법은 위의 로컬 실행입니다.

## 검증 상태

수용 테스트 AT-01~AT-17 결과는 [evidence/verification.md](evidence/verification.md). 실제 LLM(live) 모드는 API 키가 없어 **미검증**입니다. 남은 일은 [docs/PRD.md](docs/PRD.md) 11장 TODO.

## 향후 고도화

기업별 맞춤 시나리오 생성 계획은 [docs/archive/ROADMAP_MULTI_COMPANY.md](docs/archive/ROADMAP_MULTI_COMPANY.md)(이전 시나리오 시절 작성, 미구현), 두 번째 시나리오(팀 워크숍 준비) 골격은 설계서 9장에 있습니다.

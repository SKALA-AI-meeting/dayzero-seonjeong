# 문서 안내

모든 명세·지침의 **원본은 이 폴더 한 곳**에만 둔다(루트·다른 폴더에 사본을 두지 않는다).

| 문서 | 역할 | 우선순위 |
|---|---|---|
| [SCENARIO_SC_A.md](SCENARIO_SC_A.md) | 시나리오 설계서: 5역량, 이벤트 E0~E4, 서윤 페르소나, 심어둔 오류, 관찰 코드북 — 시뮬레이션 내용의 **최우선 기준** | 1 (시나리오 내용) |
| `../data/fitmoa-invite-v1/scenario.json` | 시드 데이터 계약(이벤트 트리거·대사·분기·오류). 공유 문서·코드북(`documents/`), 서윤 수정 규칙(`colleague_fixes.json`) | 데이터 계약 |
| [PRD.md](PRD.md) v2.0 | 목적, 사용자 여정, 화면·상태, P0/제외 범위, AI 행동·공정성, 관찰·리포트 원칙, 평가표 매핑, 결정 필요, TODO | 2 |
| [ARCHITECTURE.md](ARCHITECTURE.md) v2.0 | 서비스 경계, DB 스키마, API·SSE·MCP 계약, 턴 이벤트 엔진, Agent Graph, Harness 8요소, 리포트 | 기술 계약 |
| [AGENT_GUIDE.md](AGENT_GUIDE.md) v2.0 | 개발 원칙, 실행·검증 명령, 수용 테스트 AT-01~17 | 개발·검증 |
| [DESIGN_GUIDE.md](DESIGN_GUIDE.md) v2.0 | 디자인 토큰·공통 원칙·접근성 | 디자인 |
| [REFACTOR_PLAN.md](REFACTOR_PLAN.md) | 이전 시나리오 → sc-a 리팩터링 인벤토리와 구현 결정 I1~I8(완료 기록) | 기록 |
| [archive/ROADMAP_MULTI_COMPANY.md](archive/ROADMAP_MULTI_COMPANY.md) | 기업별 맞춤 시나리오 생성 고도화 계획(이전 시나리오 시절 작성, 미구현) | 참고 |

검증 결과는 [`../evidence/verification.md`](../evidence/verification.md), 실행 방법은 루트 [`README.md`](../README.md).

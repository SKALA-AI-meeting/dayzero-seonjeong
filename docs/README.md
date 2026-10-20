# 문서 안내

모든 명세·지침의 **원본은 이 폴더 한 곳**에만 둔다(루트·다른 폴더에 사본을 두지 않는다).

| 문서 | 역할 | 우선순위 |
|---|---|---|
| [DAYZERO_EXAM_SCENARIO.md](DAYZERO_EXAM_SCENARIO.md) | 시험 내용·회사 데이터·인물·AI 동료 행동·이벤트·관찰 항목의 **최우선 기준**(사용자 제공 원본) | 1 (시험 내용) |
| [PRD.md](PRD.md) v1.3 | 목적, 평가표 매핑, 사용자 여정, 화면, P0/P1 경계, 공정성·리포트 원칙, 구현 가정 A1~A7 | 2 |
| [ARCHITECTURE.md](ARCHITECTURE.md) v1.3 | 서비스 경계, DB 스키마, API·SSE·MCP 계약, Agent State/Graph, Harness 8요소, 품질 속성 | 기술 계약 |
| [SCENARIO_DATA.md](SCENARIO_DATA.md) v2.0 | 시나리오를 seed·정책으로 옮긴 구현 명세(문서 원문, 산식, 이벤트 표) — `data/moarun-rejoin-v1/`와 일치 | 데이터 계약 |
| [AGENT_GUIDE.md](AGENT_GUIDE.md) v1.3 | 개발 지시서: 마일스톤 게이트, 실행 명령 계약, 수용 테스트 AT-01~17 | 개발·검증 |
| [DESIGN_GUIDE.md](DESIGN_GUIDE.md) v1.0 | 디자인 시스템(토큰·레이아웃·컴포넌트·접근성). 내용 예시는 이전 시나리오 기준이며 시험 내용은 1번 문서가 우선 | 디자인 |
| [ROADMAP_MULTI_COMPANY.md](ROADMAP_MULTI_COMPANY.md) | 기업별 맞춤 시나리오 생성 고도화 계획(P1 이후, 미구현) | 참고 |

검증 결과는 [`../evidence/verification.md`](../evidence/verification.md), 실행 방법은 루트 [`README.md`](../README.md).

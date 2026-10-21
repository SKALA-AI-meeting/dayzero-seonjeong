# 서윤 Agent 구현·검증 보고

기준: `origin/refactor/fitmoa-sc-a`의 `567ac1f`. 작업 브랜치: `feat/seoyoon-agent`.
`docs/` 변경 없음. `data/fitmoa-invite-v1/scenario.json`, `data/.../documents/criteria.md`, 페르소나 프롬프트를 수정했다.

## 결과표

| 항목 | 결과 | 증빙 |
|---|---|---|
| pytest: 인증·시간·승인·capability·잘못된 지적 | 21/21 통과 | `services/tests/` |
| fixture 리허설·시간·검토·E3B·말/행동 일치 | 30/30 통과 | `evidence/seoyoon-fixture.json` |
| live 리허설·시간·검토·E3B·말/행동 일치 | 30/30 통과 | `evidence/seoyoon-live.json` |
| MCP 계약·검색·권한·오류 | 35/35 통과 | `scripts.smoke_mcp` |
| Harness 8요소 | 8/8 통과 | `evals/results/harness-v1-seoyoon-fixture.json` |
| company-mcp 교체·리포트 연결 | 25/25 통과 | `scripts.smoke_company_mcp` |
| dayzero-mcp HTTP·stdio | 32/32 통과 | `scripts.smoke_dayzero_mcp` |
| 실제 재시작 후 승인 재개·중복 승인 | 통과: 같은 thread, 수정/receipt 각각 1회 | `scripts.restart_resume` |
| 4명 페르소나 기대 코드 | 4/4 통과 | `scripts.seed_candidates` |
| 브라우저 | 통과: 시계 갱신, 문서 버전/차이, 반응형, 10분 강조, 자동 디브리핑 | `evidence/screens/seoyoon/` |
| 전체 생성 응답 약속 감사 | 12개 응답, 위반 0건 | `evidence/seoyoon-promises.json` |
| 프런트 lint·TypeScript | 통과 | `npm run lint`, `npx tsc --noEmit` |
| 이전 시각 계약 잔재 | `services`, `frontend/src` 소스 0건 | 요청한 정규식 검사 |

검증은 실제 서버·DB·MCP·OpenAI `gpt-4o-mini`로 수행했다. 시간 회귀는 개발용 시계 이동을 사용했다. 60분을 실제로 기다린 검사는 아니다. live 결과는 고정된 한 실행의 증빙이며 LLM의 모든 표현을 보장하는 표본은 아니다.

## 바꾼 계약

- 세션: `started_at`부터 실제 초를 계산한다. `clock_offset_seconds`는 개발용 이동 값이다. 종전 시각 컬럼은 제거했다. 기존 데이터베이스에는 Alembic `0002_elapsed_clock`을 적용한다.
- 세션 API: `session.elapsed_seconds`, `clock.{elapsed_seconds,remaining_seconds,server_now}`. 이전 시작/마감 시각 문자열 필드는 제거했다. 메시지의 `meta.elapsed_seconds`는 저장 시점의 값이다.
- 이벤트: `time {open_at,force_at}`(분), E2B는 `after_event {event,open_after,force_after,condition}`. open 전 불가, open 뒤 행동/응답 run 완료 시 발생, force 뒤 서버 tick으로 발생한다. 응답/승인 중에는 일반 이벤트를 보류한다. E4는 항상 시작 후 50분, 제출은 60분이다. E4 답변은 제출을 일으키지 않는다.
- 스케줄러: gateway lifespan의 0.5초 tick, DB 행 잠금과 이벤트 unique 제약으로 중복을 막는다. 실제 발생 초와 `occurrence_mode=on_action|forced`를 `event_occurrences`, SSE `EVENT_FIRED`, 리포트 타임라인에 남긴다.
- 무응답: 요청 후 3분에 리마인드 1회, 추가 4분 뒤 다음 단계/기본 분업. E1 무응답의 CO-1·RS-3 유지. 턴은 기록과 행동 순서 근거에만 사용한다.
- 도구: `read_artifact`(실제 작업본 읽기), `edit_own_artifact`(요청된 서윤 담당 문서 즉시 수정), `suggest_candidate_edit`(실제로 읽은 지원자 문서의 검토 수정안, 승인 필요). 기존 승인 도구 이름을 교체했다. 승인 인자 바인딩·버전 충돌·mutation receipt·checkpoint interrupt/resume을 유지한다.
- own edit: 요청 대상 밖 변경·담당 밖 수정·브리프 모순을 차단한다. 같은 run 재실행은 기존 수정 이력을 반환한다. 지원자 검토 수정안에서 금액·날짜·수치를 바꿀 수 없다.
- 대상 추론: 표기 정규화 → 최근 지원자/서윤 대화 6개에서 지시 대상 찾기 → LLM 보완. LLM 대상은 서비스 인증 `/internal/v1/runs/{rid}/targets`에서 기록하고 관찰 근거에 `LLM 추정`을 표시한다.
- rag capability: 일반 대화·지원자 문서 검토에는 brief 검색/원문을 허용하지 않는다. 구체적인 지적이 있는 run에만 열람을 허용한다. 평소 생성 컨텍스트에서 `brief_facts`, planted 정답을 제거했다.
- 응답: 서윤은 페르소나+현 상황으로 생성하고 이벤트 script·팀장 follow_up은 고정한다. 출력 검사 실패 시 최대 2회 재생성한다. 같은 주제의 질문 이력은 세션 상태에 보존하고, 되묻기 반복, 행동 없는 약속, 먼저 답 공개, 새 시각, 평가 언급, 2문장 초과 등을 검사한다.
- 관찰: 독립 관찰 노드에서 의미 코드를 판정한다. 문서/보드 규칙은 저장된 행동 근거를 사용한다. CO+7(제출 전 검토 요청), CO·N2(반영/이유를 들어 유지/반응 없음)를 추가하고 회사 조항 검색 질의에도 연결했다. 사실 지적은 비난으로 기록하지 않는다.
- E3: 이탈 시 담당 T2/T3 버전·본문을 저장한다. 복귀 시 이탈 중 지원자 수정 부분을 구체적으로 언급하고, 수정이 없으면 기존 질문을 보낸다.
- 화면: 남은 시간 `mm:ss`와 10분 이하 강조, 메시지 경과 시간, 서윤 수정의 버전/이전→이후 표시, 자동 디브리핑 이동. 관리자 다음 이벤트는 다음 open 시각으로 시계를 이동한다.

## 임의 결정

1. 지정되지 않은 open/force: E1 10/13분, E2 23/26분, E3 35/38분, E3B 43/46분. E2B는 실제 E2 발생 후 5/8분, E4는 50/50분.
2. 분업 확정 전에도 기존 기본 분업을 보드의 임시 담당으로 표시한다. 따라서 협상을 생략하고 표 정정을 먼저 요청해도 서윤의 담당 문서를 즉시 고칠 수 있다. 협상 결과나 7분 기본 확정이 최종 담당을 정한다.
3. fixture는 결정적으로 응답하고 live는 LLM으로 생성한다. 이벤트 고정 대사는 두 모드에서 같다. E3B의 수정 인지는 실제 diff로 만드는 예외 문장이다.
4. 반복 질문을 이미 했고 안전한 재생성도 실패한 경우에는 행동을 약속하지 않는 짧은 확인 응답으로 마무리한다.
5. 기존 시연을 위해 별도 DB `dayzero_seoyoon`, 웹 3200, gateway 8100, agent 8101, business/rag/dayzero 9111/9112/9113을 사용했다. 기존 DB와 8000/8001 서비스는 재시작하지 않았다.
6. 기존 3100 웹은 개발 자동 반영을 막기 위해 원래 커밋의 `/private/tmp/dayzero-demo-refactor` worktree에서 실행하도록 고정했다. 기존 브랜치와 원격 커밋은 그대로 `567ac1f`이다. 새 키 파일은 만들지 않았다.

## 실행 상태·팀원 TODO

- 새 Agent는 live로 실행 중이다. 새 기능 확인: `http://localhost:3200/admin/login`. 기존 11시 시연: `http://localhost:3100/admin/login`.
- 실행 관리: `services/.venv/bin/python infra/seoyoon-dev.py up live` / `down`. shell의 OpenAI/LangSmith 키를 제거한 뒤 기존 `.env`를 메모리로 로드한다. 키·토큰은 출력하거나 증빙 파일에 저장하지 않는다.
- 팀원 TODO: 병합 후 공유 환경에서 `alembic upgrade head` → seed → 문서 색인 갱신 → 새 API 계약의 프런트와 서버 동시 배포. 승인 도구 이름을 사용하는 외부 클라이언트도 `suggest_candidate_edit`으로 변경한다.
- 기존 완료 리포트 JSON은 과거 스키마이므로 필요한 경우 새 계약으로 다시 생성한다. 원래 시연 DB에는 마이그레이션하지 않았다.
- 검증에서 남은 실패는 없다. 기존 시연 환경을 새 계약으로 전환하는 배포는 수행하지 않았다.

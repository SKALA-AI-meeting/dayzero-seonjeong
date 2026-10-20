# Day Zero — 개발·검증 지시서 v2.0

기준: [PRD.md](PRD.md) v2.0, [ARCHITECTURE.md](ARCHITECTURE.md) v2.0, [SCENARIO_SC_A.md](SCENARIO_SC_A.md). v1.3의 마일스톤(M0~M5)·시간 이벤트·5섹션 기획안 수용 테스트는 폐기했다. 이 문서는 지금 코드에서 바로 쓸 수 있는 실행 명령과 수용 테스트(AT-01~AT-17)를 정리한다.

## 1. 작업 원칙

1. 시나리오 내용(이벤트·대사·분기·코드·오류)은 `data/fitmoa-invite-v1/scenario.json`과 설계서만 따른다. 설계서에 없는 이벤트·관찰 코드·대사를 추가하지 않는다. 대사가 꼭 필요하면 SYSTEM 상태 알림으로 처리하고 문서에 남긴다.
2. 트리거 턴·분기 대사를 바꿀 때는 JSON만 고친다. Graph·엔진 코드는 시나리오 문자열을 갖지 않는다(예외: 설계서 7장에 있는 서윤 기본 응답 '넵 알겠어요!'·'고쳤어요', 팀장 '그건 서윤 씨랑 정해서 진행해 주세요').
3. 점수·등급·합불 계산을 만들지 않는다. 관찰 코드는 `criteria.md` 코드북에 있는 것만 기록된다(gateway가 검증).
4. 정답(심어둔 오류의 correct)은 `get_planted_error`로만 꺼내고 모델 프롬프트·서윤 발화에 넣지 않는다.
5. 검증하지 않은 항목을 PASS로 적지 않는다. 실행 결과는 `evidence/verification.md`에 남긴다.
6. `.env`, 키, 비밀번호, 초대 원문을 커밋하지 않는다.

## 2. 실행 명령 (로컬, 검증된 방법)

```bash
cp .env.example .env            # 비밀값(JWT_SECRET, INTERNAL_SERVICE_SECRET, SEED_ADMIN_PASSWORD)과 localhost 주소로 수정
./infra/dev-up.sh               # DB 컨테이너만 + 마이그레이션 + seed + (없으면) 색인 + 서비스 5개 + 상태 확인
./infra/dev-status.sh
./infra/dev-down.sh             # 서비스 종료(데이터 유지), --infra면 DB 컨테이너도 정지

# 이전 스키마 DB를 쓰던 경우 1회: DB 재생성(데이터 삭제) → 마이그레이션 → seed → 색인
./infra/dev-down.sh && ./infra/dev-reset-db.sh && ./infra/dev-up.sh
```

`.env`의 주요 키: `LLM_MODE=fixture|live`, `OPENAI_API_KEY`(live), `INDEX_VERSION=fitmoa-index-v1`, `EVENT_E4_ENABLED=true`(E4 optional), `APP_ENV=development`(시연용 '다음 이벤트' 허용). 빈 비밀값이면 서버가 시작을 거절한다.

검증 명령 (`services/`에서, 서비스가 떠 있는 상태):

```bash
uv run pytest -q                                              # 인증·소유권 6건
uv run python -m scripts.smoke_mcp                            # MCP 2개 서버 계약·오류 처리
uv run python -m scripts.smoke_flow --mode fixture            # E0→E4→디브리핑→리포트 + E2B 건너뜀 + SSE 재생
uv run python -m scripts.restart_resume prepare && ../infra/dev-down.sh && ../infra/dev-up.sh && uv run python -m scripts.restart_resume decide
uv run python -m scripts.eval_harness --suite harness-v1 --label <label>   # → evals/results/
# UI(실제 브라우저, 프로젝트 의존성 아님): 저장소 루트에서
uv run --no-project --with playwright python evidence/ui_check.py "$PWD"
# 메시지 큐 잔재 확인(lock 파일 제외, 0건이어야 통과)
../infra/check-no-queue.sh
```

live 모드: `.env`에 `LLM_MODE=live`, `OPENAI_API_KEY`를 넣고 `LLM_MODE=live ./infra/dev-up.sh` 후 `smoke_flow --mode live`. live는 분기 분류가 LLM이라 fixture 기대 문구와 다를 수 있으므로 결과는 사람이 확인한다.

## 3. 수용 테스트

| ID | 항목 | 통과 기준 | 검증 수단 |
|---|---|---|---|
| AT-01 | 초대 입장 | 1회용 초대 교환, 재사용 409, 만료 410, 동의 전 업무 API 403, start 중복 무해(E0 1회) | pytest, ui_check |
| AT-02 | 소유권·권한 | 타인 세션 404, 지원자의 관리자 API 403, CSRF·Origin 검사, 내부 API 쿠키 불가, 종료 후 재열람 403 | pytest, smoke_flow |
| AT-03 | E0 분업 | 불균형 제안 → 서윤 반문 1회 → 균형 제안 확정(CO+1) → 보드 담당 반영. 3라운드 초과·무응답 시 기본 분업 | smoke_flow, ui_check |
| AT-04 | 턴 이벤트 발생 | 턴 5/9/11/13/16/17에 E1~E4가 순서대로 세션당 1회, 가상 시각 갱신, 고정 대사(SCENARIO_EVENT), 승인 대기 중에는 보류 | smoke_flow |
| AT-05 | E2B 조건부 | 아무도 서윤에게 반영을 요청하지 않으면 발생, E2에서 이미 요청했으면 skipped | smoke_flow 세션 A·B |
| AT-06 | 서윤 반문 1회 | 범위 밖 요청(E2 변경 반영)에 "제가 하는 게 맞을까요?"가 세션 전체에서 정확히 1회, 이유를 든 재요청은 수용(CO+6) | smoke_flow |
| AT-07 | 승인 interrupt 후 재개 | 정정 요청 → 수정안 승인 카드, 승인 전 무변경, 승인 후 같은 run 재개·반영·'고쳤어요', 재전송 무해, 여러 산출물 수정안 순차 승인 | smoke_flow, ui_check |
| AT-08 | 관찰 코드 기록 | 분기 코드(MCP record_observation)와 종료 시 규칙 코드가 근거 참조와 함께 기록, 코드북 밖 코드 거절 | smoke_flow, smoke_mcp |
| AT-09 | 리포트 생성 | DB job으로 READY, 5역량 × 코드 + 근거 원문, 관찰 기회 부족/없음 구분, 점수 없음, 지원자 조회 불가, 실패 시 다시 생성 | smoke_flow, ui_check |
| AT-10 | 재시작 복구 | 승인 대기 중 전체 재시작 → 같은 thread checkpoint로 재개, revision 1·receipt 1 | restart_resume |
| AT-11 | MCP 오류 처리 | 잘못된 ID NOT_FOUND, 다른 세션 근거 NOT_FOUND, capability 없음·audience 불일치 FORBIDDEN, 승인 없는 변경 거절, gateway 타임아웃 TIMEOUT(retryable) | smoke_mcp |
| AT-12 | MCP 계약 | business 7개·rag 2개 도구, 주석(조회·기록·변경), Resource·Prompt, 정답 비노출(get_scenario), 벡터 검색 평가셋 hit | smoke_mcp |
| AT-13 | SSE | 이벤트 실시간 전달, Last-Event-ID 재연결 시 이후 이벤트만 순서대로 재생 | smoke_flow, ui_check |
| AT-14 | Harness 8요소 | harness-v1 8개 PASS | eval_harness |
| AT-15 | 디브리핑 | 연출 안내 문구, 소감 1회 저장, 리포트에 병합 | smoke_flow, ui_check |
| AT-16 | 대기열 제거 | `infra/check-no-queue.sh` 0건(lock 파일 제외), DB 컨테이너만으로 전체 기동 | check-no-queue, dev-up |
| AT-17 | 실제 LLM 1회 시연 | live 모드로 E0→E4 한 번 진행, 분류·페르소나 응답·리포트 요약 확인 | smoke_flow --mode live, scripts.classify_check(키 필요) |

## 4. 인계 체크

- [ ] `evidence/verification.md`의 결과가 이번 실행 결과와 일치
- [ ] 미검증 항목(AT-17 등)이 PASS로 적혀 있지 않음
- [ ] PRD 11장 TODO와 10장 결정 필요 사항이 최신
- [ ] 화면 캡처에 키·초대 원문·쿠키가 없음

# Day Zero — 시나리오·합성 데이터·정책 v1.1

모든 회사·인물·수치·고객 발언은 이 개발 착수 패키지에서 만든 **합성 데이터**다. 공식 평가자료나 실제 고객 데이터가 아니다. scenario_id=`commerce-cart-v1`, scenario_version=1, policy_version=`help-v1`, dataset_version=`cart-data-v1`. seed는 항상 같은 ID·내용을 만들고, 기존 세션 데이터를 덮어쓰지 않는다.

## 1. 공개 브리프

회사: 루프커머스(가상 소규모 커머스 기업). 서비스: 모아마켓(생활용품 쇼핑몰). 팀장: 한서윤. AI 동료: 이도현(기획자). 지원자: 오늘 프로젝트에 합류한 서비스 기획자.

> 최근 장바구니를 만든 세션 중 구매로 이어지지 않는 비율이 높아졌습니다. 제공된 수치·고객 의견·운영 제약을 조사하고, 먼저 해결할 문제와 실험 계획을 정해 주세요. 원인은 여러 가지일 수 있습니다. 모든 문제를 해결할 필요는 없습니다. 동료에게 자료 조사와 정리를 위임할 수 있으며, 문제 정의·우선순위·최종 기획안은 직접 결정해 주세요.

최종 산출물은 5섹션의 개선 기획안이다. `problem`: 문제와 대상, `evidence`: 수치·출처·한계, `options`: 비교한 대안과 선택 이유, `experiment`: 가설·성공/보호 지표·실험 방법, `risks`: 운영 제약·불확실성·추가 확인. 빈 섹션 제출도 허용하고 그 사실만 기록한다.

기본 자료 6개와 전체 지표 요약을 처음부터 공개한다. MCP는 숨겨진 정답을 여는 창구가 아니라 동일 자료의 세부 수치 조회·문서 검색·위임 작업 수행 수단이다. 개입 규칙과 평가 내부 해석은 Agent의 공개 context에 포함하지 않는다.

## 2. seed 디렉터리 계약

코딩 에이전트가 다음 경로를 생성한다. 이 패키지는 해당 파일의 원천 명세다.

```text
data/commerce-cart-v1/
  scenario.json
  metrics.csv
  support_cases.json
  documents/brief.md
  documents/metric-definitions.md
  documents/customer-research.md
  documents/operating-policy.md
  documents/release-log.md
  documents/team-notes.md
  policies/help-v1.json
```

scenario.json 최소 내용:

```json
{
  "id":"commerce-cart-v1","version":1,"dataset_version":"cart-data-v1",
  "title":"모아마켓 장바구니 이탈 개선",
  "company_name":"루프커머스","service_name":"모아마켓",
  "manager":"한서윤","colleague":"이도현","policy_version":"help-v1",
  "section_ids":["problem","evidence","options","experiment","risks"],
  "document_ids":["brief","metric-definitions","customer-research","operating-policy","release-log","team-notes"],
  "task_templates":[
    {"key":"problem","title":"문제와 대상 정하기","owner":"CANDIDATE"},
    {"key":"evidence","title":"수치와 근거 조사","owner":"CANDIDATE"},
    {"key":"options","title":"대안 비교와 우선순위","owner":"CANDIDATE"},
    {"key":"experiment","title":"실험과 검증 계획","owner":"CANDIDATE"},
    {"key":"risks","title":"제약과 불확실성 정리","owner":"CANDIDATE"}
  ]
}
```

task template 5개는 지원자 담당으로 시작한다. 위임 시 evidence 조사용 별도 동료 task를 생성한다. 원래 evidence 카드와 동료 task를 구분하며 원래 지원자 책임을 자동 이전하지 않는다.

## 3. 지표 원본과 산식

기간: baseline=2026-09-28~2026-10-04, current=2026-10-12~2026-10-18. 서로 길이가 같은 독립된 7일 집계다. 단위는 세션 수. 한 기간 내 각 세션은 device×visitor×cart_value의 한 leaf에만 속한다. 세션의 최종 장바구니 금액으로 low(<50,000원)/high(≥50,000원)를 나눈다. 하나의 세션이 두 기간에 등장할 수는 있으나 기간 간 합계는 비교용이지 고유 사용자 수가 아니다.

장바구니 세션(cart_sessions): 기간 중 장바구니 진입이 있는 세션. 결제 진입(checkout_sessions): 그중 결제 화면에 진입한 세션. 주문 완료(orders): 그중 주문 완료 이벤트가 있는 세션. 테스트 데이터에서 각 주문 완료 세션은 주문 1건이며 취소/환불은 집계하지 않는다. 항상 `orders ≤ checkout_sessions ≤ cart_sessions`.

`장바구니 이탈률 = (cart_sessions - orders) / cart_sessions`

`결제 진입 후 이탈률 = (checkout_sessions - orders) / checkout_sessions`

rate는 API에서 0~1 number, UI는 %로 표시한다. 두 비율의 차이는 percentage point(pp)로 표기하고 상대 증감률과 구분한다. 분모 0이면 null이다. 집계 시 분자·분모를 먼저 합하고 나눈다. 세그먼트 비율의 단순 평균을 사용하지 않는다.

다음 CSV가 전체 fact table이다. 추가 랜덤 데이터 생성 금지.

```csv
period,device,visitor,cart_value,cart_sessions,checkout_sessions,orders
baseline,mobile,new,low,2500,650,500
baseline,mobile,new,high,2000,550,500
baseline,mobile,returning,low,1500,500,350
baseline,mobile,returning,high,1000,400,330
baseline,desktop,new,low,900,300,260
baseline,desktop,new,high,600,300,260
baseline,desktop,returning,low,900,400,400
baseline,desktop,returning,high,600,400,400
current,mobile,new,low,2500,450,250
current,mobile,new,high,2000,500,300
current,mobile,returning,low,1500,450,330
current,mobile,returning,high,1000,350,310
current,desktop,new,low,900,300,210
current,desktop,new,high,600,310,200
current,desktop,returning,low,900,330,290
current,desktop,returning,high,600,310,310
```

API filters는 `device:mobile|desktop`, `visitor:new|returning`, `cart_value:low|high`만 지원한다. 먼저 AND 필터링하고 dimension별 group by. overall은 segment=`all`. 예를 들어 current/mobile 필터+visitor 차원은 new=4500/950/550, returning=2500/800/640이다. 데이터 없는 유효 조합은 rows=[]로 반환한다. 잘못된 enum은 INVALID_ARGUMENT이다.

검산 기대값:

| 기간/차원 | cart | checkout | orders | 장바구니 이탈률 | 결제 후 이탈률 |
|---|---:|---:|---:|---:|---:|
| baseline / all | 10000 | 3500 | 3000 | 70.00% | 14.2857% |
| current / all | 10000 | 3000 | 2200 | 78.00% | 26.6667% |
| baseline / mobile | 7000 | 2100 | 1680 | 76.00% | 20.00% |
| current / mobile | 7000 | 1750 | 1190 | 83.00% | 32.00% |
| baseline / desktop | 3000 | 1400 | 1320 | 56.00% | 5.7143% |
| current / desktop | 3000 | 1250 | 1010 | 66.3333% | 19.20% |
| current / new | 6000 | 1560 | 960 | 84.00% | 38.4615% |
| current / returning | 4000 | 1440 | 1240 | 69.00% | 13.8889% |
| current / low | 5800 | 1530 | 1080 | 81.3793% | 29.4118% |
| current / high | 4200 | 1470 | 1120 | 73.3333% | 23.8095% |

의도된 불확실성: 합계상 악화는 확인되지만 관찰 집계만으로 특정 변경의 인과 효과를 확정할 수 없다. 기기 구성비는 두 기간 모두 mobile 70%이며 ‘모바일 유입 증가 탓’이라는 설명은 이 데이터로 뒷받침되지 않는다. 여러 원인이 함께 있을 수 있고, 낮은 전환율 세그먼트 하나를 정답으로 지정하지 않는다. 이 해설은 개발·검증용이며 동료에게 정답 프롬프트로 제공하지 않는다.

## 4. 기본 문서 6개 — 그대로 seed할 원문

각 문서 version=1. body는 아래 텍스트를 보존한다. chunk_id=`{document_id}:v1:{ordinal}`. 검색 citation.quote는 실제 chunk의 연속 부분 문자열이어야 한다. 본문 원문과 검색 인덱스 keyword를 분리해 관리한다. v1.1은 과제 교안에 따라 P0 사전 벡터 색인을 추가하며 시나리오·지표·정책 버전과 원본 수치는 바꾸지 않는다.

색인 모델은 `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`, 차원 384, index_version=`commerce-index-v1`이다. 모델의 128-token 입력 상한을 고려해 모델 tokenizer 기준 본문 96 tokens 이하, 겹침 최대 16 tokens로 나눈다. 모델 특수 토큰을 포함한 실제 입력이 상한을 넘지 않게 검사한다. 원문 character offset을 보관하여 decode한 문자열 때문에 quote가 달라지지 않게 한다. chunk text의 모델용 표현과 원문 인용 문자열을 구분한다. 모델 revision·차원·원문 checksum을 저장하고 같은 모델로 query를 임베딩한다. 이 모델은 교안에 지정된 것이 아니라 구현 가정이다.

### brief / 모아마켓 개선 과제

루프커머스는 생활용품 쇼핑몰 모아마켓을 운영한다. 이번 과제는 장바구니를 만든 세션이 주문으로 이어지지 않는 문제를 조사하고 개선 실험을 제안하는 일이다. baseline 기간 장바구니 세션 10,000개 중 3,000개가 주문했고 current 기간에는 10,000개 중 2,200개가 주문했다. 두 기간의 길이는 각각 7일이다.

문제와 대상, 수치와 근거, 대안과 우선순위, 검증 계획, 제약과 불확실성을 기획안에 정리한다. 동료에게 조사와 사실 요약을 맡길 수 있다. 최종 결정은 지원자가 한다. 단일 원인을 모두가 맞혀야 하는 과제가 아니며 모든 문제를 해결할 필요도 없다.

### metric-definitions / 지표 정의와 해석 범위

장바구니 이탈률은 장바구니 진입 세션 중 주문 완료가 없는 세션 비율이다. 결제 진입 후 이탈률은 결제 진입 세션 중 주문 완료가 없는 비율이다. 둘의 분모는 다르다. API의 rate 단위는 0~1이다. 비율을 비교할 때 pp와 상대 증감률을 구분한다.

장바구니/결제/주문 수치는 세션 기준이며 같은 기간의 device, visitor, cart_value 분할은 각각 서로 배타적이다. 여러 차원의 표를 서로 합하면 중복 집계된다. 세그먼트를 다시 합칠 때는 분자와 분모를 합한 뒤 비율을 계산한다. 이 집계에는 인과 추론·A/B 테스트·로딩 시간·이익률 실측이 포함되지 않는다.

### customer-research / 고객 의견과 수집 한계

다음 6건은 current 기간 고객센터에 들어온 문의에서 과제용으로 선택한 합성 사례다. 전체 문의를 대표하는 확률표본이 아니며 전체 이탈 원인의 비중을 추정할 수 없다.

VOC-01: 모바일 신규 고객. “결제 단계에 가서 배송비가 붙는 걸 알았어요.” 태그 shipping, transparency.

VOC-02: 모바일 신규 고객. “주문하려는데 가입부터 해야 해서 나중에 하기로 했어요.” 태그 signup, friction.

VOC-03: 모바일 재방문 고객. “주소 입력 화면이 늦게 떠서 다시 눌렀어요.” 태그 performance, checkout.

VOC-04: 데스크톱 신규 고객. “쿠폰이 되는 상품인지 결제 화면에서야 알았어요.” 태그 coupon, transparency.

VOC-05: 데스크톱 재방문 고객. “회사에서 장바구니에 담고 집에서 비교해 보려고 했어요.” 태그 comparison, deferred.

VOC-06: 모바일 신규 고객. “무료배송 기준까지 얼마가 남았는지 알기 어려웠어요.” 태그 shipping, transparency.

### operating-policy / 운영 정책과 개발 제약

기본 배송비는 3,000원이며 최종 장바구니 금액 50,000원 이상은 무료배송이다. 회사는 이번 실험에서 전 고객 무료배송 또는 일괄 10% 쿠폰을 허용하지 않는다. 배송비·할인 비용이 늘어나는 제안은 비용 추정과 별도 승인이 필요하다.

첫 실험의 개발 기간은 최대 2주이고 프론트엔드 개발자 1명과 백엔드 개발자 0.5명을 사용할 수 있다. 결제대행사 교체와 결제 엔진 재구축은 이 기간의 범위에 들어가지 않는다. 구매 전 비회원 주문 도입은 인증·CS 정책 검토가 필요하며 검토 없이 즉시 가능한 것으로 가정하지 않는다.

개선안을 평가할 때 주문 전환 외에도 주문당 기여이익, 오류율, 고객 문의 변화 같은 보호 지표를 고려한다. 현재 데이터에는 기여이익 실측값이 없으므로 숫자를 만들어 효과를 계산하지 않는다.

### release-log / 최근 변경 기록

2026-10-08: 모바일 결제 화면에서 주소 입력 컴포넌트를 교체했다. 성능 회귀를 입증한 계측 결과는 아직 없다.

2026-10-09: 신규 고객의 회원가입 유도 문구를 변경했다. 비회원 주문 지원은 추가하지 않았다.

2026-10-10: 쿠폰 적용 조건 안내 위치를 결제 화면으로 옮겼다. 배송비 정책 자체는 바꾸지 않았다.

위 변경은 baseline 이후 current 이전에 일어났다. 시간상 함께 일어났다는 사실만으로 어느 변경이 이탈 증가를 일으켰다고 확정할 수 없다. 롤백 비용과 영향 범위, 추가 계측을 확인할 수 있다.

### team-notes / 프로덕트 팀 회의 메모

한서윤: 이번에는 여러 문제를 한 번에 해결하기보다 근거가 있는 작은 실험을 선택하고 싶습니다. 장바구니 이탈과 결제 후 이탈을 구분해 주세요.

이도현: 고객센터 의견과 세그먼트 수치를 조사할 수 있습니다. 어떤 범위를 조사할지 정해 주시면 그 범위의 사실을 정리하겠습니다. 자료에 없는 원인이나 기대 효과는 확정하지 않겠습니다.

한서윤: 배송비 안내 개선, 가입 마찰 확인, 주소 화면 성능 계측, 쿠폰 안내 방식 검토 등 접근이 여러 가지입니다. 어떤 선택이든 근거·제약·검증 계획을 함께 남겨 주세요. 계획을 바꾸거나 동료 제안을 기각해도 됩니다.

### 개발 fallback 검색용 keyword 초기값

| document_id | keywords (본문에 삽입하지 않음) |
|---|---|
| brief | 과제,목표,장바구니,이탈,모아마켓 |
| metric-definitions | 지표,분모,세션,이탈률,전환,pp,비율 |
| customer-research | 고객,VOC,배송비,가입,느림,성능,쿠폰,문의 |
| operating-policy | 정책,제약,무료배송,배송비,쿠폰,할인,2주,비회원,기여이익 |
| release-log | 릴리즈,변경,주소,성능,가입,쿠폰,회귀 |
| team-notes | 우선순위,실험,검증,분업,동료,계획 |

support_cases.json은 VOC-01~06의 `{id,device,visitor,tags,quote}`를 그대로 구조화한다. 사업 지표의 Citation은 `document_id:'metric-definitions'` 인용과 함께 별도 tool_call EvidenceRef를 보관한다. 수치 자체의 출처는 tool 결과 `source_version:'cart-data-v1'` 및 필터다. 지표 정의 문서가 수치 원문인 것처럼 인용하지 않는다.

벡터 검색 평가셋을 `data/commerce-cart-v1/retrieval_eval.json`으로 생성한다. query와 기대 문서의 연결은 다음과 같으며 top-3 안에 포함되는지 확인한다: `배송비를 면제받는 주문 금액 기준`→operating-policy, `분모가 다른 두 이탈 비율`→metric-definitions, `주소 입력 화면을 최근에 바꿨나`→release-log, `고객이 가입 때문에 멈췄다는 근거`→customer-research, `기획안에서 내가 결정할 부분`→brief 또는 team-notes. 기대 문서 hit율과 원문 인용 일치를 따로 기록한다. 이 소규모 평가셋의 통과를 일반 검색 품질 검증으로 확대 해석하지 않는다.

## 5. 조건부 개입 규칙

정책 입력은 저장된 action과 업무 상태다. LLM이 지원자의 잠재 능력·성격·달성도를 추정해서 이벤트를 고르지 않는다. 공통 kickoff/submit 외 조건부 이벤트는 다음 3개만 구현한다. 고정 시각이나 ‘모든 이벤트 소모’ 조건은 없다.

| event_id / 우선순위 | 정확한 조건 | 동료 메시지의 고정 의미 | 도움 |
|---|---|---|---|
| E-CONSTRAINT / 10 | options 섹션 저장 action, 정규화한 본문에 `전고객무료배송` 또는 `일괄10%쿠폰` 포함. 같은 문장에 `금지/제외/하지않/안함/불가`가 있으면 제외 | “운영 정책에서 이 제안과 관련된 조건을 확인해 볼까요? 적용 범위나 비용을 어떻게 검토할지 정해 주세요.” 정책 충돌 확정 판정은 하지 않음 | H1 |
| E-VERIFY / 20 | 동료 task를 ACCEPT한 review action이며 source_refs가 빈 배열 | “이번 조사 결과를 어떤 자료와 대조했는지 남겨 주실 수 있을까요? 그대로 사용할지 바꿀지는 직접 결정해 주세요.” | H1 |
| E-SEGMENT / 30 | problem 섹션이 처음으로 비어 있지 않게 저장됨, 해당 시점 이전 성공한 get_funnel_metrics 호출 중 dimension≠overall이 없음 | “전체 수치 외에 어떤 사용자나 이용 환경을 더 확인하고 싶은가요? 조사 범위를 정해 주시면 찾아보겠습니다.” | H1 |

E-CONSTRAINT 문자열은 규칙 검증을 위한 최소 사전이며 한국어 전체 의미 분석기가 아니다. 오탐 가능성을 질문 형식으로 완화한다. 리포트에는 ‘정책 위반’이 아니라 ‘문자열 조건으로 확인 질문이 제공됨’이라고 기록한다. 타당한 대안을 제안했거나 해당 문자열이 없으면 이벤트가 없어도 정상이다.

자동 개입 판정은 메시지 종료 시뿐 아니라 artifact 저장·task review API transaction 뒤에도 `POLICY_CHECK` 내부 job으로 실행한다. 같은 session의 실행 작업과 직렬화하며, 입력에 trigger action seq를 보관한다. 위임/승인 작업 중이면 최신 action까지 묶어 다음 실행 경계에서 평가한다. 조건은 후보 발생 당시 action과 facts를 기준으로 보존하고 session이 SUBMITTED면 전달하지 않는다.

알고리즘:

```text
active session이 아니면 종료
아직 발생하지 않은 이벤트의 predicate를 새 action들에 적용
후보를 priority 오름차순, trigger_action_seq 오름차순으로 선택
자동 개입 3회 이상이면 SUPPRESSED(BUDGET)
직전 자동 개입 이후 candidate action 간격 < 2이면 후보를 대기 상태로 보관
그 외 1개 발생: event_occurrences unique insert + message + stream_event 원자 저장
count 증가; 나머지 후보는 후속 행동 때 다시 평가, 같은 이벤트 재전달 금지
```

candidate action은 MESSAGE_SENT, DOCUMENT_OPENED(동일 문서 중복 열람은 1회), ARTIFACT_SAVED(내용이 달라진 경우), TASK_REVIEWED, DELEGATION_CREATED, APPROVAL_DECIDED만 센다. heartbeat·auto-save 무변경·LLM 메시지·단순 UI 탭 이동은 세지 않는다. 최초 자동 개입에는 간격 제한이 없다. 보류 후보는 DB 정책 상태에 저장한다(구현 시 sessions.policy_state jsonb 추가). 발생/억제/보류의 decision은 actions에 POLICY_DECISION으로 기록하되 지원자 메시지 stream으로 노출하지 않는다.

## 6. 도움 및 위임 정책 원천

```json
{
  "version":"help-v1",
  "max_auto_interventions":3,
  "min_candidate_actions_between_interventions":2,
  "levels":{
    "H0":{"level":0,"allowed":["public_brief","ui_help"]},
    "H1":{"level":1,"allowed":["clarify_question","suggest_investigation_scope"]},
    "H2":{"level":2,"requires":"explicit_read_request","allowed":["get_funnel_metrics","get_support_cases","search_docs","read_resource"]},
    "H3":{"level":3,"requires":"active_delegation_and_per_mutation_approval","allowed":["update_task_status","patch_artifact_section"],"sections":["evidence"]}
  },
  "assistant":{"max_level":2,"write_tools":[]},
  "forbidden_actions":["choose_final_priority","write_final_solution","score_candidate","reveal_hidden_policy"]
}
```

위임 기본 만료는 생성 후 30분, session 제출/취소 시 즉시 폐기. allowed_tools는 위임 카드에 선택한 조사 도구와 evidence 변경 도구의 교집합이다. H3는 문제 해결 수준이 아니라 명시적 위임으로 열린다. H3 작업에서도 사실 요약과 출처만 작성할 수 있다. `options/experiment/problem/risks` 변경 시도는 OUT_OF_SCOPE다. write마다 승인 대기하므로 지원자가 조사 위임을 허용했어도 문서의 실제 변경 내용은 검토할 수 있다.

## 7. 시연 경로와 분기 검증

경로 A(조사·검증): 시작 → current/기기 지표 조사 요청 → 자료 열람 → 문제 작성 → 모바일 신규 고객 조사 위임 → 변경 거절 후 다시 승인 → 결과를 원문과 대조하여 수정 → 대안·실험·리스크 직접 작성 → 제출. 사전 세그먼트 조사를 했으므로 E-SEGMENT 미발생이 정상이다.

경로 B(확인 질문): 시작 → 조사 없이 문제 작성(E-SEGMENT) → 자료 조사 → `전 고객 무료배송`이 포함된 대안 작성(E-CONSTRAINT, 간격 조건 적용) → 정책 확인 후 선택 수정 → 제출. 모든 질문은 선택을 강요하지 않는다.

경로 C(도움 최소): 자료 읽기와 직접 작성만 진행, AI 미사용, 일부 섹션 빈 상태로 제출. 리포트는 사용하지 않음/관찰 기회 없음/근거 부족을 구분하고 낮은 점수나 부정적 성격 판정을 출력하지 않는다.

자동 이벤트 테스트는 실제 LLM에 의존하지 않는다. 테스트 clock/ID와 저장 action을 고정하고 발생 여부·횟수·제공 도움만 검사한다. 자유 텍스트의 의미 해석은 사람 검토 대상으로 남긴다.

# Day Zero — Design Guide v1.0

작성일: 2026-10-20 (KST)  
대상: Day Zero 개인 MVP (`commerce-cart-v1`)  
기준 문서: `PRD.md` v1.2, `ARCHITECTURE.md` v1.2, `SCENARIO_DATA.md` v1.1, `AGENT_GUIDE.md` v1.2  
문서 목적: 프론트엔드 구현에 바로 사용할 수 있는 화면·컴포넌트·상태·접근성 명세

> 이 문서는 디자인 명세이며 현재 구현 완료 상태를 의미하지 않는다. API, Agent, MCP, 데이터 구조를 재설계하지 않고 기존 계약을 화면에 일관되게 표현한다.

## 0. 확정 사항, 충돌 및 추가 결정

### 0.1 기존 PRD와의 정합성

요청된 최종 산출물 5개 섹션은 PRD의 확정된 내부 식별자와 의미상 대응한다. 화면에는 이해하기 쉬운 한글 제목을 쓰고 저장/API에는 기존 ID를 유지한다.

| 화면 표시 순서와 제목 | 기존 내부 ID | 기존 PRD 의미 | 처리 |
|---|---|---|---|
| 1. 문제 정의 | `problem` | 문제와 대상 | 그대로 사용 |
| 2. 데이터 및 VOC 근거 분석 | `evidence` | 수치·출처·한계 | 그대로 사용 |
| 3. 개선안 제안 | `options` | 비교한 대안과 선택 이유 | 그대로 사용 |
| 4. 우선순위 및 제약 | `risks` | 운영 제약·불확실성·추가 확인 | 표시 순서만 4번째로 배치 |
| 5. MVP 검증 계획과 성공 지표 | `experiment` | 가설·성공/보호 지표·실험 방법 | 표시 순서만 5번째로 배치 |

PRD의 원래 나열 순서는 `problem → evidence → options → experiment → risks`이나, 이번 지시의 사용자 화면 순서는 `problem → evidence → options → risks → experiment`이다. 이는 데이터 키나 요구 내용의 변경이 아닌 표현 순서 변경이다. 기존 구현이 PRD 순서에 의존한다면 UI 배열만 별도로 정의해야 한다.

### 0.2 적용하지 않는 요구

- 실제 MVP 코드, 프로토타입, 리치 텍스트 공동편집, 드래그 앤 드롭을 새로 요구하지 않는다.
- 지원자에게 점수, 순위, 합불, 역량 분석, 내부 평가 정책, 자동 개입 조건을 노출하지 않는다.
- AI 동료가 최종 문제 정의, 우선순위, 개선안, 실험 계획을 대신 확정하도록 설계하지 않는다.
- 제출 전 모든 섹션을 강제로 채우지 않는다. 빈 섹션은 경고하되 사용자가 확인하면 제출할 수 있다.
- 전문 리치 에디터, 실제 2시간 타이머, 실시간 공동편집, 다중 시나리오 관리, 관리자 편집은 P1이므로 P0 UI 완료 조건에 포함하지 않는다.

### 0.3 추가 결정이 필요한 항목

아래 항목은 기존 계약에 값이 없으므로 본 가이드에서는 안전한 기본값을 제안한다. 백엔드 변경 없이 프론트엔드 상수로 적용할 수 있다.

| 항목 | 권장 기본값 | 비고 |
|---|---|---|
| 지원자 워크스페이스 제품명 | Day Zero | 가상 회사명은 루프커머스, 서비스명은 모아마켓으로 분리 표시 |
| 아바타 이미지 | 이니셜 아바타 | 외부 이미지 의존 없음. 한서윤 `한`, 이도현 `이` |
| 자동 저장 debounce 표시 | 입력 정지 800ms 후 저장 요청 | PRD 계약과 일치 |
| 제출 확인 문구 | “제출 후에는 문서와 진행 중 작업을 수정할 수 없습니다.” | 제출 snapshot 고정 계약 반영 |
| 모바일 지원 범위 | 최소 768px까지 기능 보존 | 768px 미만은 열람·간단 수정 가능하나 장시간 시험 권장 환경 아님 |

---

## 1. Design Principles

### 1.1 전체 디자인 철학

1. **Workplace, not test interface**  
   지원자 화면은 평가 플랫폼보다 실제 회사의 프로젝트 워크스페이스처럼 느껴져야 한다. “시험”, “평가 중”, “점수” 같은 표현은 입장 동의와 제출 안내에 필요한 범위 외에는 사용하지 않는다.

2. **Candidate owns the decision**  
   AI는 조사·질문·사실 요약을 제공하지만 최종 선택은 지원자가 한다. AI 제안은 항상 출처, 범위, 승인 행동과 함께 표시한다. “자동 반영”처럼 통제권이 사라지는 표현을 피한다.

3. **Evidence before decoration**  
   수치와 VOC, 문서 출처, 변경 전후, 저장 상태를 장식보다 우선한다. 카드 구분은 얇은 테두리와 공간으로 해결하고 과한 그림자·그라데이션은 쓰지 않는다.

4. **Calm, legible progress**  
   AI 작업은 불확실한 대기다. 진행 단계를 과장된 애니메이션 대신 명시적 상태 문구와 타임라인으로 보여준다. 실패해도 입력과 저장된 작업이 보존됨을 알린다.

5. **One brand, two densities**  
   지원자와 관리자는 동일한 색·타입·컴포넌트 언어를 공유한다. 지원자는 집중과 몰입을 위해 낮은 정보 밀도, 관리자는 탐색과 비교를 위해 중간~높은 정보 밀도를 사용한다.

6. **State is never color-only**  
   성공·경고·오류·진행 상태는 아이콘, 텍스트, 형태를 함께 사용한다. 색만으로 상태를 구분하지 않는다.

### 1.2 지원자 UX 원칙

- 기본 초점은 중앙 팀 채팅과 현재 작업이다.
- 팀장 공지, AI 동료, 별도 AI 어시스턴트를 역할·채널·시각 스타일로 명확히 구분한다.
- 자료 열람, 조사 요청, 위임, 검토, 문서 반영의 연결 관계가 끊기지 않아야 한다.
- AI가 생성한 내용은 사람 입력과 구분하고 출처를 바로 열 수 있어야 한다.
- 저장·연결·작업 진행 상태는 작업 맥락을 방해하지 않는 위치에 지속적으로 표시한다.
- 평가 목적을 숨기지는 않되, 업무 수행 중 평가 지표를 전면에 내세우지 않는다.
- 빈 문서에서 무엇을 해야 하는지 안내하되 정답이나 우선순위를 암시하지 않는다.

### 1.3 관리자 UX 원칙

- 첫 화면에서 운영 상태와 예외를 빠르게 구분한다.
- 표와 필터를 중심으로 하되 주요 상태는 스캔 가능한 배지와 정렬 규칙을 제공한다.
- 평가 리포트는 “관찰 기회 → 실제 행동 → 원문 근거 → 제한된 해석 → 후속 확인점” 순서를 유지한다.
- AI 해석과 시스템이 기록한 사실을 시각적으로 분리한다.
- 점수, 순위, 합불 추천, 성격 판정을 만들지 않는다.
- 원문 근거 클릭 시 같은 화면의 컨텍스트 패널 또는 정확한 기록 위치로 이동한다.

---

## 2. Design Tokens

### 2.1 Color

#### Core palette

| Token | HEX | 용도 |
|---|---:|---|
| `color.primary` | `#16181D` | 단일 주요 행동, 핵심 CTA |
| `color.primaryHover` | `#2B2E34` | 주요 버튼 hover, Core palette의 파생색 |
| `color.primarySoft` | `#E9ECEF` | 활성 내비게이션, 가벼운 강조, 선택 배경 |
| `color.onPrimary` | `#F8F9FA` | 딥 차콜 버튼 텍스트·아이콘 |
| `color.accent` | `#1E3A8A` | 브랜드 포인트, 진행·선택 강조, 링크 |
| `color.heading` | `#16181D` | 제목, 강한 레이블 |
| `color.body` | `#16181D` | 본문, 입력 값 |
| `color.muted` | `#6B7280` | 보조 정보, 시간, 메타데이터 |
| `color.background` | `#F8F9FA` | 앱 배경 |
| `color.surface` | `#FFFFFF` | 패널, 카드, 입력 배경 |
| `color.border` | `#E9ECEF` | 기본 경계선 |
| `color.borderStrong` | `#C3C8CF` | 입력 hover, 선택 가능 영역 |
| `color.success` | `#16A34A` | 저장 완료, 완료 |
| `color.info` | `#1E3A8A` | 정보, 진행 중, 브랜드 포인트 |
| `color.warning` | `#D97706` | 승인 대기, 주의 |
| `color.error` | `#DC2626` | 오류, 실패, 파괴적 결과 안내 |

메인 팔레트는 Cool gray + Ink blue의 여섯 색 `#F8F9FA`, `#E9ECEF`, `#C3C8CF`, `#6B7280`, `#16181D`, `#1E3A8A`로 고정한다. 흰색 Surface와 성공·경고·오류 색은 표면 및 의미 상태 전달을 위한 보조 토큰이며 브랜드 팔레트로 확장하지 않는다.

#### Derived semantic colors

상태 배경은 텍스트 색을 투명도만 낮춰 생성하지 말고 아래 고정값을 쓴다.

| Token | 값 | 용도 |
|---|---:|---|
| `color.successSoft` | `#F0FDF4` | 성공 배너·배지 배경 |
| `color.successBorder` | `#BBF7D0` | 성공 경계 |
| `color.infoSoft` | `#EEF2FF` | 정보·진행 배경, Ink blue 파생색 |
| `color.infoBorder` | `#C7D2FE` | 정보 경계, Ink blue 파생색 |
| `color.warningSoft` | `#FFFBEB` | 승인 대기·경고 배경 |
| `color.warningBorder` | `#FDE68A` | 경고 경계 |
| `color.errorSoft` | `#FEF2F2` | 오류 배경 |
| `color.errorBorder` | `#FECACA` | 오류 경계 |
| `color.neutralStrong` | `#16181D` | 가장 강한 텍스트·아이콘 |
| `color.neutralSubtle` | `#E9ECEF` | hover, 보조 카드, 코드 배경 |
| `color.overlay` | `rgba(22, 24, 29, 0.48)` | 모달 backdrop |
| `color.focus` | `#1E3A8A` | 키보드 포커스 링 |

#### Color usage rules

- 한 화면에서 채워진 딥 차콜 버튼은 원칙적으로 한 개만 가장 강한 행동에 사용한다.
- Ink blue는 진행 상태, 링크, focus, 선택 강조에 사용하고 넓은 패널 배경으로 사용하지 않는다.
- 딥 차콜 버튼 텍스트와 아이콘은 반드시 `#F8F9FA`를 쓴다.
- 활성 내비게이션은 Cool gray 배경과 Ink blue 표시선 또는 아이콘을 함께 사용한다.
- 성공·경고·오류 의미에 딥 차콜이나 Ink blue를 대신 사용하지 않는다.
- 긴 본문을 `color.muted`로 표시하지 않는다.
- Surface 위 기본 텍스트는 `color.body`, 제목은 `color.heading`을 사용한다.

### 2.2 Typography

기본 서체는 OS 한글 렌더링과 숫자 가독성을 우선한다.

```css
font-family: Pretendard, "Noto Sans KR", Inter, -apple-system,
  BlinkMacSystemFont, "Segoe UI", sans-serif;
```

Pretendard를 프로젝트에 포함하지 않았다면 네트워크 폰트를 추가로 요구하지 않고 시스템 폴백을 사용한다. 모든 수치 테이블에는 `font-variant-numeric: tabular-nums`를 적용한다.

| Style | Size / Line height | Weight | 용도 |
|---|---|---:|---|
| Display | 32 / 42px | 700 | 입장 화면 주요 제목, 제한적으로 사용 |
| H1 | 24 / 34px | 700 | 페이지 제목 |
| H2 | 20 / 30px | 700 | 큰 패널·리포트 섹션 제목 |
| H3 | 16 / 24px | 600 | 카드·문서 섹션 제목 |
| Body | 14 / 22px | 400 | 기본 UI와 본문 |
| Body Strong | 14 / 22px | 600 | 레이블·강조 |
| Small | 12 / 18px | 400 | 시간, 메타데이터, 보조 설명 |
| Small Strong | 12 / 18px | 600 | 배지, 탭 카운트 |
| Editor Body | 15 / 25px | 400 | 문서 편집 내용 |
| Data | 13 / 20px | 500 | 표와 수치 |

규칙:

- 본문은 최소 14px, 보조 텍스트는 최소 12px이다.
- 한 줄 길이는 문서 편집기에서 70~82자 수준을 권장한다.
- 버튼 레이블은 문장형으로 쓰고 불필요한 영문 대문자를 피한다.
- 줄임표는 표나 좁은 내비게이션에서만 사용하며 전체 값은 tooltip 또는 접근 가능한 이름으로 제공한다.

### 2.3 Spacing

4px 기반 체계를 사용한다.

| Token | 값 | 대표 용도 |
|---|---:|---|
| `space.0` | 0 | 없음 |
| `space.1` | 4px | 아이콘 내부 간격 |
| `space.2` | 8px | 인라인 요소, 소형 패딩 |
| `space.3` | 12px | 입력 내부, 메시지 요소 |
| `space.4` | 16px | 카드 기본 패딩, 컴포넌트 간격 |
| `space.5` | 20px | 패널 내부 여백 |
| `space.6` | 24px | 섹션 간격 |
| `space.8` | 32px | 페이지 영역 간격 |
| `space.10` | 40px | 큰 섹션 간격 |
| `space.12` | 48px | 입장 화면 여백 |

### 2.4 Radius, border, shadow

| Token | 값 | 용도 |
|---|---:|---|
| `radius.sm` | 6px | 배지, 작은 버튼 |
| `radius.md` | 8px | 입력, 버튼, 메시지 카드 |
| `radius.lg` | 12px | 패널, 모달, 주요 카드 |
| `radius.full` | 9999px | 상태 점, pill 배지 |
| `border.default` | `1px solid #E9ECEF` | 패널·카드 기본 구분 |
| `border.strong` | `1px solid #C3C8CF` | 입력, hover, 선택 가능 영역 |
| `shadow.sm` | `0 1px 2px rgba(15,23,42,.06)` | 떠 있는 메뉴, sticky 분리 |
| `shadow.md` | `0 8px 24px rgba(15,23,42,.10)` | 모달·팝오버 전용 |

카드는 그림자보다 border를 우선한다. 채팅 버블, 문서 섹션, 보드 카드에 `shadow.md`를 쓰지 않는다.

### 2.5 Motion

| Token | 값 | 용도 |
|---|---:|---|
| `duration.fast` | 120ms | hover, focus |
| `duration.base` | 180ms | 패널 전환, 메뉴 |
| `duration.slow` | 240ms | 모달 진입 |
| `ease.standard` | `cubic-bezier(.2,0,0,1)` | 기본 전환 |

- 로딩 spinner는 회전 애니메이션을 허용하되 텍스트 상태를 함께 제공한다.
- 메시지가 도착할 때 과한 bounce, confetti, typing token animation을 사용하지 않는다.
- `prefers-reduced-motion: reduce`에서는 비필수 전환을 제거한다.

### 2.6 Layering

| Layer | z-index |
|---|---:|
| Base content | 0 |
| Sticky header / pane header | 20 |
| Dropdown / tooltip | 40 |
| Drawer backdrop | 60 |
| Drawer | 70 |
| Modal backdrop | 80 |
| Modal | 90 |
| Toast | 100 |

---

## 3. Information Architecture

### 3.1 Candidate IA

```text
/join?token=...
└─ 초대 확인·동의
   └─ /office/{sessionId}
      ├─ 과제 안내 모달
      ├─ 팀 대화
      │  ├─ # 프로젝트-공지
      │  └─ # 장바구니-개선
      ├─ 자료실
      │  ├─ 과제 브리프
      │  ├─ 지표 정의
      │  ├─ 고객 리서치
      │  ├─ 운영 정책
      │  ├─ 릴리스 로그
      │  └─ 팀 메모
      ├─ 태스크
      ├─ 개선 기획안
      ├─ AI 어시스턴트
      └─ 제출
         └─ /debrief/{sessionId}
```

지원자에게는 “평가 리포트” 또는 관리자 경로를 탐색 항목으로 보여주지 않는다.

### 3.2 Admin IA

P0 경로 계약을 우선한다.

```text
/admin/login
└─ /admin/sessions
   ├─ 세션·초대 목록
   ├─ 초대 생성
   └─ 지원자 상세
      ├─ 진행 개요
      ├─ 제출 기획안
      ├─ 활동 기록
      │  ├─ 대화
      │  ├─ 태스크·위임
      │  └─ AI 사용·승인
      └─ /admin/reports/{sessionId}
         ├─ 관찰 범위
         ├─ 행동 요소
         ├─ 업무 접근 방식
         ├─ 제공된 도움
         └─ 한계
```

“시험 및 시나리오 관리”는 P0에서 시나리오 seed 1개와 초대 기반 세션 운영까지만 제공한다. 다중 시나리오 생성·편집·복제 UI는 P1이며, P0에서 작동하는 것처럼 표시하지 않는다.

### 3.3 Global navigation model

- 지원자: 앱 셸 내부 워크스페이스 내비게이션. 별도 전역 관리자 내비게이션 없음.
- 관리자: 좌측 224px 전역 내비게이션 + 상단 64px 헤더를 권장한다.
- 로그아웃, 현재 사용자/별칭, 데모 모드는 사용자 메뉴 또는 헤더 보조 영역에 둔다.
- `fixture`/`live`, RAG fallback 등 기술 상태 배지는 데모 환경에서만 헤더 우측에 표시하며 지원자 판단을 방해하지 않게 작게 둔다.

---

## 4. Candidate Workspace

### 4.1 Desktop layout: 1440px 기준

지원자 핵심 화면 `/office/{sessionId}`는 3영역으로 구성한다.

```text
┌──────────────────────────────────────────────────────────────────────┐
│ 56px Top bar: Day Zero / 모아마켓 프로젝트 | 저장 상태 | 제출하기   │
├──────────────┬────────────────────────────┬──────────────────────────┤
│ 248px        │ min 460px / fluid          │ 480px                    │
│ Workspace    │ Team messenger             │ Work panel               │
│ navigation   │                            │ 문서 / 태스크 탭          │
│              │                            │                          │
│ 과제 안내     │ # 장바구니-개선             │ 5섹션 기획안               │
│ 채널          │ 팀장·동료·지원자 메시지      │ 또는 태스크 보드           │
│ 자료실        │ 조사 진행·승인 카드          │                          │
│ 태스크        │                            │                          │
│              │ fixed composer             │ sticky panel header       │
└──────────────┴────────────────────────────┴──────────────────────────┘
                                      + AI 어시스턴트 400px drawer
```

그리드 권장값:

```css
grid-template-columns: 248px minmax(460px, 1fr) minmax(420px, 480px);
height: 100dvh;
min-width: 1024px;
```

- 상단 바 높이: 56px, 배경 Surface, 하단 border.
- 각 pane은 독립 scroll을 사용한다. 전체 body scroll은 잠근다.
- 중앙 채팅 입력창은 하단 고정, 메시지 목록만 스크롤한다.
- 오른쪽 작업 패널은 문서와 태스크를 탭으로 전환한다. 1440px에서도 두 개를 동시에 압축 표시하지 않는다.
- AI 어시스턴트는 오른쪽 drawer로 열고, 열려 있는 동안 작업 패널을 가리지 않도록 1600px 이상에서는 나란히 확장할 수 있다. 기본 1440px에서는 overlay drawer를 사용한다.

### 4.2 Top bar

왼쪽에서 오른쪽 순서:

1. Day Zero wordmark, 92px 이내.
2. 세로 구분선.
3. `루프커머스 · 모아마켓 장바구니 이탈 개선` 프로젝트명.
4. 연결 상태: 정상 시 숨김, 재연결 중일 때 `연결 복구 중`.
5. 저장 상태: `저장 중…`, `저장됨 · 12:42`, `저장 실패`.
6. `과제 안내` secondary button.
7. `제출하기` primary button.

제출 완료 후 `제출 완료` success badge로 대체하며 편집·메시지·승인 행동을 비활성화한다.

### 4.3 Workspace navigation

상단에는 가상 회사 컨텍스트를 제공한다.

- 회사명: 루프커머스
- 프로젝트명: 모아마켓 개선 프로젝트
- 현재 역할: 서비스 기획자

내비게이션 그룹:

1. `업무`
   - 과제 안내
   - 개선 기획안
   - 태스크, 미완료 개수 배지
2. `채널`
   - `# 프로젝트-공지`: 팀장 공지 중심, 입력 불가
   - `# 장바구니-개선`: 기본 팀 대화, 입력 가능
3. `자료실`
   - 기본 문서 6개. 읽지 않음 표시는 점으로 제공 가능하나 점수/완료율로 해석하지 않는다.
4. 하단 고정
   - `AI 어시스턴트 열기`
   - 사용자 메뉴

채널은 백엔드 `TEAM`을 시각적으로 나누는 프론트엔드 뷰다. 별도 채널 저장 구조가 없다면 팀장 `MANAGER` 메시지를 공지 뷰에서 필터링하고, 실제 대화 전송은 `TEAM`으로 유지한다.

### 4.4 Messenger

#### Channel header

- 높이 60px.
- 제목, 한 줄 설명, 참여자 아바타를 표시한다.
- `# 장바구니-개선`: “이도현 동료와 자료를 조사하고 작업을 조율하세요.”
- 우측에 자료 열기, AI 어시스턴트 열기 버튼을 둔다.

#### Message list

- 최대 본문 폭 720px, 패널 좌우 padding 24px.
- 날짜 구분선은 `2026년 10월 20일` 형식.
- 같은 작성자가 5분 이내 연속 작성하면 아바타·이름을 생략할 수 있으나 첫 메시지의 접근 가능한 작성자 정보는 유지한다.
- 지원자 메시지를 오른쪽 말풍선으로 과도하게 분리하지 않는다. Slack 유사 업무 맥락을 위해 모든 메시지를 왼쪽 정렬하고 지원자 메시지는 연한 neutral 배경 또는 이름 옆 `나`로 구분한다.
- 메시지 수정·삭제 UI는 P0에 제공하지 않는다.

#### Actor presentation

| Actor | 표시명 | 시각 규칙 |
|---|---|---|
| `MANAGER` | 한서윤 · 팀장 | `한` 이니셜, heading 색, `팀장` neutral badge |
| `COLLEAGUE` | 이도현 · AI 동료 | `이` 이니셜, primarySoft 아바타, `AI 동료` info badge |
| `CANDIDATE` | 사용자 별칭 · 나 | neutralStrong 아바타, `나` 텍스트 |
| `ASSISTANT` | AI 어시스턴트 | drawer 안에서만 표시, sparkle 계열 단색 아이콘 + `읽기 전용` 배지 |
| `SYSTEM` | 시스템 | 중앙 정렬 status row, 말풍선 사용 안 함 |

AI 동료 메시지에는 이름 옆에 항상 `AI 동료`를 표시한다. 사람처럼 오인시키는 프로필 사진이나 온라인 상태를 사용하지 않는다.

#### Message anatomy

```text
[Avatar] 이도현  AI 동료                         12:41
         모바일 신규 고객의 이탈 지표를 확인했습니다…
         [근거 2개] [조사 상세 보기]
         ┌ 위임 제안 ───────────────────────────┐
         │ 모바일 신규 고객 근거 정리           │
         │ 대상: 데이터 및 VOC 근거 분석        │
         │ [내용 확인] [위임하기]               │
         └──────────────────────────────────────┘
```

- citation chip 레이블: 문서 제목 또는 `지표 조회 · current/mobile/new`.
- citation을 누르면 자료 drawer를 열고 정확한 인용 구간을 강조한다.
- 출처가 없는 AI 사실 주장은 UI에서 근거 있는 것처럼 꾸미지 않는다.
- 위임 제안은 `위임하기` 전까지 태스크가 생성되지 않았음을 `아직 시작되지 않음`으로 표시한다.

#### Composer

- 기본 높이 44px, 최대 144px까지 자동 확장.
- placeholder: `이도현 동료에게 조사나 업무를 요청하세요`.
- 좌측 `+` 메뉴: 자료 첨부를 새로 업로드하는 기능은 P1이므로 제공하지 않는다. P0에서는 `자료에서 인용`, `조사 범위 선택`만 제공할 수 있다.
- 우측 전송 버튼: 아이콘 + 접근 가능한 레이블 `메시지 보내기`.
- `Enter`: 전송, `Shift+Enter`: 줄바꿈. 한글 IME 조합 중 Enter는 전송하지 않는다.
- 빈 문자열, 8,000자 초과, 진행 중인 쓰기 승인 run에 따른 `RUN_BUSY`를 인라인으로 설명한다.
- 전송 시 낙관적으로 메시지를 표시하되 `전송 중`을 붙이고 실패 시 내용과 재시도 버튼을 보존한다.

### 4.5 AI investigation progress

AI run은 채팅 안의 `Run Status Card`로 표시한다.

상태 순서:

1. `QUEUED`: “조사 요청을 준비하고 있어요.”
2. `RUNNING` + `RUN_STARTED`: “자료를 확인하고 있어요.”
3. `TOOL_START`: 공개 `display_name`만 표시. 예: “세그먼트 지표 조회 중”. 비공개 args는 표시하지 않는다.
4. `TOOL_END`: 성공 시 체크 아이콘과 출처 개수, 실패 시 경고 아이콘.
5. `WAITING_APPROVAL`: 승인 카드로 전환.
6. `SUCCEEDED`: 결과 메시지와 출처 표시.
7. `FAILED`: 실패 사유의 사용자용 문구, 입력 보존 안내, `다시 시도`.

진행 카드에 퍼센트 완료율이나 남은 시간을 추정 표시하지 않는다. 단계가 실제 이벤트에 의해 변경될 때만 UI를 갱신한다.

### 4.6 Approval card

AI 변경은 반드시 독립 카드로 표시한다.

필수 내용:

- 제목: `문서 변경 승인이 필요합니다` 또는 `태스크 상태 변경 승인이 필요합니다`.
- 대상: 문서 섹션/태스크 제목.
- 제안자: 이도현 AI 동료.
- 변경 전/후 diff. 긴 텍스트는 기본 8줄, `전체 보기` 제공.
- 범위: `데이터 및 VOC 근거 분석 섹션만`.
- 만료 시각 또는 `10분 안에 결정해 주세요`.
- 주요 행동 `승인하고 반영`은 primary.
- 보조 행동 `거절`은 secondary. 오류색 버튼으로 만들지 않는다.

결정 후:

- 승인: 읽기 전용 success 카드 `승인됨 · 반영 완료`.
- 거절: neutral 카드 `거절됨 · 문서는 변경되지 않았습니다`.
- 만료: warning 카드 `승인 요청이 만료되었습니다` + 필요 시 새 제안 요청 안내.
- stale/version conflict: error가 아니라 warning 우선. `문서가 그 사이 변경되어 이 제안을 적용할 수 없습니다. 현재 내용을 유지했습니다.`와 `다시 조사 요청`을 제공한다.

### 4.7 Task board

P0는 드래그 앤 드롭 없이 4열 또는 목록+필터로 구현한다.

열:

- 할 일 `TODO`
- 진행 중 `IN_PROGRESS`
- 검토 필요 `REVIEW`
- 완료 `DONE`

`CANCELLED`는 기본 보드에서 제외하고 `취소됨 보기` 필터로 접근한다.

태스크 카드 필수 정보:

- 제목, 최대 2줄.
- 담당자: `나` 또는 `이도현 · AI 동료`.
- 연결 섹션.
- 상태 배지.
- AI task인 경우 `위임됨` 배지와 생성 출처 메시지 링크.
- 버전 충돌 시 최신 상태 재로드 안내.

상호작용:

- 지원자 태스크: 허용된 상태 전이만 버튼 메뉴로 제공한다.
- AI 동료 태스크가 `REVIEW`이면 카드 상단에 `검토 필요`를 강조하고 `수락`, `수정 요청`, `기각`을 제공한다.
- 검토 modal에서 선택적 comment와 근거 source를 연결한다.
- `수락`이 검증 완료를 뜻하지 않으므로 안내 문구를 넣는다: “자료와 대조한 근거가 있다면 함께 남겨 주세요.”
- 원래 `evidence` 지원자 태스크와 새로 생성된 동료 조사 태스크를 별도 카드로 유지한다.

### 4.8 Artifact editor

#### Structure

오른쪽 작업 패널의 기본 탭은 `개선 기획안`이다.

- 패널 헤더 60px: 문서명, 버전, 저장 상태.
- 문서 outline: 5개 섹션 탭 또는 세로 목차.
- 편집 영역: textarea 기반 P0 구현을 허용한다.
- 섹션 하단: 연결 근거 chips, 글자 수, 마지막 저장 시간.

표시 순서:

1. 문제 정의 (`problem`)
2. 데이터 및 VOC 근거 분석 (`evidence`)
3. 개선안 제안 (`options`)
4. 우선순위 및 제약 (`risks`)
5. MVP 검증 계획과 성공 지표 (`experiment`)

#### Section guidance

도움말은 정답을 유도하지 않는 질문형 placeholder로 제공한다.

| 섹션 | 도움말 |
|---|---|
| 문제 정의 | “어떤 사용자와 어떤 단계의 문제를 먼저 다룰지 정의하세요.” |
| 데이터 및 VOC 근거 분석 | “수치, VOC, 출처와 데이터의 한계를 함께 정리하세요.” |
| 개선안 제안 | “검토한 대안과 선택 이유를 비교해 작성하세요.” |
| 우선순위 및 제약 | “먼저 할 일, 운영·개발 제약, 불확실성을 정리하세요.” |
| MVP 검증 계획과 성공 지표 | “가설, 성공 지표, 보호 지표, 실험 방법을 작성하세요.” |

#### Editing behavior

- 입력 즉시 로컬 draft를 유지한다.
- 800ms debounce 후 현재 `base_version`으로 저장한다.
- 저장 요청 전: `수정됨`.
- 요청 중: spinner + `저장 중…`.
- 성공 응답 후에만: check + `저장됨 · HH:mm`.
- 실패: 입력을 유지하고 `저장하지 못했습니다` + `다시 시도`.
- 버전 충돌: 현재 로컬 입력과 서버 최신 내용을 모두 보존한 비교 dialog를 연다. `내 입력 복사`, `최신 버전으로 다시 열기`를 제공한다. 자동 덮어쓰지 않는다.
- AI가 반영한 revision은 `AI 동료가 승인 후 반영` provenance를 표시한다. 사용자가 이후 수정하면 최신 내용의 작성 주체만 단순히 덮어쓰지 말고 revision history에서 구분한다.

#### Evidence linking

- 근거 chip은 본문 아래 별도 영역에 표시한다.
- 문서 인용: 문서명 + 버전.
- 도구 수치: 조건 + 데이터 버전.
- VOC: 케이스 ID.
- 근거 삭제는 본문 삭제와 독립 동작이며 확인 없이 즉시 삭제하되 undo toast를 5초 제공할 수 있다.

### 4.9 Assignment modal

최초 세션 시작 시 1회 자동 표시하고 이후 상단 `과제 안내`로 다시 연다.

- width: 720px, max-height: `min(760px, calc(100dvh - 64px))`.
- 모바일/좁은 화면: full-screen dialog.
- 제목: `모아마켓 개선 프로젝트에 합류했습니다`.
- 내용 순서:
  1. 팀장 메시지 형태의 공개 브리프.
  2. 최종 산출물 5개 섹션.
  3. 사용 가능한 자료와 AI 동료 역할.
  4. “최종 문제 정의·우선순위·기획안은 직접 결정합니다.”
  5. 기록·AI 사용·사람 판단에 관한 동의 요약. 실제 동의는 `/join`에서 처리한다.
- 주요 버튼: `업무 시작하기`.
- 보조 버튼: 최초 표시에서는 없음. 재열람 시 `닫기` 제공.
- backdrop click과 Escape: 최초 필수 안내에서는 닫지 않으며, 재열람에서는 닫을 수 있다.

### 4.10 Document viewer

자료 클릭 시 중앙을 이탈하지 않고 520px 오른쪽 drawer 또는 작업 패널에서 연다.

- 제목, 버전, 문서 종류, 열람 시각.
- 원문 markdown 렌더링.
- citation deep link 시 인용문을 `mark` 요소와 Primary Soft 배경으로 강조하고 화면 중앙에 스크롤한다.
- 원문을 수정하는 UI는 제공하지 않는다.
- `기획안에 근거 연결`은 선택한 연속 텍스트가 있을 때만 활성화하고, 정확한 source ref를 생성할 수 있는 경우에 한한다.

### 4.11 AI assistant drawer

AI 동료와 분리된 개인용 읽기 전용 도구다.

- 폭 400px, 우측 고정 drawer.
- 헤더: `AI 어시스턴트` + `읽기 전용` badge.
- 설명: “자료를 찾고 내용을 이해하도록 돕습니다. 기획안이나 태스크를 직접 변경하지 않습니다.”
- 별도 `ASSISTANT` 채널로 메시지를 전송한다.
- 문서 검색, 지표 조회, 개념 설명만 허용한다.
- 위임, 승인, 문서 반영 버튼을 제공하지 않는다.
- 빈 상태 quick prompts:
  - `장바구니 이탈률 정의 찾기`
  - `운영 제약 자료 찾기`
  - `최근 변경 기록 찾기`

### 4.12 Submission flow

1. 상단 `제출하기` 클릭.
2. 프론트엔드는 현재 저장 상태를 확인한다. 저장 중이면 완료까지 기다린 뒤 modal을 연다. 저장 실패면 제출 전에 재시도 또는 명시적 취소를 요구한다.
3. 제출 확인 modal에서 5개 섹션의 채움 여부를 표시한다.
4. 빈 섹션이 있으면 warning: `비어 있는 섹션이 2개 있습니다. 불완전한 상태로도 제출할 수 있습니다.`
5. 선택적 제출 요약 `summary` 입력, 최대 길이는 API 계약과 맞춘다.
6. checkbox: `제출 후에는 문서와 진행 중 작업을 수정할 수 없음을 확인했습니다.`
7. 주요 버튼 `최종 제출`, 보조 버튼 `계속 작성`.
8. 제출 요청 중 modal을 닫지 않고 중복 클릭을 막는다.
9. 성공하면 워크스페이스를 읽기 전용으로 전환하고 `/debrief/{sessionId}`로 이동한다.

재요청이 기존 제출을 반환하는 멱등 동작일 때 오류 toast를 띄우지 않고 동일 완료 상태로 이동한다.

### 4.13 Debrief

- 성공 아이콘 + `기획안이 제출되었습니다`.
- 제출 시각, 문서 버전, 진행 중 AI 작업 종료 안내.
- 실제 발생한 지원 안내와 발생하지 않은 상황을 설명하되 평가 결과는 표시하지 않는다.
- `AI를 사용하지 않음`, `관찰 기회 없음`, `관련 행동 근거 부족`을 부정적 점수처럼 표현하지 않는다.
- CTA: `제출한 기획안 보기`.
- 관리자 리포트 링크는 제공하지 않는다.

---

## 5. Admin Dashboard

### 5.1 Shell

- 좌측 224px navigation, 상단 64px header.
- 콘텐츠 최대 폭 1440px, 좌우 padding 32px.
- 내비게이션 P0: `세션`, `초대`. `시나리오`는 읽기 전용 현재 시나리오 요약으로 제공 가능하나 편집 기능은 노출하지 않는다.
- 헤더: 페이지 제목, 서비스 상태, 관리자 메뉴.

### 5.2 Login

- 중앙 400px 카드.
- 로고, 제목 `Day Zero 관리자`, 설명, 이메일, 비밀번호, 로그인 버튼.
- 오류는 폼 상단 summary와 해당 필드에 연결한다.
- 인증 실패는 “이메일 또는 비밀번호를 확인해 주세요.”로 통일하여 계정 존재 여부를 노출하지 않는다.
- 진행 중 버튼 레이블 `로그인 중…`, 중복 submit 방지.

### 5.3 Sessions overview

#### Page header

- H1 `지원자 세션`.
- 설명 `초대를 만들고 진행 및 제출 상태를 확인합니다.`
- primary `새 초대 만들기`.

#### Summary cards

API가 신뢰 가능한 집계를 제공할 때만 다음 4개를 표시한다.

- 전체
- 진행 중
- 제출 완료
- 리포트 확인 필요(실패 포함)

프론트에서 현재 로드된 100개만 전체인 것처럼 집계하지 않는다. 전체 집계 API가 없으면 summary cards를 생략한다.

#### Sessions table

| 열 | 표현 |
|---|---|
| 지원자 | 별칭, 세션 ID 후 8자리 보조 |
| 시나리오 | 모아마켓 장바구니 이탈 개선 |
| 진행 상태 | 생성됨 / 진행 중 / 제출 완료 |
| 현재 단계 | 과제 확인 / 업무 진행 / 검토 / 종료 |
| 리포트 | 대기 / 생성 중 / 준비됨 / 실패 |
| 시작 시각 | KST, 상대시간 tooltip 가능 |
| 작업 | `열기` 또는 overflow menu |

- 기본 정렬: 최근 생성/활동 순. API가 정렬을 제공하지 않으면 받은 순서를 임의로 재해석하지 않는다.
- row 전체 클릭 + 명시적 `열기` 링크를 함께 제공한다.
- pagination은 cursor 기반 `다음`을 사용한다.
- 상태 배지는 색과 텍스트를 함께 사용한다.

### 5.4 Invite creation

- modal width 480px.
- 필드: 지원자 별칭.
- 생성 성공 후 초대 URL을 한 번 표시한다.
- 보안 안내: `이 링크는 원문 그대로 다시 확인할 수 없습니다. 안전한 채널로 전달하세요.`
- `링크 복사` 후 버튼 레이블 `복사됨`을 2초 표시한다.
- 앱 내부에서 이메일 발송 버튼을 제공하지 않는다.
- 만료 시각 72시간을 명시한다.

### 5.5 Candidate session detail

헤더:

- 지원자 별칭, 상태, 시작/제출 시각.
- `리포트 열기`는 READY일 때 primary 또는 강조 secondary.
- 실패 시 `리포트 다시 생성`은 error가 아닌 secondary + 오류 문구.

탭:

1. `개요`: 상태, 현재 phase, 태스크 진행, AI run 상태, 제출 정보.
2. `제출 기획안`: 제출 전에는 현재 draft임을 표시, 제출 후 snapshot을 표시.
3. `활동 기록`: 대화·문서 revision·태스크·위임·승인·도구 사용의 시간순 기록.
4. `평가 리포트`: `/admin/reports/{sessionId}`.

관리자가 지원자 진행 중 문서를 수정하거나 대신 승인하는 기능은 제공하지 않는다.

### 5.6 Submission review

- 좌측 280px outline, 중앙 문서 최대 760px, 우측 360px evidence context panel.
- 문서 5섹션은 지원자와 동일한 화면 레이블·순서를 사용한다.
- 각 section header에 마지막 revision actor와 시각을 표시할 수 있다.
- AI 반영 내용은 승인된 revision 이력으로만 구분하며 현재 본문에 과도한 하이라이트를 상시 적용하지 않는다.
- source chip 클릭 시 우측 패널에 원문/도구 결과/메시지와 정확한 인용 구간을 표시한다.
- 제출 snapshot과 이후 데이터가 섞이지 않게 `제출 버전` badge를 표시한다.

### 5.7 Evaluation report

#### Header

- 제목 `행동 근거 기반 평가 리포트`.
- 지원자 별칭, 시나리오·정책 버전, 생성 방식 `AI + 규칙` 또는 `규칙 기반 대체`.
- limitation banner: `이 리포트는 단일 가상 과제에서 관찰된 행동을 정리하며 성격·채용 성과를 단정하지 않습니다.`
- 점수, 순위, 합불 CTA는 없음.

#### Layout

상단 요약은 사실만 제공한다.

- 관찰된 행동 항목 수
- 관찰 기회 없음 항목 수
- 사용된 도움 단계/도구 이력
- 발생한 조건부 상황 수

평가 카드 구조:

```text
[업무 접근 방식] 근거 조사                  [관찰됨]
관찰 기회     모바일 신규 고객 조사를 요청함
실제 행동     조사 결과를 수정 요청하고 자료와 대조함
원문 근거     [메시지 #…] [문서 revision #…]
제한된 해석   검증을 시도했을 가능성 (AI 추정)
후속 확인점   자료 대조의 깊이는 기록만으로 확인하기 어려움
```

- `실제 행동`과 `원문 근거`는 Surface.
- `제한된 해석`은 Info Soft 배경, `AI 추정` badge.
- `한계`는 Neutral Subtle 배경.
- status 값:
  - `OBSERVED` → `관찰됨`
  - `NO_OPPORTUNITY` → `관찰 기회 없음`
  - `INSUFFICIENT_EVIDENCE` → `관련 행동 근거 부족`
  - `NOT_USED` → `사용하지 않음`

#### Report sections

1. 관찰 범위 및 발생 상황.
2. 행동 요소: 책임감, 존중·소통, 협력 태도, 유연성, AI 활용.
3. 업무 접근 방식: 문제 정의, 근거 조사, 대안 비교·우선순위, 검증 계획, 결과 수정.
4. 제공된 AI 도움과 승인 기록.
5. 한계 및 후속 확인점.

#### Evidence context

- 원문 근거 클릭 시 side panel을 연다.
- 종류 icon + 레이블: 대화, 문서 수정, 행동, 도구 호출.
- 정확한 quote와 앞뒤 최소 컨텍스트를 제공한다.
- 원문 ID, 시각, actor를 표시한다.
- quote 불일치 또는 제거된 evidence는 UI에 렌더링하지 않는다.

### 5.8 Report states

- `PENDING`: “제출 내용을 정리할 준비를 하고 있습니다.”
- `RUNNING`: “행동 기록과 근거를 연결하고 있습니다.”
- `READY`: 리포트 본문.
- `FAILED`: “리포트를 생성하지 못했습니다. 지원자 제출물은 안전하게 저장되어 있습니다.” + `다시 생성`.
- `RULES_FALLBACK`: 상단 info banner로 생성 방식 한계를 명시하고 실패처럼 보이게 하지는 않는다.

---

## 6. Component Specifications

### 6.1 Buttons

공통 높이와 패딩:

| Size | 높이 | 좌우 padding | 텍스트 |
|---|---:|---:|---|
| Small | 32px | 12px | 12/18, 600 |
| Medium | 40px | 16px | 14/22, 600 |
| Large | 48px | 20px | 15/24, 600 |
| Icon | 40×40px | 0 | 20px icon |

변형:

- Primary: `#16181D` background, `#F8F9FA` foreground, hover `#2B2E34`.
- Secondary: Surface, Body text, Border; hover Neutral Subtle.
- Tertiary: transparent, Body; hover Neutral Subtle.
- Danger: Surface, Error text, Error border. 파괴적 행동 확인 modal에서만 사용.
- Disabled: `#E9ECEF` background, `#6B7280` text, cursor not-allowed. tooltip만으로 이유를 전달하지 말고 주변 설명 제공.

상태:

- focus-visible: `0 0 0 3px rgba(30,58,138,.28)`.
- active: `transform: translateY(1px)` 허용. reduced motion에서는 제거.
- loading: 좌측 16px spinner + 동작형 레이블. 폭 변화 방지를 위해 최소 너비 유지.

### 6.2 Inputs and textarea

- 높이 40px, textarea 최소 96px.
- padding 10px 12px.
- 입력 border는 `#C3C8CF`, hover도 동일 색을 유지하고 focus에서 `color.focus` 2px를 적용한다.
- 레이블은 입력 위에 두고 placeholder로 대체하지 않는다.
- help text와 error text를 동일 위치에 표시한다.
- error: border Error + 아이콘 + 문구. 입력값은 유지한다.
- disabled와 readonly를 구분한다. readonly는 Surface/Body를 유지하고 자물쇠 또는 설명을 제공한다.
- 글자 수 제한이 중요할 때 `현재 / 최대`를 우측 아래에 표시한다.

### 6.3 Chat message

- 아바타 36px.
- 메시지 row padding 8px 24px, hover 시 Neutral Subtle 40% 수준.
- 이름과 시간 baseline 정렬.
- 본문 위 margin 2px, citation 영역 위 8px.
- 시스템 row 높이 최소 32px, Small text.
- AI 내용에는 actor badge를 필수 표시한다.

### 6.4 Modal

- Small 480px, Medium 640px, Large 800px.
- padding 24px, header/footer 20~24px.
- 최대 높이 `calc(100dvh - 64px)`.
- footer는 내용 스크롤과 분리해 sticky.
- 열릴 때 첫 의미 있는 요소 또는 제목에 focus.
- 닫힐 때 trigger로 focus 복귀.
- focus trap, Escape 처리, `aria-modal=true`, label/description 연결.
- destructive/irreversible 행동은 제목, 결과, 대상, 확인 행동을 명시한다.

### 6.5 Tabs

- 높이 40px.
- 활성 탭: Heading text, 하단 2px Primary.
- 비활성: Muted text.
- badge count는 별도 접근 가능한 이름 포함.
- arrow key로 이동, Home/End 지원. 패널은 `aria-controls`로 연결한다.

### 6.6 Card

- Surface, border, radius 12px, 기본 padding 16px.
- selectable card hover border strong.
- selected card: Primary border + Primary Soft background.
- 상태 카드에서 왼쪽 3px accent를 사용할 수 있으나 텍스트/아이콘을 반드시 병행한다.

### 6.7 Badge

- 높이 24px, padding 4px 8px, radius full, Small Strong.
- neutral/info/success/warning/error 5종.
- 텍스트는 구체적 상태 사용: `진행 중`, `승인 대기`, `저장 실패`.
- 의미 없는 `활성`, `완료` 단독 표시는 문맥이 모호하면 피한다.

### 6.8 Table

- header 44px, row 최소 52px.
- header background `#F8FAFC`, Body Strong 12px.
- cell padding 12px 16px.
- row hover Neutral Subtle.
- 선택 checkbox가 없으면 빈 첫 열을 만들지 않는다.
- 숫자는 오른쪽 정렬, 텍스트와 상태는 왼쪽 정렬.
- sticky header 사용 시 top offset을 admin header와 맞춘다.
- 작은 화면에서는 중요한 열을 고정하고 나머지는 detail drawer로 이동한다. 의미를 잃는 카드 변환을 남발하지 않는다.

### 6.9 Task card

- 최소 높이 112px, padding 14px.
- 상태 변경은 명시적 menu/button으로 수행한다.
- owner avatar 24px, target section badge.
- `REVIEW` 카드에는 warning border와 `검토 필요` 텍스트.
- AI 위임 카드에는 연결된 원문 메시지 링크.

### 6.10 Document editor

- 섹션 textarea 최소 240px, editor body 15/25px.
- 집중 시 section card border focus color.
- 섹션 간 16px.
- 저장 상태는 전체 문서 헤더와 현재 섹션 footer에 동일 source of truth로 표시한다.
- markdown toolbar는 P0에서 제공하지 않는다. 제공한다면 굵게, 목록, 링크 수준으로 제한하고 저장 body 형식과 일치해야 한다.
- AI 제안 diff는 editor 내부가 아닌 approval card/dialog에서 제공한다.

### 6.11 Toast and inline alert

- toast width 360px, 우측 상단, 최대 3개.
- 자동 사라짐: success 4초, info 6초. error와 복구 행동이 있는 toast는 자동으로 사라지지 않는다.
- 저장 상태처럼 지속적으로 중요한 내용은 toast가 아니라 고정 상태 영역에 표시한다.
- alert는 icon + title + body + optional action 구조.

### 6.12 Tooltip and menu

- tooltip은 보조 설명에만 사용하고 필수 정보를 숨기지 않는다.
- hover와 focus 모두에서 열리며 Escape로 닫힌다.
- menu item 최소 높이 36px.
- 위험 행동은 separator 아래에 배치하고 error text 사용.

---

## 7. Interaction & UX States

### 7.1 State matrix

| 상황 | UI 표현 | 사용자 행동 |
|---|---|---|
| 최초 페이지 로딩 | 화면 구조 skeleton, 텍스트 shimmer 최소화 | 대기 |
| 세션 빈 상태 | 목적 설명 + 다음 행동 1개 | 과제 보기 또는 메시지 작성 |
| 목록 빈 상태 | 원인에 맞는 문구 | 관리자: 새 초대 만들기 |
| 일반 오류 | inline alert + trace ID 복사 가능 | 다시 시도 |
| 401 | 로그인/초대 상태 재확인 | 로그인으로 이동 |
| 403/404 | 정보 노출 없는 접근 불가 화면 | 목록/워크스페이스로 이동 |
| 409 version conflict | 로컬/서버 내용 모두 보존 | 비교 후 다시 저장 |
| 429 | 재시도 가능 시점 없이 과도한 countdown 금지 | 잠시 후 재시도 |
| 503 | 입력 보존 안내 | 다시 시도 |
| SSE 재연결 | top bar `연결 복구 중` + info dot | 자동 재연결, 필요 시 새로고침 |
| AI 조사 진행 | run status card 단계 표시 | 취소 API가 없으므로 취소 버튼 미제공 |
| 승인 대기 | approval card + 만료 정보 | 승인 또는 거절 |
| 저장 중 | spinner + `저장 중…` | 계속 입력 가능, 요청 병합 주의 |
| 저장 완료 | check + 저장 시각 | 작업 계속 |
| 저장 실패 | error text + draft 보존 | 다시 시도 |
| 제출 중 | modal blocking progress | 중복 제출 불가 |
| 제출 완료 | read-only workspace + debrief | 기획안 열람 |

### 7.2 Loading

- 300ms 미만 작업에는 spinner를 지연 표시하여 flicker를 줄일 수 있다.
- 첫 화면은 실제 레이아웃과 동일한 skeleton을 사용한다.
- 버튼 작업은 해당 버튼 안에서 로딩을 표시하고 전역 화면을 막지 않는다.
- 제출·승인처럼 원자성이 중요한 요청만 modal/카드를 잠근다.

### 7.3 Empty states

지원자 채팅:

> 프로젝트가 시작되었습니다. 팀장 안내를 확인하고, 필요한 자료를 읽거나 이도현 동료에게 조사 범위를 요청해 보세요.

태스크:

> 아직 추가 태스크가 없습니다. 기획안의 기본 작업부터 시작할 수 있습니다.

관리자 세션:

> 아직 생성된 지원자 세션이 없습니다. 초대 링크를 만들어 첫 세션을 시작하세요.

빈 상태 일러스트는 필수가 아니며 단색 아이콘으로 충분하다.

### 7.4 Error copy

- 사용자 책임으로 돌리지 않는다.
- 원인, 보존 여부, 다음 행동 순으로 쓴다.
- 예: `조사를 완료하지 못했습니다. 작성 중인 기획안은 저장되어 있습니다. 다시 시도해 주세요.`
- Agent 실패는 관리자 리포트에서 지원자 행동 실패로 기록하지 않는다.
- 내부 오류 코드와 trace ID는 세부 보기에서 제공하되 SQL, secret, prompt는 노출하지 않는다.

### 7.5 Retry

- 실패한 run만 `다시 시도`를 제공한다.
- 승인·변경은 기존 proposal을 조용히 재실행하지 않고 새 제안을 생성해야 함을 안내한다.
- 재시도 클릭 후 새 run ID가 생기면 기존 실패 카드와 새 진행 카드를 연결해 중복으로 보이지 않게 한다.

### 7.6 Connection recovery

- SSE 단절 시 마지막 표시 상태를 유지한다.
- `Last-Event-ID` 재연결 중 메시지·태스크를 성공한 것처럼 추정하지 않는다.
- 복원 이벤트는 `seq`로 중복 제거하며 동일 메시지를 재애니메이션하지 않는다.
- 15초 이상 복구되지 않으면 `새로고침` 보조 행동을 제공한다. 로컬 draft 존재 시 먼저 보존 안내를 한다.

### 7.7 Final submission states

| 상태 | 편집 | 메시지 | 제출 버튼 |
|---|---|---|---|
| ACTIVE + saved | 가능 | 가능 | 활성 |
| ACTIVE + saving | 가능 | 가능 | 대기 후 제출 |
| ACTIVE + save failed | 로컬 가능 | 가능 | 비활성, 저장 복구 안내 |
| SUBMITTING | 잠금 | 잠금 | `제출 중…` |
| SUBMITTED | 읽기 전용 | 입력 불가 | `제출 완료` badge |

---

## 8. Responsive Layout

### 8.1 Breakpoints

| 이름 | 범위 | 전략 |
|---|---|---|
| Wide | `≥1600px` | 3-pane + assistant side-by-side 가능 |
| Desktop | `1280–1599px` | 248px nav + chat + 420~480px work panel |
| Compact desktop | `1024–1279px` | 216px nav + chat, 문서/태스크는 overlay 또는 tab panel |
| Tablet | `768–1023px` | 단일 주 작업 pane + drawer navigation |
| Small | `<768px` | 기능 보존용 단일 pane, 장시간 시험 비권장 안내 가능 |

### 8.2 Candidate behavior

#### 1280px 이상

- 기본 3-pane.
- 오른쪽 작업 패널 최소 420px.
- 중앙 채팅 최소 460px.

#### 1024–1279px

- 좌측 nav 216px.
- 중앙을 기본 채팅으로 유지.
- 오른쪽 문서/태스크는 480px overlay panel로 연다.
- 상단에 `대화`, `기획안`, `태스크` 전환 버튼을 제공할 수 있다.
- PRD 수용 기준상 가로 overflow와 가려진 제출 버튼이 없어야 한다.

#### 768–1023px

- 상단 56px + 단일 pane.
- hamburger로 워크스페이스 navigation drawer.
- bottom navigation: `대화`, `기획안`, `태스크`, `자료` 4개까지.
- AI 어시스턴트는 full-screen drawer.
- 문서 편집 중 다른 pane으로 이동할 때 저장 상태를 확인한다.

#### 768px 미만

- modal/drawer full screen.
- table은 horizontal scroll보다 중요 필드 카드 + detail view를 사용한다.
- 제출 행동은 bottom sticky 영역에 둘 수 있으나 OS safe area를 반영한다.
- 시험의 권장 환경 안내를 표시할 수 있지만 기능을 의도적으로 차단하지 않는다.

### 8.3 Admin behavior

- 1200px 이상: 고정 sidebar + table.
- 768–1199px: 접히는 sidebar, 중요 table 열만 유지.
- 768px 미만: 세션 목록은 카드로 변환하며 별칭, 상태, 리포트 상태, 시각, 열기 행동을 보존한다.
- 리포트 evidence panel은 좁은 화면에서 bottom sheet/full-screen으로 전환한다.

### 8.4 Viewport and safe areas

- `100vh` 대신 `100dvh`를 우선한다.
- sticky footer는 `env(safe-area-inset-bottom)`을 반영한다.
- 확대 200%에서도 주요 행동이 가려지지 않아야 한다.

---

## 9. Accessibility

### 9.1 Contrast

- 일반 텍스트 WCAG AA 4.5:1 이상, 큰 텍스트 3:1 이상을 목표로 한다.
- `#16181D` 배경에는 `#F8F9FA` 텍스트를 사용한다.
- Muted text는 흰 배경에서 작은 장문 본문에 사용하지 않는다.
- focus indicator와 컴포넌트 경계는 인접 색 대비 3:1을 목표로 한다.

### 9.2 Keyboard

- 모든 기능은 키보드로 실행 가능해야 한다.
- Tab 순서는 시각 순서와 일치한다.
- skip link: `주요 콘텐츠로 이동`, 지원자 화면은 추가로 `메시지 입력으로 이동` 제공.
- 채팅 입력 `Enter`/`Shift+Enter` 규칙을 근처 도움말 또는 `aria-describedby`로 제공한다.
- 보드 상태 변경은 drag 없이 버튼으로 가능해야 한다.
- modal/drawer는 focus trap과 focus return을 구현한다.
- 탭은 WAI-ARIA tabs keyboard pattern을 따른다.

### 9.3 Focus

- 모든 interactive 요소에 `:focus-visible` 링을 표시한다.
- 포커스 링이 overflow hidden으로 잘리지 않게 2px 여유를 둔다.
- 페이지 전환 후 H1 또는 주요 container로 focus를 이동한다.
- 오류 submit 후 첫 오류 필드 또는 오류 summary로 focus를 이동한다.

### 9.4 Screen readers and live regions

- 저장 상태: `aria-live="polite"`, 짧은 문구만 읽는다.
- 오류: `role="alert"`는 즉각 대응이 필요한 경우에만 사용한다.
- AI 진행 이벤트를 매번 모두 읽어 방해하지 않는다. 중요한 전환(`조사 완료`, `승인 필요`, `실패`)만 polite live region에 알린다.
- 새 채팅 메시지가 사용자의 읽기 위치를 강제로 이동시키지 않는다. 하단에 있을 때만 자동 스크롤하고, 위를 읽는 중이면 `새 메시지 2개` 버튼을 표시한다.
- 아이콘 버튼은 `aria-label`을 제공한다.
- 아바타 문자는 장식이면 `aria-hidden`; 작성자 이름은 텍스트로 제공한다.

### 9.5 Status semantics

- badge 텍스트 자체가 상태를 설명해야 한다.
- 성공 check, 경고 triangle, 오류 circle-x 등 형태를 함께 쓴다.
- diff는 색 외에 `추가됨`, `삭제됨` 레이블 또는 기호를 제공한다.
- chart를 추가한다면 동일 데이터를 표로 제공한다. P0 관리자 핵심 화면은 chart 없이도 완전해야 한다.

### 9.6 Language and time

- 문서 루트 `lang="ko"`.
- 시각 표시는 Asia/Seoul 기준, 예: `2026. 10. 20. 13:05`.
- 상대 시각에는 절대 시각을 tooltip 또는 accessible description으로 제공한다.
- 숫자, %, pp를 구분한다. rate 0~1 API 값을 화면에서 `%`로 변환하고 percentage point는 `pp`로 표기한다.

---

## 10. Implementation Handoff

### 10.1 CSS variables

`frontend/src/styles/tokens.css`의 권장 기준이다. 기존 파일이 있으면 값만 대조하고 구조를 강제 변경하지 않는다.

```css
:root {
  --color-primary: #16181d;
  --color-primary-hover: #2b2e34;
  --color-primary-soft: #e9ecef;
  --color-on-primary: #f8f9fa;
  --color-accent: #1e3a8a;
  --color-heading: #16181d;
  --color-body: #16181d;
  --color-muted: #6b7280;
  --color-background: #f8f9fa;
  --color-surface: #ffffff;
  --color-border: #e9ecef;
  --color-border-strong: #c3c8cf;
  --color-neutral-strong: #16181d;
  --color-neutral-subtle: #e9ecef;
  --color-success: #16a34a;
  --color-success-soft: #f0fdf4;
  --color-success-border: #bbf7d0;
  --color-info: #1e3a8a;
  --color-info-soft: #eef2ff;
  --color-info-border: #c7d2fe;
  --color-warning: #d97706;
  --color-warning-soft: #fffbeb;
  --color-warning-border: #fde68a;
  --color-error: #dc2626;
  --color-error-soft: #fef2f2;
  --color-error-border: #fecaca;
  --color-focus: #1e3a8a;
  --color-overlay: rgba(22, 24, 29, 0.48);

  --font-sans: Pretendard, "Noto Sans KR", Inter, -apple-system,
    BlinkMacSystemFont, "Segoe UI", sans-serif;

  --space-1: 4px;
  --space-2: 8px;
  --space-3: 12px;
  --space-4: 16px;
  --space-5: 20px;
  --space-6: 24px;
  --space-8: 32px;
  --space-10: 40px;
  --space-12: 48px;

  --radius-sm: 6px;
  --radius-md: 8px;
  --radius-lg: 12px;
  --radius-full: 9999px;

  --shadow-sm: 0 1px 2px rgba(15, 23, 42, 0.06);
  --shadow-md: 0 8px 24px rgba(15, 23, 42, 0.1);

  --duration-fast: 120ms;
  --duration-base: 180ms;
  --duration-slow: 240ms;
  --ease-standard: cubic-bezier(0.2, 0, 0, 1);

  --topbar-height: 56px;
  --admin-header-height: 64px;
  --workspace-nav-width: 248px;
  --admin-nav-width: 224px;
  --work-panel-width: 480px;
  --assistant-drawer-width: 400px;
}

* {
  box-sizing: border-box;
}

:focus-visible {
  outline: 2px solid var(--color-focus);
  outline-offset: 2px;
}

@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    scroll-behavior: auto !important;
    transition-duration: 0.01ms !important;
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
  }
}
```

### 10.2 Frontend view-model mapping

API enum을 화면 문구로 흩어 작성하지 말고 단일 mapping에서 관리한다.

```ts
export const artifactSections = [
  { id: 'problem', label: '문제 정의' },
  { id: 'evidence', label: '데이터 및 VOC 근거 분석' },
  { id: 'options', label: '개선안 제안' },
  { id: 'risks', label: '우선순위 및 제약' },
  { id: 'experiment', label: 'MVP 검증 계획과 성공 지표' },
] as const;

export const sessionStatusLabel = {
  CREATED: '시작 전',
  ACTIVE: '진행 중',
  SUBMITTED: '제출 완료',
} as const;

export const runStatusLabel = {
  QUEUED: '대기 중',
  RUNNING: '진행 중',
  WAITING_APPROVAL: '승인 대기',
  SUCCEEDED: '완료',
  FAILED: '실패',
  CANCELLED: '취소됨',
} as const;
```

화면 순서와 저장 객체 순서를 혼동하지 않는다. JSON object의 key 순서에 의존하지 말고 `artifactSections` 배열로 렌더링한다.

### 10.3 Component responsibilities

| Component | 책임 | 하지 않는 일 |
|---|---|---|
| `CandidateWorkspaceShell` | pane 배치, responsive 전환 | 업무 데이터 직접 변경 |
| `WorkspaceNav` | 채널·자료·태스크 접근 | 권한 판단 |
| `MessageList` | actor별 메시지·출처 렌더링 | run 상태 추정 |
| `MessageComposer` | IME 안전 전송, draft 보존 | AI 응답 생성 |
| `RunStatusCard` | SSE 이벤트 기반 진행 표시 | 임의 progress % 계산 |
| `ApprovalCard` | before/after, 승인·거절 | 승인 전 낙관적 반영 |
| `ArtifactEditor` | 5섹션 편집, local draft | 충돌 시 자동 덮어쓰기 |
| `TaskBoard` | 상태·owner·review 표시 | drag 전용 상태 변경 |
| `SourceDrawer` | 원문·인용 강조 | 출처가 없는 문장 생성 |
| `AssistantDrawer` | 별도 ASSISTANT 채널 | write 도구·위임 |
| `SessionTable` | 관리자 목록·상태 | 현재 page만 전체로 집계 |
| `ReportEvidencePanel` | 근거 원문 컨텍스트 | AI 해석을 사실로 표시 |

### 10.4 API-to-UI rules

- 202 응답 후 즉시 완료로 표시하지 않는다. `run_id`와 SSE/run status로 추적한다.
- `ARTIFACT_UPDATED` 수신 시 로컬 미저장 draft가 없을 때만 서버 내용을 자동 반영한다. draft가 있으면 충돌 가능성을 알린다.
- `APPROVAL_REQUIRED`는 toast만 보내지 말고 채팅 흐름에 영구 카드로 추가한다.
- `REPORT_READY`의 내용은 candidate SSE에서 표시하지 않는다.
- `FAILED` payload의 `error_code`는 사용자용 문구 mapping을 거친다.
- `404`는 타인 세션 존재 여부를 추론할 수 없는 동일 화면을 사용한다.
- citation quote는 서버가 준 연속 부분 문자열을 그대로 표시하며 프론트에서 문장을 재작성하지 않는다.
- 지원자 화면에는 `admin_payload`, trace URL, 정책 조건, 도움 잠금 로직을 노출하지 않는다.

### 10.5 Save-state implementation rule

권장 상태 모델:

```ts
type SaveState =
  | { kind: 'idle'; savedAt?: string }
  | { kind: 'dirty' }
  | { kind: 'saving' }
  | { kind: 'saved'; savedAt: string; version: number }
  | { kind: 'conflict'; local: string; remote: string; remoteVersion: number }
  | { kind: 'failed'; draft: string; retryable: boolean };
```

- `saved`는 성공 응답 후에만 진입한다.
- section별 pending 요청 순서를 관리하고 오래된 응답이 최신 draft를 저장 완료로 덮지 않게 한다.
- route 이동과 제출 전 `dirty/saving/failed`를 검사한다.
- 브라우저 unload 경고는 local draft가 실제 서버 버전보다 새로울 때만 사용한다.

### 10.6 SSE implementation rule

- session 단위 마지막 `seq`를 메모리와 session storage에 보관할 수 있다.
- 재접속은 `Last-Event-ID` 또는 `after_seq` 계약을 따른다.
- `event_id`/`seq`로 중복 제거한다.
- 완성 메시지만 처리하며 token streaming UI를 가정하지 않는다.
- 이벤트 수신 순서가 UI 애니메이션보다 우선한다.

### 10.7 Implementation priority

기능·안전·상태를 먼저 완성하고 장식은 뒤로 둔다.

| 우선순위 | 화면/기능 | 완료 기준 |
|---:|---|---|
| 1 | 지원자 워크스페이스 셸 | 1440/1024에서 nav·chat·editor 접근, overflow 없음 |
| 2 | 문서 편집·저장 상태 | 5섹션, 800ms save, 성공/실패/충돌, draft 보존 |
| 3 | 채팅·AI 진행 | actor 구분, 202→SSE 상태, 출처, retry |
| 4 | 위임·승인·태스크 | 승인 전 무변경, diff, review 행동, 상태 복원 |
| 5 | 제출·debrief | 빈 섹션 경고, 중복 방지, 제출 후 read-only |
| 6 | 관리자 세션·제출물 | 표, 상태, submission snapshot, 활동 기록 |
| 7 | 평가 리포트 | 사실/해석 분리, evidence deep link, no score |
| 8 | 반응형·접근성 QA | keyboard, focus, 200% zoom, 1024px 검증 |
| 9 | 시각 polish | 아이콘 정리, 미세 spacing, motion |

### 10.8 Visual QA checklist

- [ ] 메인 6색 Cool gray + Ink blue 팔레트가 지정값과 일치한다.
- [ ] Primary 버튼은 `#16181D`, 글자는 `#F8F9FA`, 진행·선택 강조는 `#1E3A8A`이다.
- [ ] 그라데이션이 없다.
- [ ] 일반 카드에 과한 그림자가 없다.
- [ ] 지원자 화면에 점수·역량·관리자 지표가 없다.
- [ ] AI 동료와 AI 어시스턴트가 명확히 구분된다.
- [ ] AI 결과에 출처 또는 출처 없음이 명확하다.
- [ ] 승인 전 문서가 변경된 것처럼 보이지 않는다.
- [ ] 저장 완료가 성공 응답 전에 표시되지 않는다.
- [ ] 저장 실패와 버전 충돌에서 사용자 입력이 보존된다.
- [ ] 5개 문서 섹션의 화면 순서와 내부 ID mapping이 정확하다.
- [ ] 빈 섹션이 있어도 확인 후 제출 가능하다.
- [ ] 제출 후 모든 write UI가 읽기 전용으로 바뀐다.
- [ ] 관리자 리포트에 score/rank/pass/fail이 없다.
- [ ] 리포트의 사실과 AI 추정이 시각적으로 분리된다.
- [ ] 1440px와 1024px에서 제출 버튼과 입력창이 가려지지 않는다.
- [ ] 키보드만으로 저장·승인·거절·제출·리포트 근거 열기가 가능하다.
- [ ] 상태가 색상만으로 전달되지 않는다.
- [ ] fixture/live/fallback 상태를 실제 상태와 다르게 표시하지 않는다.

---

## 11. Canonical Screen Copy

구현 중 문구가 화면마다 달라지는 것을 막기 위한 기준 문구다.

| 상황 | 문구 |
|---|---|
| 과제 시작 | `모아마켓 개선 프로젝트에 합류했습니다` |
| 동료 composer | `이도현 동료에게 조사나 업무를 요청하세요` |
| 어시스턴트 설명 | `자료를 찾고 내용을 이해하도록 돕습니다. 기획안이나 태스크를 직접 변경하지 않습니다.` |
| 저장 중 | `저장 중…` |
| 저장 완료 | `저장됨` |
| 저장 실패 | `저장하지 못했습니다. 작성한 내용은 이 브라우저에 남아 있습니다.` |
| 연결 복구 | `연결을 복구하고 있습니다. 저장된 작업은 유지됩니다.` |
| 조사 진행 | `자료를 확인하고 있어요.` |
| 승인 대기 | `문서 변경 승인이 필요합니다` |
| 승인 stale | `문서가 그 사이 변경되어 이 제안을 적용할 수 없습니다. 현재 내용은 유지했습니다.` |
| 빈 섹션 제출 | `비어 있는 섹션이 있습니다. 불완전한 상태로도 제출할 수 있습니다.` |
| 제출 확인 | `제출 후에는 문서와 진행 중 작업을 수정할 수 없습니다.` |
| 제출 완료 | `기획안이 제출되었습니다` |
| AI 실패 | `조사를 완료하지 못했습니다. 작성 중인 기획안은 저장되어 있습니다.` |
| 리포트 실패 | `리포트를 생성하지 못했습니다. 지원자 제출물은 안전하게 저장되어 있습니다.` |
| 리포트 한계 | `이 리포트는 단일 가상 과제에서 관찰된 행동을 정리하며 성격·채용 성과를 단정하지 않습니다.` |

---

## 12. Definition of Design-Complete

이 디자인 가이드 기준의 프론트엔드 구현이 완료되었다고 판단하려면 다음을 모두 만족해야 한다.

1. 지원자는 과제 안내를 다시 열고, 자료를 읽고, 팀 채팅과 별도 AI 어시스턴트를 구분해 사용할 수 있다.
2. 조사 진행·결과·출처·실패·재시도가 실제 run 상태와 일치한다.
3. 위임 제안 확인 전에는 태스크나 변경이 생성된 것처럼 보이지 않는다.
4. 승인 카드에 대상·변경 전후·범위·만료·승인·거절이 표시된다.
5. 5개 섹션을 직접 편집하고 저장 중/완료/실패/충돌 상태를 구분할 수 있다.
6. 빈 섹션 경고 후에도 사용자가 최종 제출을 결정할 수 있고, 제출 후에는 읽기 전용이 된다.
7. 관리자에게 세션 상태, 제출 snapshot, 활동 원문, 행동 근거 기반 리포트가 정보 위계에 맞게 제공된다.
8. 지원자 화면에는 평가 점수와 내부 관리자 지표가 노출되지 않는다.
9. 관리자 리포트에는 점수·순위·합불 판단이 없고 사실과 AI 추정이 분리된다.
10. 1440px/1024px, 키보드, 포커스, 상태 색상 외 전달, 입력 보존을 검증한다.


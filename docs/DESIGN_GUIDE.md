# Day Zero — Design Guide v2.0

작성 2026-10-20 · 대상: 핏모아 sc-a 시뮬레이션 프론트엔드(`frontend/`)

v1.0의 화면별 명세(5섹션 기획안, 어시스턴트 드로어, 2시간 타이머, 모아런 예시 문구 등)는 이전 시나리오 기준이라 제거했다. 이 문서는 **디자인 토큰과 공통 원칙·접근성 기준만** 유지한다. 현재 화면 구성과 필수 상태는 [PRD.md](PRD.md) 5장, 구현은 `frontend/src/app/**`와 `frontend/src/components/**`를 기준으로 한다. 토큰 원본은 `frontend/src/styles/tokens.css`(변경하지 않음)다.

## 1. Design Principles

### 1.1 전체 디자인 철학

1. **Workplace, not test interface**  
   지원자 화면은 평가 플랫폼보다 실제 회사의 프로젝트 워크스페이스처럼 느껴져야 한다. “시험”, “평가 중”, “점수” 같은 표현은 입장 동의와 제출 안내에 필요한 범위 외에는 사용하지 않는다.

2. **Candidate owns the decision**  
   AI 동료의 수정안은 지원자가 승인해야 반영된다. 수정안은 항상 대상, 변경 전후, 승인 행동과 함께 표시한다. “자동 반영”처럼 통제권이 사라지는 표현을 피한다.

3. **Evidence before decoration**  
   문서 출처, 변경 전후, 저장 상태를 장식보다 우선한다. 카드 구분은 얇은 테두리와 공간으로 해결하고 과한 그림자·그라데이션은 쓰지 않는다.

4. **Calm, legible progress**  
   AI 답장은 불확실한 대기다. 과장된 애니메이션 대신 명시적 상태 문구로 보여준다. 실패해도 입력과 저장된 작업이 보존됨을 알린다.

5. **One brand, two densities**  
   지원자와 관리자는 동일한 색·타입·컴포넌트 언어를 공유한다. 지원자는 집중과 몰입을 위해 낮은 정보 밀도, 관리자는 탐색과 비교를 위해 중간~높은 정보 밀도를 사용한다.

6. **State is never color-only**  
   성공·경고·오류·진행 상태는 아이콘, 텍스트, 형태를 함께 사용한다. 색만으로 상태를 구분하지 않는다.

### 1.2 화면별 원칙(현재 구현)

- 지원자 화면은 3단 작업 공간이다: 좌측 공유 문서·태스크 보드, 중앙 팀 메신저, 우측 내 산출물. 상단에는 가상 시각만 표시하고 남은 시간 압박 요소는 두지 않는다.
- 팀장·AI 동료·시스템 알림을 이름·배지·아바타·메시지 형태로 구분한다.
- 서윤의 수정안은 승인 카드(변경 전 ↔ 수정안)로만 산출물에 반영된다.
- 관리자 리포트는 "관련 이벤트 → 관찰 코드와 정의 → 근거 원문(메시지·diff·행동)" 순서를 유지하고, 시스템 기록과 AI 요약을 시각적으로 분리한다. 점수·순위·합불 추천·성격 판정을 만들지 않는다.

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

---

## 3. Accessibility

### 3.1 Contrast

- 일반 텍스트 WCAG AA 4.5:1 이상, 큰 텍스트 3:1 이상을 목표로 한다.
- `#16181D` 배경에는 `#F8F9FA` 텍스트를 사용한다.
- Muted text는 흰 배경에서 작은 장문 본문에 사용하지 않는다.
- focus indicator와 컴포넌트 경계는 인접 색 대비 3:1을 목표로 한다.

### 3.2 Keyboard

- 모든 기능은 키보드로 실행 가능해야 한다.
- Tab 순서는 시각 순서와 일치한다.
- skip link: `주요 콘텐츠로 이동`, 지원자 화면은 추가로 `메시지 입력으로 이동` 제공.
- 채팅 입력 `Enter`/`Shift+Enter` 규칙을 근처 도움말 또는 `aria-describedby`로 제공한다.
- 보드 상태 변경은 drag 없이 버튼으로 가능해야 한다.
- modal/drawer는 focus trap과 focus return을 구현한다.
- 탭은 WAI-ARIA tabs keyboard pattern을 따른다.

### 3.3 Focus

- 모든 interactive 요소에 `:focus-visible` 링을 표시한다.
- 포커스 링이 overflow hidden으로 잘리지 않게 2px 여유를 둔다.
- 페이지 전환 후 H1 또는 주요 container로 focus를 이동한다.
- 오류 submit 후 첫 오류 필드 또는 오류 summary로 focus를 이동한다.

### 3.4 Screen readers and live regions

- 저장 상태: `aria-live="polite"`, 짧은 문구만 읽는다.
- 오류: `role="alert"`는 즉각 대응이 필요한 경우에만 사용한다.
- AI 진행 이벤트를 매번 모두 읽어 방해하지 않는다. 중요한 전환(`승인 필요`, `실패`)만 polite live region에 알린다.
- 새 채팅 메시지가 사용자의 읽기 위치를 강제로 이동시키지 않는다. 하단에 있을 때만 자동 스크롤하고, 위를 읽는 중이면 `새 메시지 2개` 버튼을 표시한다.
- 아이콘 버튼은 `aria-label`을 제공한다.
- 아바타 문자는 장식이면 `aria-hidden`; 작성자 이름은 텍스트로 제공한다.

### 3.5 Status semantics

- badge 텍스트 자체가 상태를 설명해야 한다.
- 성공 check, 경고 triangle, 오류 circle-x 등 형태를 함께 쓴다.
- diff는 색 외에 `추가됨`, `삭제됨` 레이블 또는 기호를 제공한다.
- chart를 추가한다면 동일 데이터를 표로 제공한다. P0 관리자 핵심 화면은 chart 없이도 완전해야 한다.

### 3.6 Language and time

- 문서 루트 `lang="ko"`.
- 시각 표시는 Asia/Seoul 기준, 예: `2026. 10. 20. 13:05`.
- 상대 시각에는 절대 시각을 tooltip 또는 accessible description으로 제공한다.

---

---

## 4. CSS variables

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

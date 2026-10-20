"""UI 확인: 실제 브라우저로 초대 → 입장 → E0 분업 → 정정 요청 → 승인 카드 → 업무 종료 → 디브리핑 → 관리자 리포트.

프로젝트 의존성에 넣지 않은 일회성 검증 스크립트다(시스템 Chrome 사용). 서비스가 떠 있는 상태에서:
  uv run --no-project --with playwright python evidence/ui_check.py "$PWD"
스크린샷은 evidence/screens/에 저장된다.
"""
import re
import sys
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

ROOT = Path(sys.argv[1])
OUT = ROOT / "evidence" / "screens"
OUT.mkdir(parents=True, exist_ok=True)
BASE = "http://localhost:3100"
env = dict(l.split("=", 1) for l in (ROOT / ".env").read_text().splitlines() if "=" in l and not l.startswith("#"))
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
errors: list[str] = []
results: list[tuple[str, bool]] = []


def check(name, ok):
    results.append((name, bool(ok))); print(("PASS " if ok else "FAIL ") + name, flush=True)


with sync_playwright() as p:
    b = p.chromium.launch(executable_path=CHROME, headless=True)
    adm = b.new_context(viewport={"width": 1440, "height": 900}, locale="ko-KR")
    ap = adm.new_page()
    r = ap.request.post(f"{BASE}/api/v1/auth/login", headers={"Origin": BASE},
                        data={"email": env["SEED_ADMIN_EMAIL"], "password": env["SEED_ADMIN_PASSWORD"]})
    csrf = r.json()["csrf_token"]
    url = ap.request.post(f"{BASE}/api/v1/invites", headers={"Origin": BASE, "X-CSRF-Token": csrf}, data={"alias": "UI 확인"}).json()["invite_url"]

    cand = b.new_context(viewport={"width": 1440, "height": 900}, locale="ko-KR")
    pg = cand.new_page()
    pg.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.on("response", lambda r: r.status >= 400 and print("  HTTP", r.status, r.url.replace(BASE, "")))
    pg.goto(url)
    expect(pg.get_by_role("heading", name="핏모아 운영팀 합류")).to_be_visible(timeout=20000)
    pg.screenshot(path=str(OUT / "01-join.png"))
    pg.get_by_role("checkbox").check()
    pg.get_by_role("button", name="작업 공간 입장").click()
    expect(pg.get_by_role("button", name="업무 시작하기")).to_be_visible(timeout=20000)
    pg.screenshot(path=str(OUT / "02-brief-modal.png"))
    pg.get_by_role("button", name="업무 시작하기").click()
    expect(pg.get_by_text("편한 쪽 먼저 골라주세요")).to_be_visible(timeout=10000)
    check("E0: 팀장 지시 + 서윤 분업 질문 + 분업 카드", pg.get_by_role("button", name="이렇게 나눠요").is_visible())
    check("상단 가상 시각 09:00", pg.get_by_text(re.compile(r"09:00 · 마감 17:00")).is_visible())
    pg.screenshot(path=str(OUT / "03-office-e0.png"))
    pg.get_by_role("button", name="이렇게 나눠요").click()
    expect(pg.get_by_text("좋아요, 그렇게 가요!")).to_be_visible(timeout=20000)
    check("분업 확정 → 서윤 답 + 확정 배지", pg.get_by_text("확정됨").first.is_visible())
    pg.get_by_role("tab", name="태스크 보드").click()
    pg.screenshot(path=str(OUT / "04-taskboard.png"))
    check("태스크 보드 T1~T3 담당 반영", pg.get_by_text("담당 나").first.is_visible() and pg.get_by_text("담당 한서윤").first.is_visible())
    pg.get_by_role("tab", name="공유 문서").click()
    pg.get_by_role("button", name=re.compile("리워드·일정 표")).click()
    expect(pg.get_by_text("11/2 ~ 11/31").first).to_be_visible(timeout=10000)
    pg.screenshot(path=str(OUT / "05-doc-reward-table.png"))
    pg.keyboard.press("Escape")
    box = pg.locator("#composer")
    box.fill("서윤 씨, 리워드 표 일정이 11/2 ~ 11/31인데 11월 31일은 없는 날짜예요. 브리프 기준으로 고쳐주실 수 있을까요?")
    box.press("Enter")
    expect(pg.get_by_text("바로 고칠게요").first).to_be_visible(timeout=30000)
    expect(pg.get_by_role("button", name="승인하고 반영")).to_be_visible(timeout=30000)
    check("정정 요청 → 서윤 인정 → 승인 카드(수정안 diff)", pg.get_by_text("서윤 님 수정안").is_visible())
    pg.screenshot(path=str(OUT / "06-approval-card.png"))
    pg.get_by_role("button", name="승인하고 반영").click()
    expect(pg.get_by_text("고쳤어요", exact=True)).to_be_visible(timeout=30000)
    pg.get_by_role("tab", name="T3").click()
    check("승인 후 T3 반영", "11/2 ~ 11/15" in pg.locator("#art-body-T3").input_value())
    pg.get_by_role("tab", name="T1").click()
    pg.locator("#art-body-T1").fill("핏모아 친구 초대 이벤트를 안내드립니다.")
    pg.get_by_role("button", name="저장").click()
    expect(pg.get_by_text("저장됨")).to_be_visible(timeout=10000)
    pg.screenshot(path=str(OUT / "07-office-after-fix.png"))
    pg.set_viewport_size({"width": 1024, "height": 768})
    pg.wait_for_timeout(800)  # 리사이즈 직후 중간 렌더 캡처 방지
    pg.screenshot(path=str(OUT / "08-office-1024.png"))
    pg.set_viewport_size({"width": 1440, "height": 900})
    pg.get_by_role("button", name="업무 종료").click()
    pg.get_by_role("dialog").get_by_role("checkbox").check()
    pg.get_by_role("dialog").get_by_role("button", name="업무 종료").click()
    expect(pg.get_by_text("의도된 연출")).to_be_visible(timeout=20000)
    pg.locator("#reflection").fill("근거를 들어 서윤 씨에게 정정을 요청했습니다.")
    pg.get_by_role("button", name="소감 남기기").click()
    expect(pg.get_by_text("소감을 남겼습니다")).to_be_visible(timeout=10000)
    check("디브리핑 문구 + 소감 저장", True)
    pg.screenshot(path=str(OUT / "09-debrief.png"))

    ap.goto(f"{BASE}/admin/sessions")
    expect(ap.get_by_text("UI 확인").first).to_be_visible(timeout=20000)
    ap.screenshot(path=str(OUT / "10-admin-sessions.png"))
    ap.get_by_role("link", name="리포트 열기").first.click()
    expect(ap.get_by_role("heading", name="역량별 관찰")).to_be_visible(timeout=30000)
    check("리포트: 5역량·관찰 코드·근거 원문", ap.get_by_text("CO+5").first.is_visible() and ap.get_by_text("관찰 기회 없음").first.is_visible())
    ap.screenshot(path=str(OUT / "11-report.png"), full_page=True)
    b.close()

bad = [e for e in errors if "favicon" not in e]
check("브라우저 콘솔 오류 없음", not bad)
for e in bad[:5]:
    print("  console:", e[:200])
print(f"\n결과: {sum(ok for _, ok in results)}/{len(results)} PASS")

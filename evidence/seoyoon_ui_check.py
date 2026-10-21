"""Isolated browser check; credentials stay in process memory."""
import re,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'services'))
from shared.config import settings
from playwright.sync_api import sync_playwright,expect
S=settings();BASE=S.app_origin
OUT=ROOT/'evidence/screens/seoyoon';OUT.mkdir(parents=True,exist_ok=True)
with sync_playwright() as p:
    browser=p.chromium.launch(executable_path='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',headless=True)
    admin=browser.new_context();page=admin.new_page()
    csrf=page.request.post(BASE+'/api/v1/auth/login',data={'email':S.seed_admin_email,'password':S.seed_admin_password},headers={'Origin':BASE}).json()['csrf_token']
    invite=page.request.post(BASE+'/api/v1/invites',data={'alias':'seoyoon-ui-synthetic'},headers={'Origin':BASE,'X-CSRF-Token':csrf}).json()['invite_url']
    candidate=browser.new_context(viewport={'width':1440,'height':900},locale='ko-KR');pg=candidate.new_page();errors=[]
    pg.on('pageerror',lambda error:errors.append(str(error)))
    pg.goto(invite)
    expect(pg.get_by_role('checkbox')).to_be_visible(timeout=20000)
    pg.get_by_role('checkbox').check();pg.get_by_role('button',name='작업 공간 입장').click()
    pg.get_by_role('button',name='업무 시작하기').click(timeout=20000)
    expect(pg.get_by_label(re.compile('남은 시간'))).to_be_visible()
    pg.screenshot(path=str(OUT/'01-clock.png'))
    before=pg.get_by_label(re.compile('남은 시간')).inner_text();pg.wait_for_timeout(1200)
    assert pg.get_by_label(re.compile('남은 시간')).inner_text()!=before
    pg.locator('#composer').fill('서윤님 초대 1명당 3000P로 표 금액 확인 부탁드립니다!');pg.locator('#composer').press('Enter')
    pg.get_by_role('tab',name='T3',exact=True).click()
    expect(pg.locator('#art-body-T3')).to_contain_text('') if False else None
    for _ in range(120):
        if '초대 1명당 3,000P' in pg.locator('#art-body-T3').input_value():break
        pg.wait_for_timeout(500)
    assert '초대 1명당 3,000P' in pg.locator('#art-body-T3').input_value()
    expect(pg.get_by_text('서윤 문서 수정 · v2',exact=True)).to_be_visible(timeout=10000)
    expect(pg.locator('.msg-body').filter(has_text=re.compile('수정했어요|고쳤어요')).last).to_be_visible(timeout=60000)
    pg.screenshot(path=str(OUT/'02-revision.png'))
    assert pg.locator('del').inner_text().find('5,000P')>=0
    assert pg.locator('ins').inner_text().find('3,000P')>=0
    pg.set_viewport_size({'width':1024,'height':768});pg.wait_for_timeout(500)
    pg.screenshot(path=str(OUT/'03-responsive.png'))
    # Shift via the same persisted clock used by backend regressions.
    import subprocess
    sid=pg.url.split('/office/')[1].split('?')[0]
    for _ in range(10):
        r=page.request.post(BASE+f'/api/v1/sessions/{sid}/demo/advance',headers={'Origin':BASE,'X-CSRF-Token':csrf})
        if r.status!=200:break
        snapshot=pg.request.get(BASE+f'/api/v1/sessions/{sid}').json()
        if 'E4' in snapshot['events']:break
    expect(pg.get_by_label(re.compile('남은 시간'))).to_have_class(re.compile('warning'),timeout=10000)
    pg.screenshot(path=str(OUT/'04-deadline-warning.png'))
    code="import sys;from shared.config import settings;from shared.db import tx;\nwith tx(settings().psycopg_dsn) as c:c.execute(\"UPDATE sessions SET clock_offset_seconds=3601-EXTRACT(EPOCH FROM(now()-started_at))::int WHERE id=%s\",(sys.argv[1],))"
    subprocess.run([str(ROOT/'services/.venv/bin/python'),'-c',code,sid],cwd=ROOT/'services',check=True)
    pg.wait_for_url(re.compile('/debrief/'),timeout=20000)
    pg.screenshot(path=str(OUT/'05-auto-debrief.png'))
    assert not errors,errors
    print('PASS browser: ticking remaining clock, immediate T3 edit, version/diff, responsive layout, 10 minute warning, auto-debrief, no page errors')
    browser.close()

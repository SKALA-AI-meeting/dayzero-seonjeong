from datetime import datetime, timedelta, timezone
from gateway.app.domain import elapsed_seconds
from gateway.app.engine import event_window

def test_real_clock_and_demo_offset():
    now = datetime.now(timezone.utc)
    assert elapsed_seconds({'started_at': now-timedelta(seconds=90), 'clock_offset_seconds': 30}, now) == 120
    assert elapsed_seconds({'started_at': None}, now) == 0

def test_event_windows_depend_on_actual_parent_occurrence():
    assert event_window({'trigger': {'kind':'time','open_at':10,'force_at':13}}, {}) == (600,780)
    e = {'trigger': {'kind':'after_event','event':'E2','open_after':5,'force_after':8}}
    assert event_window(e,{}) is None
    assert event_window(e,{'E2':{'elapsed_seconds':1450,'skipped':False}}) == (1750,1930)

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


def test_action_gate_forced_gate_and_e4(monkeypatch):
    from gateway.app import engine
    events = [
        {'id':'E1','trigger':{'kind':'time','open_at':10,'force_at':13}},
        {'id':'E4','trigger':{'kind':'time','open_at':50,'force_at':50}},
    ]
    occurrence={}; fired=[]; clock=[599]
    monkeypatch.setattr(engine,'elapsed_seconds',lambda s:clock[0])
    monkeypatch.setattr(engine,'occurred',lambda c,sid:dict(occurrence))
    def fire(c,s,ev,sc,mode='on_action'):
        occurrence[ev['id']]={'elapsed_seconds':clock[0],'skipped':False}
        fired.append((ev['id'],mode))
    monkeypatch.setattr(engine,'fire',fire)
    s={'id':'test','scenario_state':{},'turn_count':9999}
    for _ in range(30):assert engine.fire_due(None,s,{'events':events}) == []
    clock[0]=600
    assert engine.fire_due(None,s,{'events':events},on_action=False) == []
    assert engine.fire_due(None,s,{'events':events}) == ['E1']
    assert fired[-1]==('E1','on_action')
    occurrence.clear();clock[0]=780
    assert engine.fire_due(None,s,{'events':events},on_action=False)==['E1']
    assert fired[-1]==('E1','forced')
    clock[0]=3000
    assert engine.fire_due(None,s,{'events':events},on_action=False)==['E4']
    assert fired[-1]==('E4','forced')


def test_deadline_ends_even_while_approval_pending(monkeypatch):
    from gateway.app import engine
    monkeypatch.setattr(engine,'elapsed_seconds',lambda s:3600)
    ended=[]
    monkeypatch.setattr(engine,'end_session',lambda c,s,**kw:ended.append(kw))
    assert engine.tick(None,{'status':'ACTIVE'},on_action=False)==[]
    assert ended[0]['actor']=='SYSTEM'


def test_e4_bypasses_pending_run_but_other_events_wait(monkeypatch):
    from gateway.app import engine
    clock=[2999];fired=[]
    monkeypatch.setattr(engine,'elapsed_seconds',lambda s:clock[0])
    monkeypatch.setattr(engine,'one',lambda *a: {'pending':True})
    monkeypatch.setattr(engine,'scenario_def',lambda *a:{'events':[{'id':'E4'}]})
    monkeypatch.setattr(engine,'occurred',lambda *a:{})
    monkeypatch.setattr(engine,'fire',lambda c,s,ev,sc,mode:fired.append((ev['id'],mode)))
    session={'id':'test','status':'ACTIVE'}
    assert engine.tick(None,session,on_action=False)==[]
    clock[0]=3000
    assert engine.tick(None,session,on_action=False)==['E4']
    assert fired==[('E4','forced')]


def test_no_response_reminds_once_at_three_minutes_and_defaults_at_seven(monkeypatch):
    from gateway.app import engine
    clock=[179];reminders=[];codes=[];confirmed=[]
    monkeypatch.setattr(engine,'elapsed_seconds',lambda s:clock[0])
    monkeypatch.setattr(engine,'set_state',lambda c,s,st:s.update(scenario_state=st))
    monkeypatch.setattr(engine,'post_line',lambda *a,**k:reminders.append(k))
    monkeypatch.setattr(engine,'observe',lambda c,sid,code,*a,**k:codes.append(code))
    monkeypatch.setattr(engine,'record_action',lambda *a,**k:None)
    monkeypatch.setattr(engine,'default_split',lambda sc:{})
    monkeypatch.setattr(engine,'confirm_split',lambda *a,**k:confirmed.append(True))
    s={'id':'test','scenario_state':{'awaiting':{'event_id':'E0','since_seconds':0,'reminded':False}}}
    sc={'events':[{'id':'E0'}],'no_response_policy':{'remind_after_minutes':3,'advance_after_minutes':4}}
    engine.no_response(None,s,sc);assert not reminders
    for at in (180,181,419):
        clock[0]=at;engine.no_response(None,s,sc)
    assert len(reminders)==1 and not confirmed
    clock[0]=420;engine.no_response(None,s,sc)
    assert confirmed==[True] and codes==['RS-3'] and s['scenario_state']['awaiting'] is None

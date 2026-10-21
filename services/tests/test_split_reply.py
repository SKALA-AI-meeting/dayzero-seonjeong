import pytest
from agent.app import graph as g
from agent.app.split_reply import assignment_text, split_violations, split_context

P={'T1':'COLLEAGUE','T3':'CANDIDATE','faq_candidate':3}


def state(confirmed=True, run_type='split', text=''):
    return {'run_type':run_type,'text':text,'ctx':{'state':{'split':{'confirmed':confirmed,'proposal':P}},'tasks':[]}}


def test_reported_rehearsal_is_rejected():
    bad='제가 T2 FAQ 5개와 T3를 맡고 있어요. 제가 FAQ 3개와 리워드 표를 맡고, 동료분이 FAQ 2개는 어떨까요?'
    problems=split_violations(bad,state())
    assert 'ownership_differs_from_confirmed_split' in problems
    assert 'unsolicited_renegotiation' in problems
    assert not split_violations('넵, 확정된 담당은 '+assignment_text(P)+'예요.',state())


def test_pushback_cannot_confirm_or_claim_provisional_owner():
    assert split_context(state(False)['ctx'])['status']=='임시(미확정)'
    assert 'pushback_must_remain_unconfirmed' in split_violations('넵 확정했어요.',state(False))
    assert not split_violations('앗, 분량을 조금 조정해 주실 수 있을까요?',state(False))
    assert 'provisional_ownership_claimed_as_final' in split_violations('제가 T3를 맡고 있어요.',state(False,'message'))


def test_do_not_reopen_after_confirmation_unless_candidate_requests_change():
    text='제가 FAQ 3개와 리워드 표를 맡으면 어떨까요?'
    assert 'unsolicited_renegotiation' in split_violations(text,state(True,'message','감사합니다'))
    assert not split_violations(text,state(True,'message','분업을 다시 바꾸고 싶어요'))


def test_decision_and_refreshed_context_precede_generation(monkeypatch):
    old=state(False);old.update(run_id='run',event_id='E0',label='BALANCED_SPLIT',effects={'split':{'confirm':True,'proposal':P}})
    order=[]
    class Gateway:
        def post(self,path,body):order.append('decision')
        def get(self,path):
            assert order==['decision'];order.append('refresh');return state(True)['ctx']
    monkeypatch.setattr(g,'gw',Gateway())
    result=g.apply_effects(old)
    assert result['ctx']['state']['split']['confirmed']
    assert result['ctx']['state']['split']['proposal']==P
    assert order==['decision','refresh']


@pytest.mark.parametrize('proposal,allow,round_,expected',[
    (P,True,1,'ACCEPT'),
    ({'T1':'COLLEAGUE','T3':'COLLEAGUE','faq_candidate':1},True,1,'PUSHBACK'),
    ({'T1':'COLLEAGUE','T3':'COLLEAGUE','faq_candidate':1},False,2,'ACCEPT'),
    ({'T1':'CANDIDATE','T3':'CANDIDATE','faq_candidate':5},True,1,'PUSHBACK'),
    (P,True,4,'DEFAULT'),
])
def test_system_decides_split_without_llm(proposal,allow,round_,expected):
    s={'ctx':{'run':{'input':{'proposal':proposal,'round':round_,'action_id':'action'}},
              'state':{'split':{}},'allow_pushback':{'E0':allow},'event':{},'scenario':{}}}
    result=g.negotiate(s)
    assert result['split_decision']['decision']==expected
    assert result['effects']['split']['confirm']==(expected!='PUSHBACK')
    if expected=='DEFAULT':assert result['effects']['split']['proposal']!=P


@pytest.mark.parametrize('text',['T3는 제가 담당해요.', '안내문은 지원자님 담당이에요.', 'FAQ 서윤 5개예요.'])
def test_object_first_ownership_claims_are_checked(text):
    assert 'ownership_differs_from_confirmed_split' in split_violations(text,state(True,'message','담당을 확인해 주세요'))


@pytest.mark.parametrize('confirmed,bad',[(True,'제가 FAQ 5개와 T3를 맡으면 어떨까요?'),(False,'넵 확정했어요.')])
def test_validator_regenerates_then_falls_back_to_the_system_decision(monkeypatch,confirmed,bad):
    monkeypatch.setattr(g,'_secrets',lambda state:[])
    monkeypatch.setattr(g.S,'llm_mode','live')
    s=state(confirmed);s['ctx']['messages']=[]
    s.update(answer=bad,answer_actor='COLLEAGUE',output_rewrite_count=0,tool_results=[])
    retry=g.validate_output(s)
    assert retry['error_code']=='OUTPUT_RETRY' and g.after_validation(retry)=='reason'
    s['output_rewrite_count']=2
    final=g.validate_output(s)
    assert not split_violations(final['answer'],s)
    assert (assignment_text(P) in final['answer'])==confirmed


def test_natural_object_first_confirmation_is_not_false_positive():
    text='앗, 확인해주셔서 감사해요. T1 안내문은 한서윤님이 맡고, T3 리워드 표는 지원자가 담당하며, FAQ는 지원자 3개와 한서윤님 2개로 진행됩니다.'
    assert not split_violations(text,state())


def test_generation_context_has_human_owners_and_both_faq_counts():
    from agent.app.split_reply import split_prompt_context
    import json
    s=state();s['split_decision']={'decision':'ACCEPT'}
    payload=json.dumps(split_prompt_context(s),ensure_ascii=False)
    assert 'COLLEAGUE' not in payload and 'CANDIDATE' not in payload
    assert 'FAQ 지원자 3개·한서윤 2개' in payload

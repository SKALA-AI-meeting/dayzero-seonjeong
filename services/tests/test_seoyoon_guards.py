from shared.scenario import targets_in, contextual_targets, claim_kind
from agent.app.graph import action_violations

def test_reward_and_date_spellings():
    for text in ['3000P', '3,000p', '3천 포인트', '5000포인트', '5000점']:
        assert 'PE-2' in targets_in(text)
    for text in ['11/31','11월 31일','31일']:
        assert 'PE-1' in targets_in(text)

def test_recent_context_and_wrong_criticism():
    recent = [{'actor':'CANDIDATE','content':'리워드 일정표에는 5000포인트로 되어있어서요!'}]
    assert contextual_targets('제가 아까 말한게 그거예요',recent) == ['PE-2']
    assert claim_kind('동일 결제수단 제외가 잘못된 것 같아요') == 'WRONG'
    assert contextual_targets('동일 결제수단 제외가 잘못된 것 같아요',recent) == []

def test_promises_require_matching_successful_action():
    assert action_violations('수정할게요!',[]) == ['promise_without_edit']
    assert action_violations('확인할게요!',[]) == ['promise_without_read_and_opinion']
    assert not action_violations('수정했어요!', [{'tool':'edit_own_artifact','payload':{'ok':True}}])
    assert action_violations('고칠게요!', [{'tool':'read_artifact','payload':{'ok':True}}])


def test_correct_amount_criticized_is_not_a_valid_correction():
    assert claim_kind('초대자 3000포인트가 잘못된 것 같아요') == 'WRONG'
    assert claim_kind('5000포인트로 바꿔 주세요') == 'WRONG'
    assert claim_kind('리워드 일정표에는 5000포인트로 되어있어서요!') == 'SPECIFIC'


def test_clarification_topic_survives_beyond_recent_messages(monkeypatch):
    from agent.app import graph as g
    monkeypatch.setattr(g,'_secrets',lambda state:[])
    monkeypatch.setattr(g.S,'llm_mode','fixture')
    state={'text':'뭔가 이상해요','event_id':'E1','targets':[], 'answer':'앗, 어느 부분인지 알려주실 수 있을까요?',
           'answer_actor':'COLLEAGUE','output_rewrite_count':2,'tool_results':[],
           'ctx':{'messages':[],'state':{'clarification_topics':['E1:general']}}}
    result=g.validate_output(state)
    assert not g.CLARIFY.search(result['answer'])

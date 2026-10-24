import copy
import json
import asyncio
from decimal import Decimal
import pytest
from sqlalchemy import select,func
from app.models import DecisionCase,DiscussionRun,User,Scenario,ERPRecord,ExternalSource,AuditEvent
from app.db import SessionLocal
from app.services import decision_memory as memory,discussions
from app.services.erp import snapshot
from app.services.planning import evaluate
from test_approvals import recommendation
from test_workspace_integration import ready,command
from test_discussions import configure_review_provider,review_turn

API='/api/v1'


def real_case(client,po='past-1',actor_email='approver@example.test'):
    client.get(API+'/scenarios/scenario_1')
    with SessionLocal() as db:
        state=snapshot(db,'scenario_1');state['is_synthetic']=False;state['source_kind']='actual';state['source_evidence_refs']=['ERP:import:actual-fixture']
        from app.config import COLLECTIONS
        for key in COLLECTIONS:
            for row in state.get(key,[]): row['is_synthetic']=False;row.pop('source_kind',None)
        # Explicit complete specification is required before comparing cases.
        for m in state['materials']:
            m.update(product_code=m.get('product_code') or m['code'],content_per_vial=m.get('content_per_vial') or '100 units',grade=m.get('grade') or 'grade-a')
        calculation=evaluate(state,as_of='2026-10-24')
        selected=next(c for c in calculation['candidates'] if c['validation']['hard_constraints_passed'] and c['validation']['target_delivery_met'] and not c['validation']['requires_budget_approval'])
        user=db.scalar(select(User).where(User.email==actor_email))
        row=memory.capture(db,user,'scenario_1',po,state,calculation,selected,'납기와 분할 조건을 확인하고 선택')
        db.commit();return row.id,copy.deepcopy(row.decision['context'])


def outcome(client,case_id,revision=0,**values):
    return client.put(API+'/decision-cases/'+case_id+'/outcome',json={'expected_revision':revision,'source_kind':'real','evidence_refs':['GRN:1'],'change_reason':'담당자 실측 결과 기록',**values})


def test_native_approval_records_ids_reason_and_immutable_run_snapshot(client):
    rec_id,state=recommendation(client)
    body={'expected_revision':state['revision'],'acknowledge_unverified':True,'decision_reason':'품질 승인과 납기를 확인한 선택'}
    first=client.post(API+'/recommendations/'+rec_id+'/approve',json=body,headers={'Idempotency-Key':'capture-once'})
    assert first.status_code==200,first.text
    assert client.post(API+'/recommendations/'+rec_id+'/approve',json=body,headers={'Idempotency-Key':'capture-once'}).status_code==200
    cases=client.get(API+'/decision-cases?include_demo=true').json();assert len(cases)==1
    row=cases[0];assert row['po_id']==first.json()['id'] and row['decision']['recommendation_id']==rec_id
    assert row['decision']['analysis_run_id'] and row['decision']['approval_id']
    assert row['decision']['selection_reason']==body['decision_reason'] and row['source_kind']=='demo'
    before=client.get(API+'/decision-cases/'+row['id']).json()['decision']['erp_snapshot']
    material=state['materials'][0]
    changed=client.patch(API+'/scenarios/scenario_1/materials/'+material['id'],json={'revision':material['revision'],'name':'새 이름'})
    assert changed.status_code==200
    after=client.get(API+'/decision-cases/'+row['id']).json()['decision']['erp_snapshot']
    assert after==before


def test_failed_approval_leaves_no_case(client):
    rec_id,state=recommendation(client)
    response=client.post(API+'/recommendations/'+rec_id+'/approve',json={'expected_revision':state['revision']+1,'acknowledge_unverified':True},headers={'Idempotency-Key':'stale-case'})
    assert response.status_code==409
    with SessionLocal() as db: assert db.scalar(select(func.count()).select_from(DecisionCase))==0


def test_workspace_case_is_demo_and_tracking_observations_are_not_real(client):
    current=command(client,ready(client),'registerPO',decision_reason='가상 B 분할 시연')
    rows=client.get(API+'/decision-cases?include_demo=true').json();assert len(rows)==1
    row=rows[0];assert row['source_kind']=='demo' and row['decision']['selection_reason']=='가상 B 분할 시연'
    assert client.get(API+'/decision-cases').json()==[]
    assert outcome(client,row['id'],actual_purchase_cost=0).status_code==422
    order=current['workflow']['orders'][0]
    for _ in range(2): current=command(client,current,'trackNext',po=order['id'],line=order['lines'][0]['id'])
    detail=client.get(API+'/decision-cases/'+row['id']).json()
    assert detail['observations']['source_kind']=='demo'
    assert detail['observations']['receipts'][0]['actual_arrival']
    assert not detail['outcome']['confirmed'] and detail['outcome']['actual_total'] is None
    assert detail['observations']['receipts'][0]['line_id']==row['decision']['selected']['deliveries'][0]['id']
    saved=outcome(client,row['id'],source_kind='demo',actual_purchase_cost=0,receipts=detail['observations']['receipts'])
    assert saved.status_code==200,saved.text
    assert not saved.json()['outcome']['confirmed']


def test_missing_zero_cost_and_disposal_are_distinct_and_audited(client):
    case_id,context=real_case(client)
    assert client.get(API+'/decision-cases/'+case_id).json()['outcome']['actual_total'] is None
    first=outcome(client,case_id,actual_purchase_cost='0')
    assert first.status_code==200,first.text
    assert first.json()['outcome']['values']['actual_purchase_cost']=='0'
    assert first.json()['outcome']['actual_total'] is None
    assert 'actual_transport_cost' in first.json()['outcome']['unknown_fields']
    values={key:'0' for key in ('actual_purchase_cost','actual_transport_cost','actual_testing_cost','actual_storage_cost','actual_disposal_cost')}
    values.update(actual_purchase_cost='100.10',actual_disposal_cost='3.20',expired_quantity=10,production_delayed=False,production_delay_days=0)
    second=outcome(client,case_id,1,**values);assert second.status_code==200,second.text
    assert Decimal(second.json()['outcome']['actual_total'])==Decimal('103.30')
    assert second.json()['outcome']['confirmed']
    assert outcome(client,case_id,1,actual_purchase_cost=1).status_code==409
    history=client.get(API+'/decision-cases/'+case_id+'/history').json();assert len(history)==2
    assert history[1]['before']['outcome']['actual_purchase_cost']=='0'
    assert 'savings' not in second.json()['outcome']


def test_other_users_cannot_read_write_history_or_personal_stats(client):
    case_id,context=real_case(client)
    assert outcome(client,case_id,notes='owner-private-result',actual_purchase_cost=0).status_code==200
    client.post(API+'/auth/logout');assert client.get(API+'/decision-cases').status_code==401
    client.post(API+'/auth/login',json={'email':'operator@example.test','password':'test-only-operator-password'})
    assert client.get(API+'/decision-cases').json()==[]
    for path in ('','/history'): assert client.get(API+'/decision-cases/'+case_id+path).status_code==404
    assert outcome(client,case_id,1,actual_purchase_cost=99).status_code==404
    logs=client.get(API+'/scenarios/scenario_1/audit').json()
    assert all(not x['action'].startswith('decision.') for x in logs)
    assert 'owner-private-result' not in json.dumps(logs)
    with SessionLocal() as db:
        user=db.scalar(select(User).where(User.email=='operator@example.test'))
        assert memory.search(db,user.id,context)['preference']['case_count']==0


def test_similarity_normalizes_and_rejects_incomparable_specs(client,monkeypatch):
    case_id,current=real_case(client)
    settings=memory.policy();assert memory.similarity(current,current,settings)['similarity']==1
    changed=copy.deepcopy(current);changed['features']['production_days']+=30
    result=memory.similarity(current,changed,settings)
    assert result['similarity']>0.7 and result['similarity']<1
    assert any(x['feature']=='production_days' and x['score']==0 for x in result['explanation'])
    for key,value in [('unit','kg'),('material','OTHER')]:
        other=copy.deepcopy(current);other['identity'][key]=value;assert memory.similarity(current,other,settings) is None
    other=copy.deepcopy(current);other['identity']['spec']['content_per_vial']='different';assert memory.similarity(current,other,settings) is None
    other=copy.deepcopy(current);other['features']={key:None for key in other['features']};assert memory.similarity(current,other,settings) is None
    monkeypatch.setenv('BIOFLOW_CASE_WEIGHTS','{"production_days":10}')
    assert memory.similarity(current,changed,memory.policy())['similarity']<result['similarity']
    monkeypatch.setenv('BIOFLOW_CASE_SCALES','{"production_days":0}')
    with pytest.raises(Exception) as failure: memory.policy()
    assert failure.value.status_code==503


def test_outcomes_never_change_similarity_or_turn_preference_into_performance(client):
    case_id,current=real_case(client)
    with SessionLocal() as db:
        user=db.scalar(select(User).where(User.email=='approver@example.test'))
        before=memory.search(db,user.id,current)
    assert before['preference']['case_count']==1 and before['performance']['confirmed_outcome_count']==0
    assert outcome(client,case_id,evaluation='좋음이라는 의견만 입력').status_code==200
    with SessionLocal() as db:
        after=memory.search(db,user.id,current)
    assert after['cases'][0]['similarity']==before['cases'][0]['similarity']
    assert after['performance']['confirmed_outcome_count']==0
    assert after['advisory_only'] and after['training_performed'] is False


def test_empty_real_history_and_demo_inclusion_do_not_pollute_statistics(client):
    current=command(client,ready(client),'registerPO')
    real=client.get(API+'/decision-memory/similar?scenario_id=main-workspace').json()
    assert real['message']=='참고할 과거 사례 없음' and real['preference']['case_count']==0
    included=client.get(API+'/decision-memory/similar?scenario_id=main-workspace&include_demo=true').json()
    assert included['preference']['case_count']==0 and included['performance']['confirmed_outcome_count']==0
    assert included['reuse_authorized'] is False
    assert client.get(API+'/decision-memory/similar?scenario_id=main-workspace&expected_stamp=wrong').status_code==409


def test_outcome_requires_evidence_and_consistent_dates_and_delay(client):
    case_id,_=real_case(client)
    assert outcome(client,case_id,evidence_refs=[],used_quantity=0).status_code==422
    assert outcome(client,case_id,change_reason=' ').status_code==422
    assert outcome(client,case_id,production_delayed=False,production_delay_days=3).status_code==422
    assert outcome(client,case_id,actual_purchase_cost=-1).status_code==422
    line=client.get(API+'/decision-cases/'+case_id).json()['decision']['selected']['deliveries'][0]
    receipts=[{'line_id':line.get('id') or line.get('lot_code'),'actual_arrival':'2026-11-04','usable_date':'2026-11-03'}]
    assert outcome(client,case_id,receipts=receipts).status_code==422


def test_orchestrator_memory_is_advisory_and_not_a_current_candidate(client):
    case_id,current=real_case(client)
    with SessionLocal() as db:
        user=db.scalar(select(User).where(User.email=='approver@example.test'));past=memory.search(db,user.id,current)
    candidates=[{'id':'current-invalid','material_id':'m','validation':{'hard_constraints_passed':False,'target_delivery_met':False},'costs':{}}]
    context=discussions.orchestrator_context({}, {'candidates':candidates}, [], [],past)
    assert context['historical_decision_memory']['cases'][0]['id']==case_id
    assert context['registered_candidates']==candidates
    assert context['registered_candidates'][0]['validation']['hard_constraints_passed'] is False
    assert past['cases'][0]['decision']['selected']['id'] not in [x['id'] for x in context['registered_candidates']]
    assert '우회하지' in context['history_use_policy']


def test_private_memory_run_endpoints_are_owner_scoped(client):
    client.get(API+'/scenarios/scenario_1')
    with SessionLocal() as db:
        owner=db.scalar(select(User).where(User.email=='approver@example.test'))
        run=DiscussionRun(actor_id=owner.id,scenario_id='scenario_1',snapshot_revision=1,snapshot={},calculation={},status='failed',progress={})
        db.add(run);db.commit();run_id=run.id
    client.post(API+'/auth/logout');client.post(API+'/auth/login',json={'email':'operator@example.test','password':'test-only-operator-password'})
    for suffix in ('','/snapshot','/events'): assert client.get(API+'/discussions/'+run_id+suffix).status_code==404
    assert client.get(API+'/scenarios/scenario_1/discussions').json()==[]



def test_native_actual_records_are_collected_without_estimate_fallback(client):
    case_id,_=real_case(client)
    with SessionLocal() as db:
        case=db.get(DecisionCase,case_id);selected=case.decision['selected'];material_id=case.decision['context']['material_id'];line=selected['deliveries'][0]
        lot_id='actual-lot'
        value={'id':lot_id,'material_id':material_id,'code':line.get('lot_code'),'lot_code':line.get('lot_code'),'source_kind':'actual','is_synthetic':False,'evidence_refs':['LOT:actual'], 'actual_arrival_date':'2026-10-29','qa_release_date':'2026-11-01','actual_remaining_quantity':2,'actual_expired_quantity':0}
        db.add(ERPRecord(scenario_id=case.scenario_id,collection='lots',record_id=lot_id,revision=1,data=value))
        db.add(ERPRecord(scenario_id=case.scenario_id,collection='consumptions',record_id='used',revision=1,data={'id':'used','lot_id':lot_id,'quantity':'4','source_kind':'actual','evidence_refs':['USE:1']}))
        db.add(ERPRecord(scenario_id=case.scenario_id,collection='consumptions',record_id='fake',revision=1,data={'id':'fake','lot_id':lot_id,'quantity':'999','source_kind':'simulation','evidence_refs':['SIM']}))
        expected={x['production_plan_id']:x['use_date'] for x in case.decision['erp_snapshot']['requirements'] if x['material_id']==material_id}
        for record in db.scalars(select(ERPRecord).where(ERPRecord.scenario_id==case.scenario_id,ERPRecord.collection=='production_plans')):
            if record.record_id in expected: record.data={**record.data,'source_kind':'actual','is_synthetic':False,'evidence_refs':['PROD:1'],'actual_start_date':expected[record.record_id]}
        db.commit()
    collected=client.get(API+'/decision-cases/'+case_id).json()['observations']
    assert collected['values']['used_quantity']==4 and collected['values']['remaining_quantity']==2
    assert collected['values']['expired_quantity']==0 and collected['values']['production_delayed'] is False
    assert collected['values']['production_delay_days']==0
    assert collected['values'].get('actual_purchase_cost') is None
    assert collected['receipts'][0]['actual_arrival']=='2026-10-29'
    assert 'SIM' not in collected['evidence_refs'] and collected['field_sources']['used_quantity']
    assert client.get(API+'/decision-cases/'+case_id).json()['outcome']['values']=={}


def test_worker_passes_private_memory_only_to_orchestrator(client,monkeypatch):
    case_id,current=real_case(client)
    with SessionLocal() as db:
        owner=db.scalar(select(User).where(User.email=='approver@example.test'))
        expected=memory.search(db,owner.id,current)
    configure_review_provider(monkeypatch,1)
    from test_discussions import create_review
    queued=create_review(client)
    called=[]
    def retrieve(db,actor,data,calculation):
        assert actor==owner.id
        assert data['revision']==queued['snapshot_revision']
        return expected
    monkeypatch.setattr(memory,'memory_for',retrieve)
    async def generate(role,messages,schema):
        context=json.loads(messages[-1]['content']);called.append(role)
        if role=='orchestrator':
            assert context['historical_decision_memory']['cases'][0]['id']==case_id
            valid=next(c['id'] for c in context['registered_candidates'] if c['validation']['hard_constraints_passed'] and c['validation']['target_delivery_met'])
            return review_turn(role,context,[valid])
        assert 'historical_decision_memory' not in context
        return review_turn(role,context)
    monkeypatch.setattr(discussions,'generate_json',generate)
    asyncio.run(discussions.run_discussion(queued['id']))
    result=client.get(API+'/discussions/'+queued['id']).json()
    assert result['status']=='awaiting_review',result.get('error')
    assert called[-1]=='orchestrator'
    assert any(x['type']=='case_memory' for x in result['events'])
    assert all(x['candidate']['validation']['hard_constraints_passed'] for x in result['recommendations'])


def test_past_selection_cannot_override_current_approval_constraints(client):
    real_case(client)
    rec_id,state=recommendation(client)
    offer=state['offers'][0]
    changed=client.patch(API+'/scenarios/scenario_1/offers/'+offer['id'],json={'revision':offer['revision'],'confirmed':False})
    assert changed.status_code==200
    result=client.post(API+'/recommendations/'+rec_id+'/approve',json={'expected_revision':state['revision'],'acknowledge_unverified':True},headers={'Idempotency-Key':'past-cannot-authorize'})
    assert result.status_code==409
    assert len(client.get(API+'/decision-cases').json())==1
    with SessionLocal() as db:
        assert not db.scalar(select(ERPRecord).where(ERPRecord.scenario_id=='scenario_1',ERPRecord.collection=='purchase_orders'))



def test_private_analysis_cannot_be_adopted_into_another_users_workspace(client):
    from app.models import Recommendation
    current=ready(client)
    with SessionLocal() as db:
        operator=db.scalar(select(User).where(User.email=='operator@example.test'))
        run=DiscussionRun(actor_id=operator.id,scenario_id='main-workspace',snapshot_revision=current['revision'],snapshot={},calculation={},status='awaiting_review',progress={})
        db.add(run);db.flush()
        rec=Recommendation(run_id=run.id,scenario_id='main-workspace',snapshot_revision=current['revision'],candidate_id='private-candidate',data={},status='proposed')
        db.add(rec);db.commit();rec_id=rec.id
    denied=client.post(API+'/workspace/adopt-review',json={'recommendation_id':rec_id,'expected_revision':current['revision'],'stamp':current['stamp']})
    assert denied.status_code==409

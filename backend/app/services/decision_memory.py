"""Retrieval of recorded decisions, not model training. No approval authority."""
import copy
import json
import math
from typing import Annotated
from datetime import date
from decimal import Decimal,InvalidOperation
from collections import Counter
from fastapi import HTTPException
from pydantic import Field
from sqlalchemy import select,update
from ..models import DecisionCase,DiscussionRun,ERPRecord,AuditEvent,now,utc_iso,uid
from ..schemas import StrictModel
from ..config import setting
from .erp import audit

COSTS=('purchase','transport','testing','storage','disposal')
MEASUREMENTS=tuple('actual_'+x+'_cost' for x in COSTS)+('used_quantity','remaining_quantity','expired_quantity','production_delay_days','production_delayed')
DEFAULT_WEIGHTS={'production_days':1,'inventory_ratio':1,'budget_margin':1,'supply_confirmation':1,'expiry_days':1,'quote_validity_days':1,'waste_ratio':1}
DEFAULT_SCALES={'production_days':30,'inventory_ratio':1,'budget_margin':1,'supply_confirmation':1,'expiry_days':90,'quote_validity_days':30,'waste_ratio':1}


class ReceiptOutcome(StrictModel):
    line_id: str = Field(min_length=1,max_length=100)
    actual_arrival: date | None = None
    usable_date: date | None = None


class OutcomeInput(StrictModel):
    expected_revision: int = Field(ge=0)
    source_kind: str = Field(pattern='^(real|demo)$')
    receipts: list[ReceiptOutcome] = Field(default_factory=list,max_length=100)
    actual_purchase_cost: Decimal | None = Field(default=None,ge=0,le=Decimal("1e15"),max_digits=24,decimal_places=6,allow_inf_nan=False)
    actual_transport_cost: Decimal | None = Field(default=None,ge=0,le=Decimal("1e15"),max_digits=24,decimal_places=6,allow_inf_nan=False)
    actual_testing_cost: Decimal | None = Field(default=None,ge=0,le=Decimal("1e15"),max_digits=24,decimal_places=6,allow_inf_nan=False)
    actual_storage_cost: Decimal | None = Field(default=None,ge=0,le=Decimal("1e15"),max_digits=24,decimal_places=6,allow_inf_nan=False)
    actual_disposal_cost: Decimal | None = Field(default=None,ge=0,le=Decimal("1e15"),max_digits=24,decimal_places=6,allow_inf_nan=False)
    used_quantity: float | None = Field(default=None,ge=0,le=1e12,allow_inf_nan=False)
    remaining_quantity: float | None = Field(default=None,ge=0,le=1e12,allow_inf_nan=False)
    expired_quantity: float | None = Field(default=None,ge=0,le=1e12,allow_inf_nan=False)
    production_delayed: bool | None = None
    production_delay_days: int | None = Field(default=None,ge=0,le=36500)
    evaluation: str | None = Field(default=None,max_length=1000)
    notes: str | None = Field(default=None,max_length=4000)
    evidence_refs: list[Annotated[str,Field(min_length=1,max_length=500)]] = Field(default_factory=list,max_length=100)
    change_reason: str = Field(min_length=1,max_length=1000)


def number(value):
    try:
        n=float(value)
        return n if math.isfinite(n) else None
    except (ValueError,TypeError):
        return None


def days(end,start):
    try: return (date.fromisoformat(str(end)[:10])-date.fromisoformat(str(start)[:10])).days
    except (ValueError,TypeError): return None


def context(data,calculation,material_id=None):
    projections=calculation.get('materials',[])
    p=next((x for x in projections if x.get('material_id')==material_id),None) if material_id else next((x for x in projections if (number(x.get('new_order_quantity')) or 0)>0),None)
    p=p or (projections[0] if projections else {})
    mid=material_id or p.get('material_id')
    m=next((m for m in data.get('materials',[]) if m['id']==mid),{})
    spec={k:str(m.get(k) or '').strip().casefold() for k in ('product_code','manufacturer','formulation','content_per_vial','grade')}
    identity={'material':m.get('code') or m.get('id'),'spec':spec,'unit':m.get('base_unit'),'currency':m.get('currency',data.get('currency','KRW'))}
    candidates=[x for x in calculation.get('candidates',[]) if x.get('material_id')==mid]
    eligible=[x for x in candidates if x.get('validation',{}).get('hard_constraints_passed') and x['validation'].get('target_delivery_met') and x['validation'].get('cash_feasible',True)]
    costs=[number(x.get('costs',{}).get('total')) for x in eligible]
    costs=[x for x in costs if x is not None]
    budgets=[x for x in data.get('budgets',[]) if not x.get('payment_date') and (not x.get('material_id') or x['material_id']==mid)]
    budget=sum((number(x.get('approved_amount')) or 0)-(number(x.get('committed_amount')) or 0) for x in budgets) if budgets else None
    required,stock=number(p.get('required_quantity')),number(p.get('usable_for_production'))
    confirmed=[x.get('validation',{}).get('supply_evidence_level')=='confirmed' for x in candidates]
    offers=[x for x in data.get('offers',[]) if x.get('material_id')==mid]
    expiries=[days(x.get('valid_until'),calculation.get('as_of')) for x in offers]
    expiries=[x for x in expiries if x is not None]
    use_dates=[x.get('use_date') for x in data.get('requirements',[]) if x.get('material_id')==mid and x.get('use_date')]
    last_use=max(use_dates) if use_dates else calculation.get('as_of')
    lot_margins=[days(d.get('expiry_date'),last_use) for candidate in eligible for d in candidate.get('deliveries',[])]
    lot_margins=[x for x in lot_margins if x is not None]
    waste=[number(x.get('expected_disposal_quantity'))/number(x['quantity']) for x in eligible if number(x.get('expected_disposal_quantity')) is not None and number(x.get('quantity'))]
    features={'production_days':days(p.get('first_shortage_date') or p.get('first_safety_breach_date'),calculation.get('as_of')),
        'inventory_ratio':stock/required if stock is not None and required and required>0 else None,
        'budget_margin':(budget-min(costs))/max(abs(budget),1) if budget is not None and costs else None,
        'supply_confirmation':sum(confirmed)/len(confirmed) if confirmed else None,
        'expiry_days':min(lot_margins) if lot_margins else None,'quote_validity_days':min(expiries) if expiries else None,'waste_ratio':min(waste) if waste else None}
    return {'identity':identity,'comparable':bool(identity['material'] and identity['unit'] and spec['product_code'] and any(spec[k] for k in ('formulation','content_per_vial','grade'))),
        'features':features,'required_quantity':required,'available_stock':stock,'budget_available':budget,
        'production_use_dates':[x.get('use_date') for x in data.get('requirements',[]) if x.get('material_id')==mid],
        'as_of':calculation.get('as_of'),'material_id':mid}


def policy():
    try:
        weights={**DEFAULT_WEIGHTS,**json.loads(setting('BIOFLOW_CASE_WEIGHTS','{}'))}
        scales={**DEFAULT_SCALES,**json.loads(setting('BIOFLOW_CASE_SCALES','{}'))}
        minimum=float(setting('BIOFLOW_CASE_MIN_SIMILARITY','0.5'))
        coverage=float(setting('BIOFLOW_CASE_MIN_COVERAGE','0.5'))
        if set(weights)!=set(DEFAULT_WEIGHTS) or set(scales)!=set(DEFAULT_SCALES): raise ValueError()
        if not all(number(x) is not None and x>=0 for x in weights.values()) or not sum(weights.values()): raise ValueError()
        if not all(number(x) is not None and x>0 for x in scales.values()) or not 0<=minimum<=1 or not 0<=coverage<=1: raise ValueError()
        return {'weights':weights,'scales':scales,'minimum_similarity':minimum,'minimum_coverage':coverage,'version':'rules-v1'}
    except (ValueError,TypeError,AttributeError):
        raise HTTPException(503,'과거 사례 유사도 설정을 확인하세요.') from None


def similarity(current,past,settings):
    if not current.get('comparable') or not past.get('comparable') or current['identity']!=past['identity']: return None
    parts=[];total=sum(settings['weights'].values());known=0;score=0
    for key,weight in settings['weights'].items():
        a,b=current['features'].get(key),past['features'].get(key)
        if a is None or b is None:
            parts.append({'feature':key,'current':a,'past':b,'score':None,'weight':weight,'reason':'미확인 · 점수 기여 없음'})
            continue
        value=max(0,1-min(abs(a-b)/settings['scales'][key],1))
        known+=weight;score+=weight*value
        parts.append({'feature':key,'current':a,'past':b,'score':round(value,6),'weight':weight,'scale':settings['scales'][key],'reason':'유사' if value>=0.75 else '차이 있음'})
    if known/total<settings['minimum_coverage']: return None
    return {'similarity':round(score/total,6),'coverage':round(known/total,6),'explanation':parts}


def capture(db,user,scenario_id,po_id,state,calculation,selected,reason=None,run=None,review_id=None,recommendation_id=None,approval_id=None,workspace_report=None):
    existing=db.scalar(select(DecisionCase).where(DecisionCase.scenario_id==scenario_id,DecisionCase.po_id==po_id))
    if existing: return existing
    from ..config import COLLECTIONS
    synthetic=scenario_id=='main-workspace' or state.get('is_synthetic') is True or any(x.get('is_synthetic') is True or x.get('source_kind') in ('synthetic','demo','simulation','test') or x.get('test_delivery') is True or x.get('demo_association') is True for key in COLLECTIONS for x in state.get(key,[]))
    source_refs=state.get('source_evidence_refs')
    actual=state.get('source_kind')=='actual' and state.get('is_synthetic') is False and isinstance(source_refs,list) and any(isinstance(x,str) and x.strip() for x in source_refs)
    kind='demo' if synthetic else 'real' if actual else 'unverified'
    candidates=[copy.deepcopy(x) for x in calculation.get('candidates',[]) if x.get('material_id')==selected.get('material_id')]
    decision={'review_id':review_id or scenario_id,'analysis_run_id':run.id if run else ((workspace_report or {}).get('externalReview') or {}).get('runId') or (workspace_report or {}).get('id'),
        'recommendation_id':recommendation_id,'approval_id':approval_id,'snapshot_revision':state.get('revision'),
        'erp_snapshot':None if run else copy.deepcopy(state),'snapshot_reference':{'run_id':run.id} if run else None,
        'context':context(state,calculation,selected.get('material_id')),'candidates':candidates,'selected':copy.deepcopy(selected),
        'strategy_type':'분할' if len(selected.get('deliveries',[]))>1 else '일괄','selection_reason':reason.strip() if isinstance(reason,str) and reason.strip() else None,
        'selected_at':now().isoformat(),'actor_id':user.id,'data_source':{'source_kind':kind,'scenario_id':scenario_id,'synthetic':synthetic,'evidence_refs':copy.deepcopy(source_refs) if isinstance(source_refs,list) else [],'snapshot_source':'discussion_run:'+run.id if run else 'workspace:'+(workspace_report or {}).get('id','unknown')},
        'workspace_report':{key:copy.deepcopy(workspace_report[key]) for key in ('id','revision','stamp','at','selected','summary','findings','externalReview') if key in workspace_report} if workspace_report else None}
    row=DecisionCase(id=uid(),scenario_id=scenario_id,actor_id=user.id,po_id=po_id,run_id=run.id if run else None,source_kind=kind,decision=decision,outcome={},revision=0)
    db.add(row);db.flush()
    audit(db,user.email,'decision.capture',scenario_id,after={'case_id':row.id,'po_id':po_id,'source_kind':kind})
    return row


def owned(db,case_id,user):
    row=db.get(DecisionCase,case_id)
    if not row or row.actor_id!=user.id: raise HTTPException(404,'의사결정 사례를 찾을 수 없습니다.')
    return row


def outcome_summary(row):
    outcome=row.outcome or {}
    costs=[Decimal(str(outcome['actual_'+key+'_cost'])) if outcome.get('actual_'+key+'_cost') is not None else None for key in COSTS]
    total=sum(costs) if all(x is not None for x in costs) else None
    raw_estimate=row.decision['selected'].get('costs',{}).get('total')
    estimate=Decimal(str(raw_estimate)) if raw_estimate is not None else None
    measured=any(outcome.get(key) is not None for key in MEASUREMENTS) or any(x.get('actual_arrival') or x.get('usable_date') for x in outcome.get('receipts',[]))
    return {'values':outcome,'source_kind':outcome.get('source_kind','unverified'),'confirmed':bool(row.source_kind=='real' and outcome.get('source_kind')=='real' and outcome.get('evidence_refs') and measured),
        'actual_total':str(total) if total is not None else None,'estimate_total':str(estimate) if estimate is not None else None,'actual_minus_estimate':str(total-estimate) if total is not None and estimate is not None else None,
        'unknown_fields':[key for key in MEASUREMENTS if outcome.get(key) is None],
        'cost_definition':'구매 + 운송 + 시험 + 보관 + 폐기처리비. 폐기 원료 구매원가는 추가 합산하지 않음.'}


def view(row,detail=False,db=None):
    value={'id':row.id,'scenario_id':row.scenario_id,'po_id':row.po_id,'actor_id':row.actor_id,'source_kind':row.source_kind,
        'created_at':utc_iso(row.created_at),'revision':row.revision,'decision':copy.deepcopy(row.decision),'outcome':outcome_summary(row)}
    if not detail:
        value['decision'].pop('erp_snapshot',None);value['decision'].pop('workspace_report',None)
    elif db is not None and row.decision.get('snapshot_reference'):
        run=db.get(DiscussionRun,row.decision['snapshot_reference']['run_id'])
        value['decision']['erp_snapshot']=copy.deepcopy(run.snapshot) if run else None
    return value


def search(db,user_id,current,include_demo=False,limit=5,exclude_po=None):
    settings=policy();query=select(DecisionCase).where(DecisionCase.actor_id==user_id)
    if not include_demo: query=query.where(DecisionCase.source_kind=='real')
    matches=[]
    for row in db.scalars(query.order_by(DecisionCase.created_at.desc()).limit(1000)):
        if row.po_id==exclude_po: continue
        match=similarity(current,row.decision['context'],settings)
        if match is not None and match['similarity']>=settings['minimum_similarity']:
            matches.append({**view(row),**match})
    matches.sort(key=lambda item:(-item['similarity'],item['id']))
    chosen=matches[:limit]
    # Demo inclusion changes the case list only. It never changes real preference/performance statistics.
    real=[x for x in matches if x['source_kind']=='real']
    verified=[x for x in real if x['outcome']['confirmed']]
    return {'message':'참고할 과거 사례 없음' if not chosen else '과거 사례는 참고 정보이며 현재 필수조건 검증을 대체하지 않습니다.',
        'cases':chosen,'policy':settings,'current_context':current,'matched_count':len(matches),
        'preference':{'actor_id':user_id,'case_count':len(real),'choices':dict(Counter(x['decision']['strategy_type'] for x in real))},
        'performance':{'case_count':len(real),'confirmed_outcome_count':len(verified),
            'cost_known_count':sum(x['outcome']['actual_total'] is not None for x in verified),
            'delay_known_count':sum(x['outcome']['values'].get('production_delayed') is not None for x in verified),
            'waste_known_count':sum(x['outcome']['values'].get('expired_quantity') is not None for x in verified)},
        'advisory_only':True,'training_performed':False,'pool_limit':1000}


def memory_for(db,user_id,data,calculation):
    return search(db,user_id,context(data,calculation))


def save_outcome(db,row,body,user):
    if not body.change_reason.strip(): raise HTTPException(422,'결과 저장·수정 이유를 입력하세요.')
    if row.source_kind!='real' and body.source_kind=='real': raise HTTPException(422,'시연·출처 미확인 판단을 실제 성과로 전환할 수 없습니다.')
    if body.source_kind=='real' and not any(x.strip() for x in body.evidence_refs): raise HTTPException(422,'실제 결과의 입력 근거를 기록하세요.')
    if body.production_delayed is False and body.production_delay_days not in (None,0): raise HTTPException(422,'지연 여부와 지연 일수를 확인하세요.')
    if body.production_delayed is True and body.production_delay_days==0: raise HTTPException(422,'지연 시 일수는 0보다 커야 합니다.')
    ids=[x.line_id for x in body.receipts]
    if len(ids)!=len(set(ids)): raise HTTPException(422,'입고 회차 ID가 중복됐습니다.')
    allowed={str(x.get('id') or x.get('lot_code')) for x in row.decision['selected'].get('deliveries',[])}
    if any(x not in allowed for x in ids): raise HTTPException(422,'승인 당시의 입고 회차를 사용하세요.')
    if any(x.actual_arrival and x.usable_date and x.usable_date<x.actual_arrival for x in body.receipts): raise HTTPException(422,'사용 가능일은 입고일보다 빠를 수 없습니다.')
    before=copy.deepcopy(row.outcome)
    value=body.model_dump(mode='json');value.pop('expected_revision');value['reported_by']=user.id;value['reported_at']=now().isoformat()
    changed=db.execute(update(DecisionCase).where(DecisionCase.id==row.id,DecisionCase.actor_id==user.id,DecisionCase.revision==body.expected_revision).values(outcome=value,revision=body.expected_revision+1))
    if changed.rowcount!=1:
        db.rollback();raise HTTPException(409,'실행 결과가 변경됐습니다. 최신 내용을 불러오세요.')
    audit(db,user.email,'decision.outcome.update',row.scenario_id,before={'case_id':row.id,'revision':body.expected_revision,'outcome':before},after={'case_id':row.id,'revision':body.expected_revision+1,'outcome':value})
    db.commit();db.refresh(row)
    return view(row)


def observations(db,row):
    from ..models import Scenario
    scenario=db.get(Scenario,row.scenario_id)
    result={'receipts':[],'source_kind':'demo' if row.source_kind=='demo' else 'unverified','values':{},'evidence_refs':[]}
    if row.scenario_id=='main-workspace' and scenario:
        order=next((x for x in scenario.data.get('_workflow',{}).get('orders',[]) if x['id']==row.po_id),None)
        if order:
            result['receipts']=[{'line_id':next((str(line.get('id') or line.get('lot_code')) for line in row.decision['selected'].get('deliveries',[]) if line.get('code')==x['id'] or line.get('id')==x['id']),x['id']),'actual_arrival':x.get('actualArrival') or None,'usable_date':x.get('qaAt') or None} for x in order['lines']]
            result['evidence_refs']=['workspace:'+row.po_id+':가상 입고·품질·생산 진행']
        return result
    order=db.scalar(select(ERPRecord).where(ERPRecord.scenario_id==row.scenario_id,ERPRecord.collection=='purchase_orders',ERPRecord.record_id==row.po_id))
    if order:
        data=order.data
        for line in data.get('deliveries',[]):
            if line.get('source_kind')!='actual' or not line.get('evidence_refs') or line.get('is_synthetic') is True or line.get('test_delivery'): continue
            result['receipts'].append({'line_id':line.get('id') or line.get('lot_code'),'actual_arrival':line.get('actual_arrival_date'),'usable_date':line.get('actual_usable_date')})
            result['evidence_refs'].extend(line['evidence_refs'])
        if data.get('source_kind')=='actual' and data.get('evidence_refs') and data.get('is_synthetic') is not True and not data.get('test_delivery'):
            result['source_kind']='real';result['evidence_refs'].extend(data['evidence_refs'])
            for key in COSTS:
                raw=data.get('actual_costs',{}).get(key)
                result['values']['actual_'+key+'_cost']=raw if number(raw) is not None and data.get('currency',row.decision['context']['identity']['currency'])==row.decision['context']['identity']['currency'] else None
            for key in ('used_quantity','remaining_quantity','expired_quantity','production_delay_days','production_delayed'):
                result['values'][key]=data.get('actual_outcome',{}).get(key)
    # Actual observations require an explicit source marker and evidence. Estimates are never substituted.
    frozen=row.decision.get('erp_snapshot')
    if frozen is None and row.decision.get('snapshot_reference'):
        run=db.get(DiscussionRun,row.decision['snapshot_reference']['run_id']);frozen=run.snapshot if run else {}
    frozen=frozen or {}
    material_id=row.decision['context']['material_id']
    expected={x['production_plan_id']:x['use_date'] for x in frozen.get('requirements',[]) if x.get('material_id')==material_id and x.get('production_plan_id') and x.get('use_date')}
    deliveries=(order.data if order else {}).get('deliveries',row.decision['selected'].get('deliveries',[]))
    records=list(db.scalars(select(ERPRecord).where(ERPRecord.scenario_id==row.scenario_id,ERPRecord.collection.in_(['lots','consumptions','production_plans']))))
    actual=lambda value:value.get('source_kind')=='actual' and bool(value.get('evidence_refs')) and value.get('is_synthetic') is not True
    field_sources={}
    def cite(key,record):
        value=record.data
        field_sources.setdefault(key,[]).append({'collection':record.collection,'record_id':record.record_id,'evidence_refs':value['evidence_refs']})
        result['evidence_refs'].extend(value['evidence_refs'])
    lots=[]
    for record in records:
        if record.collection!='lots' or not actual(record.data) or record.data.get('material_id')!=material_id or record.data.get('unit',row.decision['context']['identity']['unit'])!=row.decision['context']['identity']['unit']: continue
        lot=record.data
        linked=next((x for x in deliveries if x.get('lot_id')==record.record_id or (x.get('lot_code') and x['lot_code'] in (lot.get('lot_code'),lot.get('code')))),None)
        if not linked: continue
        lots.append(record)
        line_id=str(linked.get('id') or linked.get('lot_code'))
        if not any(x['line_id']==line_id for x in result['receipts']):
            result['receipts'].append({'line_id':line_id,'actual_arrival':lot.get('actual_arrival_date'),'usable_date':lot.get('qa_release_date')})
        cite('receipts',record)
    lot_ids={x.record_id for x in lots}
    used=[]
    for record in records:
        value=record.data
        if record.collection=='consumptions' and actual(value) and (value.get('purchase_order_id')==row.po_id or value.get('lot_id') in lot_ids):
            if value.get('unit',row.decision['context']['identity']['unit'])!=row.decision['context']['identity']['unit']: continue
            quantity=number(value.get('quantity'))
            if quantity is not None: used.append(quantity);cite('used_quantity',record)
    if used and result['values'].get('used_quantity') is None: result['values']['used_quantity']=sum(used)
    for target,field in [('remaining_quantity','actual_remaining_quantity'),('expired_quantity','actual_expired_quantity')]:
        values=[number(x.data.get(field)) for x in lots]
        if values and all(x is not None for x in values) and result['values'].get(target) is None:
            result['values'][target]=sum(values)
            for record in lots: cite(target,record)
    delays={}
    for record in records:
        if record.collection=='production_plans' and record.record_id in expected and actual(record.data):
            delay=days(record.data.get('actual_start_date'),expected[record.record_id])
            if delay is not None: delays[record.record_id]=max(0,delay);cite('production_delay_days',record)
    if expected and len(delays)==len(expected):
        result['values'].setdefault('production_delay_days',max(delays.values()))
        if result['values'].get('production_delay_days') is None: result['values']['production_delay_days']=max(delays.values())
        if result['values'].get('production_delayed') is None: result['values']['production_delayed']=any(delays.values())
    result['field_sources']=field_sources
    result['evidence_refs']=list(dict.fromkeys(result['evidence_refs']))
    result['collection_note']='명시된 실제 기록만 수집. 사용량은 등록된 실제 소비 기록 합계이며 기록 누락 여부는 담당자가 확인해야 합니다. 생산 지연은 승인 당시 투입일 대비 실제 시작일 기준입니다.'
    if field_sources: result['source_kind']='real' if row.source_kind=='real' else 'unverified'
    return result




def orchestrator_input(result):
    """Bounded advisory projection: old ERP/candidate payloads are not re-injected."""
    if not result: return {'cases':[],'message':'참고할 과거 사례 없음','advisory_only':True,'training_performed':False}
    cases=[]
    for case in result.get('cases',[])[:5]:
        decision=case.get('decision',{});outcome=case.get('outcome',{});values=outcome.get('values',{})
        cases.append({'id':case['id'],'po_id':case.get('po_id'),'source_kind':case.get('source_kind'),
            'similarity':case.get('similarity'),'coverage':case.get('coverage'),'explanation':case.get('explanation',[]),
            'selection':{'candidate_id':decision.get('selected',{}).get('id'),'strategy_type':decision.get('strategy_type'),
                'reason':str(decision.get('selection_reason') or '')[:1000],'selected_at':decision.get('selected_at')},
            'outcome':{'source_kind':outcome.get('source_kind','unverified'),'confirmed':outcome.get('confirmed',False),'actual_total':outcome.get('actual_total'),
                'values':{key:values.get(key) for key in MEASUREMENTS},'receipts':values.get('receipts',[])[:10],
                'evaluation':str(values.get('evaluation') or '')[:600],'notes':str(values.get('notes') or '')[:600],
                'unknown_fields':outcome.get('unknown_fields',[]),'evidence_refs':values.get('evidence_refs',[])[:10]},
            'provenance':decision.get('data_source',{})})
    return {'cases':cases,'message':result.get('message'),'policy':result.get('policy'),
        'preference':{k:v for k,v in result.get('preference',{}).items() if k!='actor_id'},
        'performance':result.get('performance',{}),'unavailable':result.get('unavailable',False),
        'advisory_only':True,'training_performed':False}

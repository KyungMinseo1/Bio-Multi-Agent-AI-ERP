"""Authenticated, owner-scoped decision memory endpoints."""
from fastapi import APIRouter,Depends,Query
from sqlalchemy import select
from .auth import current_user,mutation_user
from .db import get_db
from .models import DecisionCase,AuditEvent,Scenario,utc_iso
from .services import decision_memory as memory
from .services.erp import snapshot
from .services.planning import evaluate
from .config import planning_date
router=APIRouter(prefix='/api/v1')

@router.get('/decision-cases')
def cases(scenario_id:str|None=None,po_id:str|None=None,include_demo:bool=False,user=Depends(current_user),db=Depends(get_db)):
    query=select(DecisionCase).where(DecisionCase.actor_id==user.id)
    if scenario_id: query=query.where(DecisionCase.scenario_id==scenario_id)
    if po_id: query=query.where(DecisionCase.po_id==po_id)
    if not include_demo: query=query.where(DecisionCase.source_kind=='real')
    return [memory.view(row) for row in db.scalars(query.order_by(DecisionCase.created_at.desc()).limit(200))]

@router.get('/decision-memory/similar')
def similar(scenario_id:str,expected_stamp:str|None=None,material_id:str|None=None,include_demo:bool=False,exclude_po:str|None=None,limit:int=Query(5,ge=1,le=20),user=Depends(current_user),db=Depends(get_db)):
    if db.get(Scenario,scenario_id) is None:
        from fastapi import HTTPException
        raise HTTPException(404,'서버에 저장된 검토 건을 선택하세요.')
    data=snapshot(db,scenario_id);calculation=evaluate(data,as_of=planning_date())
    if expected_stamp and expected_stamp!=data.get('workspace_stamp'):
        from fastapi import HTTPException
        raise HTTPException(409,'로컬 판단 원본과 서버 저장 버전이 다릅니다. 먼저 현재 업무를 서버에 저장하세요.')
    value=memory.search(db,user.id,memory.context(data,calculation,material_id),include_demo,limit,exclude_po)
    value['current_eligible_candidate_ids']=[c['id'] for c in calculation.get('candidates',[]) if c.get('validation',{}).get('hard_constraints_passed') and c['validation'].get('target_delivery_met') and c['validation'].get('cash_feasible',True)]
    value['reuse_authorized']=False
    return value

@router.get('/decision-cases/{case_id}')
def detail(case_id:str,user=Depends(current_user),db=Depends(get_db)):
    row=memory.owned(db,case_id,user)
    return {**memory.view(row,True,db),'observations':memory.observations(db,row)}

@router.put('/decision-cases/{case_id}/outcome')
def outcome(case_id:str,body:memory.OutcomeInput,user=Depends(mutation_user),db=Depends(get_db)):
    return memory.save_outcome(db,memory.owned(db,case_id,user),body,user)

@router.get('/decision-cases/{case_id}/history')
def history(case_id:str,user=Depends(current_user),db=Depends(get_db)):
    memory.owned(db,case_id,user)
    rows=db.scalars(select(AuditEvent).where(AuditEvent.action=='decision.outcome.update',AuditEvent.after['case_id'].as_string()==case_id).order_by(AuditEvent.created_at))
    return [{'id':x.id,'actor':x.actor,'before':x.before,'after':x.after,'created_at':utc_iso(x.created_at)} for x in rows]

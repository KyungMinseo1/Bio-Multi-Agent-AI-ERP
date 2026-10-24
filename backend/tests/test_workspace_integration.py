"""Integration tests: original TS engine + team auth, DB, worker and validation contracts."""
import asyncio
import copy
import json
from sqlalchemy import select
from app.services.workspace import execute
from app.services import discussions
from app.models import ERPRecord, AuditEvent
from app.db import SessionLocal
from test_discussions import configure_review_provider, review_turn

API='/api/v1'

def seed(): return execute(command='seed')['workflow']
def upload(client, state=None, revision=0):
    response=client.put(API+'/workspace',json={'workflow':state or seed(),'expected_revision':revision})
    assert response.status_code==200,response.text
    return response.json()
def command(client, current, name, **args):
    response=client.post(API+'/workspace/commands',json={'command':name,'args':args,'expected_revision':current['revision']})
    assert response.status_code==200,response.text
    return response.json()
def ready(client):
    current=upload(client)
    for name in ['approveInquiry','startInquiries','receiveReplies','analyze']:
        current=command(client,current,name)
    return current

def test_workspace_shared_calculations_and_product_assumptions(client):
    current=ready(client)
    projected=client.get(API+'/scenarios/main-workspace').json()
    assert '_workflow' not in projected
    assert next(m for m in projected['materials'] if m['code']=='MAT-IL7')['content_per_vial']=='동일 함량 규격 U1 · 실물 함량 미지정'
    calc=client.get(API+'/scenarios/main-workspace/planning').json()
    material=next(m for m in calc['materials'] if m['code']=='MAT-IL7')
    assert material['book_quantity']=='6' and material['usable_for_production']=='2' and material['new_order_quantity']=='12'
    b=next(c for c in calc['candidates'] if c['original_vendor_id']=='B')
    assert b['quantity']=='12' and b['costs']['subtotal']=='12300000' and b['costs']['total']=='12758800'
    assert [x['available_date'] for x in b['deliveries']]==['2026-11-02','2026-11-09','2026-11-16']
    assert current['workflow']['integration']['selected']=='B'

def test_unauthorized_and_operator_approval_blocked(client):
    current=ready(client)
    client.post(API+'/auth/logout')
    assert client.get(API+'/workspace').status_code==401
    assert client.put(API+'/workspace',json={'workflow':seed(),'expected_revision':0}).status_code==401
    client.post(API+'/auth/login',json={'email':'operator@example.test','password':'test-only-operator-password'})
    response=client.post(API+'/workspace/commands',json={'command':'registerPO','expected_revision':current['revision']})
    assert response.status_code==403

def test_first_approval_gates_commands_and_actual_review(client,monkeypatch):
    current=upload(client)
    for name in ['startInquiries','receiveReplies','analyze','registerPO']:
        assert client.post(API+'/workspace/commands',json={'command':name,'expected_revision':current['revision']}).status_code==422
    configure_review_provider(monkeypatch,1)
    assert client.post(API+'/scenarios/main-workspace/discussions',json={'expected_revision':current['revision']}).status_code==409

def test_db_final_po_same_data_and_duplicate_prevention(client):
    current=ready(client)
    approved=command(client,current,'registerPO')
    o=approved['workflow']['orders'][0]
    assert o['quantity']==12 and o['subtotal']==12300000
    assert len(approved['workflow']['approvals'])==2
    mirror=client.get(API+'/scenarios/main-workspace/purchase_orders').json()
    assert len(mirror)==1 and mirror[0]['code']==o['id']
    assert mirror[0]['costs']['subtotal']=='12300000'
    assert client.post(API+'/workspace/commands',json={'command':'registerPO','expected_revision':approved['revision']}).status_code==422
    assert client.post(API+'/workspace/commands',json={'command':'registerPO','expected_revision':current['revision']}).status_code==409
    with SessionLocal() as db:
        assert db.scalar(select(AuditEvent).where(AuditEvent.action=='workspace.registerPO')) is not None

def test_concurrent_drafts_rejected_without_overwrite(client):
    current=upload(client)
    old=copy.deepcopy(current['workflow'])
    current=command(client,current,'approveInquiry')
    response=client.put(API+'/workspace',json={'workflow':old,'expected_revision':1})
    assert response.status_code==409
    assert client.get(API+'/workspace').json()['workflow']==current['workflow']

def test_draft_upload_cannot_add_or_remove_orders_or_change_frozen_price(client):
    current=ready(client)
    counterfeit=execute(current['workflow'],'registerPO')['workflow']
    assert client.put(API+'/workspace',json={'workflow':counterfeit,'expected_revision':current['revision']}).status_code==409
    current=command(client,current,'registerPO')
    changed=copy.deepcopy(current['workflow']);changed['orders'][0]['unitPrice']=1
    assert client.put(API+'/workspace',json={'workflow':changed,'expected_revision':current['revision']}).status_code==409
    assert client.put(API+'/workspace',json={'workflow':seed(),'expected_revision':current['revision']}).status_code==409

def test_derived_erp_tables_readonly_but_native_scenarios_keep_crud(client):
    current=ready(client)
    projected=client.get(API+'/scenarios/main-workspace').json()
    material=projected['materials'][0]
    assert client.patch(API+f"/scenarios/main-workspace/materials/{material['id']}",json={'name':'overwritten','revision':material['revision']}).status_code==409
    native=client.get(API+'/scenarios/scenario_1').json();m=native['materials'][0]
    assert client.patch(API+f"/scenarios/scenario_1/materials/{m['id']}",json={'name':'팀원 확장 ERP 편집','revision':m['revision']}).status_code==200
    assert client.get(API+'/workspace').json()['workflow']==current['workflow']

def test_keyless_real_review_fails_explicitly_not_simulated(client):
    current=ready(client)
    response=client.post(API+'/scenarios/main-workspace/discussions',json={'expected_revision':current['revision']})
    assert response.status_code==503
    assert client.get(API+'/scenarios/main-workspace/discussions').json()==[]
    assert current['workflow']['integration']['selected']=='B'

def test_qc_delay_mirrors_db_and_authoritative_shortage(client):
    current=command(client,ready(client),'registerPO');o=current['workflow']['orders'][0]
    current=command(client,current,'trackingIssue',po=o['id'],line=o['lines'][1]['id'],kind='delay')
    assert current['workflow']['orders'][0]['lines'][1]['available']=='2026-11-12'
    projected=client.get(API+'/scenarios/main-workspace/purchase_orders').json()[0]
    assert projected['deliveries'][1]['available_date']=='2026-11-12'
    calc=client.get(API+'/scenarios/main-workspace/planning').json()
    assert next(m for m in calc['materials'] if m['code']=='MAT-IL7')['first_shortage_date']=='2026-11-11'
    for _ in range(4):current=command(client,current,'trackNext',po=o['id'],line=o['lines'][0]['id'])
    assert current['workflow']['data']['lots'][-1]['qa']=='미승인'
    current=command(client,current,'trackNext',po=o['id'],line=o['lines'][0]['id'])
    assert current['workflow']['data']['lots'][-1]['qa']=='승인'

def test_mocked_provider_contract_to_adoption_to_same_final_approval(client,monkeypatch):
    current=ready(client);configure_review_provider(monkeypatch,1)
    queued=client.post(API+'/scenarios/main-workspace/discussions',json={'expected_revision':current['revision']}).json()
    chosen=next(c['id'] for c in queued['calculation']['candidates'] if c['original_vendor_id']=='B')
    roles=[]
    async def generate(role,messages,schema):
        roles.append(role);context=json.loads(messages[-1]['content'])
        return review_turn(role,context,[chosen])
    monkeypatch.setattr(discussions,'generate_json',generate)
    asyncio.run(discussions.run_discussion(queued['id']))
    run=client.get(API+'/discussions/'+queued['id']).json()
    assert run['status']=='awaiting_review',run.get('error')
    assert set(roles)=={'purchasing','inventory_planning','quality','finance','orchestrator'}
    rec=run['recommendations'][0]
    adopted=client.post(API+'/workspace/adopt-review',json={'recommendation_id':rec['id'],'expected_revision':current['revision'],'stamp':current['stamp']})
    assert adopted.status_code==200,adopted.text
    adopted=adopted.json()
    assert adopted['workflow']['integration']['externalReview']['runId']==queued['id']
    assert '[실제 LLM 검토' in adopted['workflow']['integration']['summary']
    registered=command(client,adopted,'registerPO')
    assert registered['workflow']['orders'][0]['subtotal']==12300000
    assert client.get(API+'/discussions/'+queued['id']).json()['recommendations'][0]['status']=='selected'

def test_local_demo_login_default_disabled_and_origin_restricted(client,monkeypatch):
    client.post(API+'/auth/logout')
    assert client.post(API+'/auth/local-demo').status_code==403
    monkeypatch.setenv('BIOFLOW_LOCAL_DEMO','1')
    assert client.post(API+'/auth/local-demo',headers={'Origin':'https://untrusted.example'}).status_code==403
    assert client.post(API+'/auth/local-demo',headers={'Origin':'http://127.0.0.1:4173'}).status_code==200

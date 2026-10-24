"""All transport is mocked. These tests cannot send real email."""
import copy
import smtplib
from concurrent.futures import ThreadPoolExecutor
from threading import Event
import pytest
from app.services import mailer, workspace
from test_workspace_integration import upload, command, API


@pytest.fixture
def rfq(client, monkeypatch):
    monkeypatch.setenv('BIOFLOW_MAIL_MODE', 'preview')
    monkeypatch.setenv('BIOFLOW_MAIL_TEST_TO', '')
    monkeypatch.setenv('BIOFLOW_MAIL_TEST_ALLOWLIST', '')
    for key, value in {'HOST':'smtp.company.co.kr','PORT':'587','SECURITY':'starttls',
        'USERNAME':'buyer@company.co.kr','PASSWORD':'mock-secret','DEFAULT_FROM':'buyer@company.co.kr',
        'ALLOWED_FROM':'buyer@company.co.kr','DEFAULT_TO':'unrelated@company.co.kr'}.items():
        monkeypatch.setenv('BIOFLOW_SMTP_'+key, value)
    state = workspace.execute(command='seed')['workflow']
    for v in state['data']['vendors']:
        v['quoteEmail'] = f"rfq@{v['id'].lower()}-supplier.co.kr"
    current = command(client, upload(client, state), 'approveInquiry')
    monkeypatch.setattr(mailer.smtplib, 'SMTP', lambda *a, **k: pytest.fail('Unexpected SMTP network call'))
    return current


def payload(current, vendor='A'):
    s = current['workflow']; p = s['data']['products'][0]
    v = next(v for v in s['data']['vendors'] if v['id'] == vendor)
    q = next(q for q in s['inquiries'] if q['vendor'] == vendor)
    return dict(case_id=workspace.execute(s)['case_id'], inquiry_id=q['id'], expected_revision=current['revision'],
        vendor_id=vendor,vendor_name=v['name'],sender_email='buyer@company.co.kr',recipient_email=v['quoteEmail'],
        subject='Quote request',body='Please confirm price, MOQ and delivery dates.',material_code=p['id'],
        material_name=p['name'],unit=p['unit'],required_quantity=12,safety_stock=p['safety'],
        schedule=[dict(production_id=x['id'],needed_date=x['date'],quantity=x['il7']) for x in s['data']['productions']])


def send(client, body, key='rfq-test-idempotency-0001', method='post'):
    return getattr(client, method)(API+'/mail/quote-requests',json=body,headers={'Idempotency-Key':key})


def transport(monkeypatch, outcome=None):
    calls=[]
    class SMTP:
        def __init__(self,*a,**kw): pass
        def __enter__(self): return self
        def __exit__(self,*a): pass
        def ehlo(self): pass
        def starttls(self,**kw): pass
        def login(self,*a): pass
        def send_message(self,msg,**kw):
            calls.append((msg,kw))
            if outcome: raise outcome
            return {}
    monkeypatch.setattr(mailer.smtplib,'SMTP',SMTP)
    return calls


def test_approval_atomic_inquiries_and_revision_conflict(client,rfq):
    s=rfq['workflow']
    assert len(s['approvals'])==1 and len(s['inquiries'])==3 and not s['orders']
    again=command(client,rfq,'startInquiries')
    assert again['workflow']['inquiries']==s['inquiries']
    assert client.post(API+'/workspace/commands',json={'command':'approveInquiry','expected_revision':1}).status_code==409
    held=command(client,again,'approveInquiry',approve=False)
    assert send(client,payload(held)).status_code==422


def test_preview_without_smtp_and_per_vendor_drafts(client,rfq,monkeypatch):
    monkeypatch.setenv('BIOFLOW_SMTP_PASSWORD','')
    for vendor in 'AB':
        body=payload(rfq,vendor)
        result=send(client,body,'preview-draft-key-'+vendor)
        assert result.status_code==200,result.text
        assert result.json()['status']=='preview' and result.json()['reply_status']=='not_requested'
        assert result.json()['original_recipient']==body['recipient_email']
    rows=client.get(API+'/mail/outbox',params={'case_id':body['case_id']}).json()
    assert len(rows)==2 and len({r['original_recipient'] for r in rows})==2
    assert all(r['draft']['body']==body['body'] for r in rows)


@pytest.mark.parametrize('address',['','bad-address','supplier-a@example.com'])
def test_invalid_or_example_live_blocked_and_draft_retained(client,rfq,monkeypatch,address):
    monkeypatch.setenv('BIOFLOW_MAIL_MODE','live')
    s=copy.deepcopy(rfq['workflow']);s['data']['vendors'][0]['quoteEmail']=address
    # Contact edits are persisted; they do not grant any supply commitment.
    current=upload(client,s,rfq['revision'])
    body=payload(current)
    response=send(client,body)
    assert response.status_code==422,response.text
    rows=client.get(API+'/mail/outbox',params={'case_id':body['case_id']}).json()
    assert rows[0]['draft']['body']==body['body'] and rows[0]['status']=='draft'


def test_server_rejects_recipient_spoof_and_stale_data(client,rfq):
    body=payload(rfq);body['recipient_email']='unrelated@company.co.kr'
    assert send(client,body).status_code==409
    body=payload(rfq);body['required_quantity']=999
    assert send(client,body).status_code==409
    body=payload(rfq);body['expected_revision']-=1
    assert send(client,body).status_code==409


def test_test_mode_requires_explicit_allowlist_and_routes_envelope(client,rfq,monkeypatch):
    monkeypatch.setenv('BIOFLOW_MAIL_MODE','test');body=payload(rfq)
    assert send(client,body).status_code==422
    monkeypatch.setenv('BIOFLOW_MAIL_TEST_TO','qa@company.co.kr')
    assert send(client,body).status_code==422
    monkeypatch.setenv('BIOFLOW_MAIL_TEST_ALLOWLIST','qa@company.co.kr')
    calls=transport(monkeypatch)
    response=send(client,body)
    assert response.status_code==200,response.text
    result=response.json()
    assert result['status']=='sent' and result['reply_status']=='test_only'
    assert result['original_recipient']==body['recipient_email'] and result['recipient']=='qa@company.co.kr'
    assert calls[0][1]['to_addrs']==['qa@company.co.kr'] and calls[0][0]['To']=='qa@company.co.kr'
    replied=command(client,rfq,'receiveReplies')
    assert next(q for q in replied['workflow']['inquiries'] if q['vendor']=='A')['terms'] is None
    assert '테스트 메일' in replied['workflow']['inquiries'][0]['original']


def test_live_duplicate_clicks_and_new_keys_send_once_and_exclude_mock_replies(client,rfq,monkeypatch):
    monkeypatch.setenv('BIOFLOW_MAIL_MODE','live');calls=transport(monkeypatch);body=payload(rfq)
    for key in ['rfq-first-live-key-0001','rfq-first-live-key-0001','rfq-other-live-key-0002']:
        result=send(client,body,key)
        assert result.status_code==200,result.text
        assert result.json()['reply_status']=='awaiting_reply'
    assert len(calls)==1
    other=payload(rfq,'B')
    assert send(client,other,'rfq-first-live-key-0001').status_code==409
    replied=command(client,rfq,'receiveReplies')['workflow']
    assert next(q for q in replied['inquiries'] if q['vendor']=='A')['terms'] is None
    assert next(q for q in replied['inquiries'] if q['vendor']=='B')['terms'] is not None


def test_failure_preserves_edits_and_definite_rejection_can_retry(client,rfq,monkeypatch):
    monkeypatch.setenv('BIOFLOW_MAIL_MODE','live');body=payload(rfq)
    calls=transport(monkeypatch,smtplib.SMTPDataError(554,b'rejected'))
    result=send(client,body).json()
    assert result['status']=='failed' and result['draft']['body']==body['body']
    calls=transport(monkeypatch)
    assert send(client,body).json()['status']=='sent' and len(calls)==1


def test_ambiguous_delivery_blocks_every_retry(client,rfq,monkeypatch):
    monkeypatch.setenv('BIOFLOW_MAIL_MODE','live');body=payload(rfq)
    calls=transport(monkeypatch,TimeoutError())
    result=send(client,body).json()
    assert result['status']=='unknown' and result['reply_status']=='check_required'
    assert result['message_id']
    for key in ['rfq-test-idempotency-0001','another-unknown-retry-key']:
        assert send(client,body,key).status_code==409
    assert len(calls)==1


def test_draft_update_and_forged_approval_or_mock_commitment_blocked(client,rfq,monkeypatch):
    body=payload(rfq);assert send(client,body,method='put').status_code==200
    body['body']='Edited terms retained after reopen.'
    assert send(client,body,method='put').json()['draft']['body']==body['body']
    forged=copy.deepcopy(rfq['workflow']);forged['approvals'][0]['decision']='보류'
    assert client.put(API+'/workspace',json={'workflow':forged,'expected_revision':rfq['revision']}).status_code==409
    monkeypatch.setenv('BIOFLOW_MAIL_MODE','live');transport(monkeypatch)
    assert send(client,body,'different-mode-delivery-key').json()['status']=='sent'
    forged=workspace.execute(rfq['workflow'],'receiveReplies')['workflow']
    assert client.put(API+'/workspace',json={'workflow':forged,'expected_revision':rfq['revision']}).status_code==409


def test_parallel_clicks_claim_one_delivery_and_keep_sending_protected(client,rfq,monkeypatch):
    monkeypatch.setenv('BIOFLOW_MAIL_MODE','live');body=payload(rfq)
    entered, release=Event(),Event();calls=[]
    def smtp(payload,message_id):
        calls.append(message_id);entered.set()
        assert release.wait(10)
        return message_id,'mock.csv'
    monkeypatch.setattr(mailer,'send_quote_email',smtp)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first=pool.submit(send,client,body)
        try:
            assert entered.wait(10)
            assert send(client,body,'parallel-second-delivery-key').status_code==409
            assert send(client,body,method='put').status_code==409
            assert command(client,rfq,'receiveReplies')['workflow']['inquiries'][0]['terms'] is None
        finally:
            release.set()
        assert first.result().json()['status']=='sent'
    assert len(calls)==1


def test_approval_commit_failure_does_not_create_inquiries(client,monkeypatch):
    from fastapi import HTTPException
    current=upload(client)
    def fail(*a,**kw): raise HTTPException(503,'Simulated database failure')
    monkeypatch.setattr(workspace,'persist',fail)
    response=client.post(API+'/workspace/commands',json={'command':'approveInquiry','expected_revision':current['revision']})
    assert response.status_code==503
    saved=client.get(API+'/workspace').json()['workflow']
    assert not saved['approvals'] and not saved['inquiries']

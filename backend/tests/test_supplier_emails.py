"""Supplier email integration: mock transports and isolated test DB only."""
from unittest.mock import AsyncMock
import pytest
from app.services import workspace,gmail_mcp
from test_quote_requests import quote,post


def update_contact(client,body,email):
    current=client.get('/api/v1/workspace').json()
    current['workflow']['data']['vendors'][1]['email']=email
    response=client.put('/api/v1/workspace',json={'workflow':current['workflow'],'expected_revision':current['revision']})
    assert response.status_code==200,response.text
    remote=response.json()
    draft=workspace.execute(remote['workflow'],'quoteDraft',{'vendor':'B'})['quoteDraft']
    return {**body,**draft,'expected_revision':remote['revision'],'source_stamp':remote['stamp']}


def test_supplier_csv_api_persists_email_after_reload_and_projection(client,quote):
    source=client.get('/api/v1/workspace/csv').json()
    updated=source['sources']['suppliers'].replace('rfq@supplier-b.co.kr','quotes@new-supplier.co.kr')
    result=client.put('/api/v1/workspace/csv/suppliers',json={'content':updated,'expected_revision':source['revision']})
    assert result.status_code==200,result.text
    saved=client.get('/api/v1/workspace').json()
    assert saved['workflow']['data']['vendors'][1]['email']=='quotes@new-supplier.co.kr'
    assert saved['workflow']['data']['vendors'][0]['email']=='rfq@supplier-a.co.kr'
    assert 'quotes@new-supplier.co.kr' in client.get('/api/v1/workspace/csv').json()['sources']['suppliers']
    records=client.get('/api/v1/scenarios/main-workspace/suppliers').json()
    assert next(row for row in records if row['code']=='SUP-B')['email']=='quotes@new-supplier.co.kr'
    stale=client.put('/api/v1/workspace/csv/suppliers',json={'content':updated,'expected_revision':source['revision']})
    assert stale.status_code==409


def test_previous_local_quote_email_is_preserved_without_second_field(client,quote):
    current=client.get('/api/v1/workspace').json();vendor=current['workflow']['data']['vendors'][1]
    vendor.pop('email');vendor['quoteEmail']='legacy@supplier.co.kr'
    result=client.put('/api/v1/workspace',json={'workflow':current['workflow'],'expected_revision':current['revision']})
    assert result.status_code==200,result.text
    restored=client.get('/api/v1/workspace').json()['workflow']['data']['vendors'][1]
    assert restored['email']=='legacy@supplier.co.kr' and 'quoteEmail' not in restored


@pytest.mark.parametrize('email',['','not-an-address','a..b@supplier.co.kr','supplier-b@example.com','supplier-b@x.example.com'])
def test_invalid_and_example_addresses_never_reach_transport(client,quote,monkeypatch,email):
    mocked=AsyncMock();monkeypatch.setattr(gmail_mcp,'send_quote',mocked)
    if email == 'not-an-address':
        current=client.get('/api/v1/workspace').json();current['workflow']['data']['vendors'][1]['email']=email
        invalid=client.put('/api/v1/workspace',json={'workflow':current['workflow'],'expected_revision':current['revision']})
        assert invalid.status_code==422
        mocked.assert_not_called()
        return
    body=update_contact(client,quote,email)
    result=post(client,{**body,'delivery_mode':'gmail_mcp'})
    assert result.status_code==422,result.text
    mocked.assert_not_called()


def test_common_default_cannot_replace_supplier_address_or_sender(client,quote,monkeypatch):
    mocked=AsyncMock();monkeypatch.setattr(gmail_mcp,'send_quote',mocked)
    monkeypatch.setenv('BIOFLOW_SMTP_DEFAULT_TO','teammate@company.co.kr')
    assert post(client,{**quote,'delivery_mode':'gmail_mcp','recipient_email':'teammate@company.co.kr'}).status_code==422
    assert post(client,{**quote,'delivery_mode':'gmail_mcp','sender_email':'other@company.co.kr'}).status_code==422
    mocked.assert_not_called()


def test_preview_policy_is_default_and_never_sends(client,quote,monkeypatch):
    monkeypatch.delenv('BIOFLOW_MAIL_MODE',raising=False)
    mocked=AsyncMock();monkeypatch.setattr(gmail_mcp,'send_quote',mocked)
    assert post(client,{**quote,'delivery_mode':'gmail_mcp'}).status_code==422
    assert post(client,quote).json()['status']=='simulated'
    mocked.assert_not_called()


def test_test_recipient_is_explicit_allowlisted_and_not_supply_confirmation(client,quote,monkeypatch):
    monkeypatch.setenv('BIOFLOW_MAIL_MODE','test');monkeypatch.setenv('BIOFLOW_MAIL_TEST_TO','');monkeypatch.setenv('BIOFLOW_MAIL_TEST_ALLOWLIST','')
    mocked=AsyncMock(return_value=('test-id','test-thread','quote.csv'));monkeypatch.setattr(gmail_mcp,'send_quote',mocked)
    body={**quote,'delivery_mode':'gmail_mcp'}
    assert post(client,body).status_code==422
    monkeypatch.setenv('BIOFLOW_MAIL_TEST_TO','qa@company.co.kr')
    assert post(client,body).status_code==422
    monkeypatch.setenv('BIOFLOW_MAIL_TEST_ALLOWLIST','qa@company.co.kr')
    result=post(client,body);assert result.status_code==200,result.text
    row=result.json();assert row['recipient']=='qa@company.co.kr' and row['original_recipient']==quote['recipient_email'] and row['test_delivery']
    assert mocked.call_args.args[0].recipient_email=='qa@company.co.kr'
    assert mocked.call_args.args[0].subject.startswith('[BioFlow 테스트]')
    assert post(client,body,'duplicate').json()['already_sent'] is True
    assert mocked.call_count==1
    assert client.post('/api/v1/mail/outbox/'+row['id']+'/sync',json={}).status_code==422
    assert client.post('/api/v1/mail/outbox/'+row['id']+'/confirm-reply',json={}).status_code==422
    current=client.get('/api/v1/workspace').json()
    replies=client.post('/api/v1/workspace/commands',json={'command':'receiveReplies','args':{},'expected_revision':current['revision']})
    assert replies.status_code==200,replies.text
    assert replies.json()['workflow']['inquiries'][1]['terms'] is None

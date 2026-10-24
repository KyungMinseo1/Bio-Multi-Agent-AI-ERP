from unittest.mock import AsyncMock
import pytest
from sqlalchemy import select
from app.models import OutboundEmail
from app.db import SessionLocal
from app.services import workspace, gmail_mcp
from app.services.mailer import MailConfigurationError, MailDeliveryError


@pytest.fixture
def quote(client, monkeypatch):
    monkeypatch.setenv('BIOFLOW_MAIL_MODE', 'live')
    monkeypatch.setenv('BIOFLOW_SMTP_DEFAULT_FROM', 'sender@example.test')
    monkeypatch.setenv('BIOFLOW_SMTP_ALLOWED_FROM', 'sender@example.test')
    monkeypatch.setenv('BIOFLOW_SMTP_DEFAULT_TO', 'rfq@supplier-b.co.kr')
    monkeypatch.setenv('BIOFLOW_SMTP_PASSWORD', '')
    monkeypatch.setenv('GMAIL_MCP_URL', '')
    s = workspace.execute(command='seed')['workflow']
    for vendor in s['data']['vendors']:
        vendor['email'] = 'rfq@supplier-' + vendor['id'].lower() + '.co.kr'
    s = workspace.execute(s, 'approveInquiry')['workflow']
    s = workspace.execute(s, 'startInquiries')['workflow']
    response = client.put('/api/v1/workspace', json={'workflow': s, 'expected_revision': 0})
    assert response.status_code == 200
    remote = response.json()
    draft = workspace.execute(s, 'quoteDraft', {'vendor': 'B'})['quoteDraft']
    return {**draft, 'sender_email': 'sender@example.test', 'recipient_email': 'rfq@supplier-b.co.kr',
            'expected_revision': remote['revision'], 'source_stamp': remote['stamp'],
            'delivery_mode': 'simulation', 'final_confirmation': True}


def post(client, quote, suffix='first'):
    return client.post('/api/v1/mail/quote-requests', json=quote, headers={'Idempotency-Key': 'request-identifier-' + suffix})


def test_final_approval_and_current_quantity_required(client, quote):
    assert post(client, {**quote, 'final_confirmation': False}).status_code == 422
    assert post(client, {**quote, 'required_quantity': 99}).status_code == 409
    assert post(client, {**quote, 'expected_revision': 99}).status_code == 409
    with SessionLocal() as db:
        assert db.scalar(select(OutboundEmail)) is None


def test_simulation_persists_approval_without_network_and_deduplicates(client, quote, monkeypatch):
    mocked = AsyncMock(side_effect=AssertionError('Simulation must not call Gmail'))
    monkeypatch.setattr(gmail_mcp, 'send_quote', mocked)
    a = post(client, quote)
    b = post(client, quote, 'new-browser-key')
    assert a.status_code == b.status_code == 200
    assert a.json()['status'] == 'simulated'
    assert b.json()['id'] == a.json()['id']
    assert b.json()['already_sent'] is True
    assert a.json()['payload']['required_quantity'] == 12
    mocked.assert_not_called()
    with SessionLocal() as db:
        assert len(db.scalars(select(OutboundEmail)).all()) == 1


def test_connection_failure_can_retry_but_sent_request_is_not_resent(client, quote, monkeypatch):
    payload = {**quote, 'delivery_mode': 'gmail_mcp'}
    mocked = AsyncMock(side_effect=MailConfigurationError('Connection unavailable'))
    monkeypatch.setattr(gmail_mcp, 'send_quote', mocked)
    assert post(client, payload).status_code == 502
    mocked.side_effect = None
    mocked.return_value = ('gmail-id', 'thread-id', 'rfq.csv')
    success = post(client, payload, 'retry')
    assert success.status_code == 200
    assert success.json()['thread_id'] == 'thread-id'
    assert post(client, payload, 'duplicate').json()['already_sent'] is True
    assert mocked.call_count == 2


def test_uncertain_delivery_blocks_automatic_retry(client, quote, monkeypatch):
    mocked = AsyncMock(side_effect=MailDeliveryError('unknown'))
    monkeypatch.setattr(gmail_mcp, 'send_quote', mocked)
    payload = {**quote, 'delivery_mode': 'gmail_mcp'}
    assert post(client, payload).status_code == 502
    assert post(client, payload, 'retry').status_code == 409
    assert mocked.call_count == 1


def test_real_recipient_must_match_registered_supplier(client, quote):
    assert post(client, {**quote, 'delivery_mode': 'gmail_mcp', 'recipient_email': 'unregistered@example.test'}).status_code == 422


def test_csv_import_preserves_version_and_rejects_invalid_rows(client, quote):
    data = client.get('/api/v1/workspace/csv').json()
    csv = data['sources']['production']
    invalid = client.put('/api/v1/workspace/csv/production', json={'content': csv.replace('2026-11-04', '2026-02-30'), 'expected_revision': data['revision']})
    assert invalid.status_code == 422
    assert client.get('/api/v1/workspace').json()['revision'] == data['revision']
    changed = client.put('/api/v1/workspace/csv/production', json={'content': csv.replace('"4"', '"5"', 1), 'expected_revision': data['revision']})
    assert changed.status_code == 200
    assert post(client, quote).status_code == 409


def test_mcp_status_reports_missing_runtime_config_not_fake_connected(client, quote):
    response = client.get('/api/v1/mail/mcp/status')
    assert response.status_code == 200
    assert response.json()['ready'] is False


def test_verified_reply_is_explicitly_confirmed_then_existing_agents_analyze(client, quote, monkeypatch):
    mocked=AsyncMock(return_value=('gmail-id','thread-id','rfq.csv'))
    monkeypatch.setattr(gmail_mcp,'send_quote',mocked)
    response=post(client,{**quote,'delivery_mode':'gmail_mcp'})
    dispatch_id=response.json()['id']
    reply={'id':'supplier-message','sender':'rfq@supplier-b.co.kr','subject':'Quote','body':'PR-IL7-20261024 supply confirmed','source':'gmail_mcp'}
    monkeypatch.setattr(gmail_mcp,'read_replies',AsyncMock(return_value=[reply]))
    assert client.post(f'/api/v1/mail/outbox/{dispatch_id}/sync',json={}).status_code==200
    current=client.get('/api/v1/workspace').json()
    terms=current['workflow']['data']['vendors'][1]
    invalid=client.post(f'/api/v1/mail/outbox/{dispatch_id}/confirm-reply',json={'message_id':'not-verified','expected_revision':current['revision'],'terms':terms})
    assert invalid.status_code==409
    accepted=client.post(f'/api/v1/mail/outbox/{dispatch_id}/confirm-reply',json={'message_id':'supplier-message','expected_revision':current['revision'],'terms':terms})
    assert accepted.status_code==200
    assert accepted.json()['workflow']['inquiries'][1]['status']=='공급 확인'
    analyzed=client.post('/api/v1/workspace/commands',json={'command':'analyze','args':{},'expected_revision':accepted.json()['revision']})
    assert analyzed.status_code==200
    assert analyzed.json()['workflow']['integration']['selected']=='B'


def test_reapproving_same_business_data_does_not_bypass_deduplication(client, quote):
    first = post(client, quote).json()
    current = client.get('/api/v1/workspace').json()
    workflow = current['workflow']
    workflow['inquiries'] = []
    workflow = workspace.execute(workflow, 'approveInquiry')['workflow']
    workflow = workspace.execute(workflow, 'startInquiries')['workflow']
    remote = client.put('/api/v1/workspace', json={'workflow':workflow,'expected_revision':current['revision']}).json()
    second = post(client, {**quote,'expected_revision':remote['revision'],'source_stamp':remote['stamp']}, 'new-approval')
    assert second.status_code == 200
    assert second.json()['already_sent'] is True
    assert second.json()['id'] == first['id']


def test_server_simulated_replies_exclude_real_dispatched_supplier(client, quote, monkeypatch):
    monkeypatch.setattr(gmail_mcp, 'send_quote', AsyncMock(return_value=('gmail-id','thread','quote.csv')))
    assert post(client,{**quote,'delivery_mode':'gmail_mcp'}).status_code==200
    current=client.get('/api/v1/workspace').json()
    result=client.post('/api/v1/workspace/commands',json={'command':'receiveReplies','args':{},'expected_revision':current['revision']})
    assert result.status_code==200
    b=next(q for q in result.json()['workflow']['inquiries'] if q['vendor']=='B')
    assert b['status']=='미회신'
    assert b['terms'] is None

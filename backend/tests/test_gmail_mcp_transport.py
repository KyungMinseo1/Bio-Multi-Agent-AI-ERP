"""Exercise the real MCP SDK over loopback; the fixture never contacts Gmail."""
import asyncio
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest
from app.schemas import QuoteEmailInput
from app.services import gmail_mcp
from app.services.mailer import MailConfigurationError


@pytest.fixture
def mcp_server(tmp_path, monkeypatch):
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    script = tmp_path / 'fake_gmail.py'
    script.write_text('''from mcp.server.fastmcp import FastMCP
mcp=FastMCP("Gmail transport fixture",host="127.0.0.1",port=PORT,json_response=True)
@mcp.tool()
def gmail_get_profile()->dict:
    return {"email":"sender@example.test"}
@mcp.tool()
def gmail_send_email(from_address:str,to:str,subject:str,payload:dict)->dict:
    assert from_address=="sender@example.test"
    assert to=="receiver@example.test"
    assert payload["mime_type"]=="multipart/mixed"
    assert payload["parts"][1]["content_disposition"]=="attachment"
    return {"id":"gmail-test-id","thread_id":"gmail-test-thread"}
@mcp.tool()
def gmail_search_emails(query:str,max_results:int)->dict:
    return {"messages":[{"id":"supplier-reply-id"}]}
@mcp.tool()
def gmail_read_email(message_id:str,format:str)->dict:
    return {"id":message_id,"thread_id":"gmail-test-thread","payload":{"headers":[{"name":"From","value":"Supplier <receiver@example.test>"},{"name":"Subject","value":"RE: PR-IL7-20261024 quote"}],"body":{"content":"PR-IL7-20261024: confirmed 12 vials"}}}
mcp.run(transport="streamable-http")
'''.replace('PORT', str(port)))
    with (tmp_path / 'server.log').open('w') as log:
        process = subprocess.Popen([sys.executable, str(script)], stdout=log, stderr=log)
        try:
            for _ in range(100):
                if process.poll() is not None:
                    pytest.fail('MCP fixture failed to start')
                try:
                    with socket.create_connection(('127.0.0.1', port), timeout=.1):
                        break
                except OSError:
                    time.sleep(.05)
            else:
                pytest.fail('MCP fixture startup timeout')
            monkeypatch.setenv('GMAIL_MCP_URL', f'http://127.0.0.1:{port}/mcp')
            monkeypatch.delenv('GMAIL_MCP_TOKEN', raising=False)
            for kind in ['PROFILE', 'SEND', 'SEARCH', 'READ']:
                monkeypatch.delenv('GMAIL_MCP_'+kind+'_TOOL', raising=False)
            yield
        finally:
            process.terminate()
            process.wait(timeout=5)


def test_runtime_mcp_profile_and_mime_send(mcp_server):
    status = asyncio.run(gmail_mcp.connection_status('sender@example.test'))
    assert status['ready'] is True
    payload = QuoteEmailInput(case_id='PR-IL7-20261024',vendor_id='B',vendor_name='B',sender_email='sender@example.test',recipient_email='receiver@example.test',subject='Quote request',body='Request 12 vials, simulation fixture only',material_code='MAT-IL7',material_name='IL-7',unit='vial',required_quantity=12,safety_stock=2,schedule=[{'production_id':'PROD-01','needed_date':'2026-11-04','quantity':4}])
    identifier, thread, filename = asyncio.run(gmail_mcp.send_quote(payload))
    assert identifier == 'gmail-test-id'
    assert thread == 'gmail-test-thread'
    assert filename.endswith('.csv')


def test_wrong_sender_account_is_blocked(mcp_server):
    with pytest.raises(MailConfigurationError, match="발신"):
        asyncio.run(gmail_mcp.connection_status('different@example.test'))


def test_incoming_reply_must_match_sender_case_and_thread(mcp_server):
    from types import SimpleNamespace
    delivery = SimpleNamespace(sender='sender@example.test',recipient='receiver@example.test',case_id='PR-IL7-20261024',thread_id='gmail-test-thread')
    found = asyncio.run(gmail_mcp.read_replies(delivery))
    assert found[0]['id'] == 'supplier-reply-id'
    delivery.thread_id = 'other-thread'
    assert asyncio.run(gmail_mcp.read_replies(delivery)) == []

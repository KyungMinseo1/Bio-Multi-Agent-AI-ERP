import asyncio
import base64
from email.parser import BytesParser
from email import policy
import httpx
import pytest
from app import gmail_gateway


def test_gateway_rejects_requests_without_local_bearer(monkeypatch):
    monkeypatch.setenv('GMAIL_MCP_TOKEN', 'private-test-gateway-token')
    async def inner(scope, receive, send):
        from starlette.responses import JSONResponse
        await JSONResponse({'ok':True})(scope,receive,send)
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=gmail_gateway.ProtectedMCP(inner)),base_url='http://test') as client:
            assert (await client.post('/mcp')).status_code == 401
            assert (await client.post('/mcp',headers={'Authorization':'Bearer private-test-gateway-token'})).status_code == 200
    asyncio.run(run())


def test_gateway_uses_verified_sender_and_rfc_mime(monkeypatch):
    requests = []
    async def fake(method,path,**kwargs):
        requests.append((method,path,kwargs))
        if path=='profile': return {'emailAddress':'sender@example.test'}
        return {'id':'google-id','threadId':'thread'}
    monkeypatch.setattr(gmail_gateway,'gmail',fake)
    parts={'mime_type':'multipart/mixed','parts':[{'mime_type':'text/plain','body':{'content':'Approved quote request'}},{'mime_type':'text/csv','filename':'quote.csv','body':{'base64_url_content':base64.urlsafe_b64encode(b'id,quantity\nB,12').decode()}}]}
    result=asyncio.run(gmail_gateway.gmail_send_email('sender@example.test','supplier@example.test','Quote',parts))
    assert result['id']=='google-id'
    raw=base64.urlsafe_b64decode(requests[-1][2]['json']['raw'])
    msg=BytesParser(policy=policy.default).parsebytes(raw)
    assert msg['To']=='supplier@example.test'
    assert list(msg.iter_attachments())[0].get_filename()=='quote.csv'
    requests.clear()
    with pytest.raises(ValueError,match='발신'):
        asyncio.run(gmail_gateway.gmail_send_email('wrong@example.test','supplier@example.test','Quote',parts))
    assert not any(method=='POST' for method,_,_ in requests)

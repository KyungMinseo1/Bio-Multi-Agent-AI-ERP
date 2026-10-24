"""Optional loopback Gmail MCP server, authenticated separately from the chat connector.
Run through scripts/run-local.py with BIOFLOW_GMAIL_MCP_LOCAL=1 and OAuth env values.
"""
import asyncio
import base64
import hmac
import os
from email.message import EmailMessage
from email.utils import parseaddr

import httpx
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request as GoogleRequest
from mcp.server.fastmcp import FastMCP
from starlette.responses import JSONResponse
from .config import setting

mcp = FastMCP("BioFlow Gmail", host="127.0.0.1", port=int(setting("BIOFLOW_GMAIL_MCP_PORT", "4180")), json_response=True)
_credentials = None


def credentials():
    global _credentials
    if _credentials is None:
        token, refresh = setting('GMAIL_ACCESS_TOKEN'), setting('GMAIL_REFRESH_TOKEN')
        if not token and not (refresh and setting('GMAIL_CLIENT_ID') and setting('GMAIL_CLIENT_SECRET')):
            raise ValueError('서버 환경에 Gmail OAuth 자격증명을 등록하세요. Codex 연결 토큰은 자동 공유되지 않습니다.')
        _credentials = Credentials(token=token or None, refresh_token=refresh or None, token_uri='https://oauth2.googleapis.com/token', client_id=setting('GMAIL_CLIENT_ID') or None, client_secret=setting('GMAIL_CLIENT_SECRET') or None, scopes=['https://www.googleapis.com/auth/gmail.send', 'https://www.googleapis.com/auth/gmail.readonly'])
    return _credentials


async def gmail(method, path, **kwargs):
    creds = credentials()
    try:
        if not creds.valid:
            await asyncio.to_thread(creds.refresh, GoogleRequest())
        async with httpx.AsyncClient(timeout=25) as client:
            response = await client.request(method, 'https://gmail.googleapis.com/gmail/v1/users/me/'+path, headers={'Authorization': 'Bearer '+creds.token}, **kwargs)
            if response.status_code == 401 and creds.refresh_token:
                await asyncio.to_thread(creds.refresh, GoogleRequest())
                response = await client.request(method, 'https://gmail.googleapis.com/gmail/v1/users/me/'+path, headers={'Authorization': 'Bearer '+creds.token}, **kwargs)
            if not response.is_success:
                raise ValueError('Gmail API 인증·권한 또는 요청 상태를 확인하세요.')
            return response.json()
    except Exception:
        raise ValueError('Gmail API 요청에 실패했습니다. OAuth 인증·권한과 메일함을 확인하세요.') from None


@mcp.tool()
async def gmail_get_profile() -> dict:
    data = await gmail('GET', 'profile')
    return {'email': data['emailAddress']}


@mcp.tool()
async def gmail_send_email(from_address: str, to: str, subject: str, payload: dict) -> dict:
    profile = await gmail_get_profile()
    if profile['email'].lower() != from_address.lower():
        raise ValueError('OAuth 계정과 발신 주소가 다릅니다.')
    if any(c in from_address+to+subject for c in '\r\n') or parseaddr(to)[1] != to or '@' not in to:
        raise ValueError('메일 헤더가 유효하지 않습니다.')
    message = EmailMessage()
    message['From'], message['To'], message['Subject'] = from_address, to, subject
    parts = payload.get('parts') or []
    if payload.get('mime_type') != 'multipart/mixed' or len(parts) != 2 or parts[0].get('mime_type') != 'text/plain' or parts[1].get('mime_type') != 'text/csv':
        raise ValueError('승인된 본문과 CSV 첨부 MIME 구성이 필요합니다.')
    message.set_content(parts[0].get('body', {}).get('content', ''))
    encoded = parts[1].get('body', {}).get('base64_url_content', '')
    attachment = base64.urlsafe_b64decode(encoded+'='*(-len(encoded)%4))
    if len(attachment) > 2_000_000:
        raise ValueError('CSV 첨부 크기 초과')
    filename = os.path.basename(parts[1].get('filename', 'quote.csv'))
    message.add_attachment(attachment, maintype='text', subtype='csv', filename=filename)
    data = await gmail('POST', 'messages/send', json={'raw': base64.urlsafe_b64encode(message.as_bytes()).decode()})
    return {'id': data['id'], 'thread_id': data.get('threadId', '')}


@mcp.tool()
async def gmail_search_emails(query: str, max_results: int = 10) -> dict:
    return await gmail('GET', 'messages', params={'q': query, 'maxResults': min(max(max_results, 1), 20)})


@mcp.tool()
async def gmail_read_email(message_id: str, format: str = 'full') -> dict:
    if not message_id.isalnum() or format != 'full':
        raise ValueError('Gmail 메시지 ID와 full 형식이 필요합니다.')
    data = await gmail('GET', 'messages/'+message_id, params={'format': 'full'})
    def normalize(part):
        body = part.get('body') or {}
        return {'headers': part.get('headers', []), 'mime_type': part.get('mimeType', ''), 'body': {'base64_url_content': body.get('data', '')}, 'parts': [normalize(p) for p in part.get('parts', [])]}
    return {'id': data['id'], 'thread_id': data.get('threadId', ''), 'payload': normalize(data.get('payload', {}))}


class ProtectedMCP:
    def __init__(self, app):
        self.app = app
    async def __call__(self, scope, receive, send):
        if scope['type'] == 'http':
            token = setting('GMAIL_MCP_TOKEN')
            authorization = dict(scope.get('headers', [])).get(b'authorization', b'').decode()
            if not token or not hmac.compare_digest(authorization, 'Bearer '+token):
                await JSONResponse({'error': 'Unauthorized MCP client'}, status_code=401)(scope, receive, send)
                return
        await self.app(scope, receive, send)


if __name__ == '__main__':
    import uvicorn
    if not setting('GMAIL_MCP_TOKEN'):
        raise SystemExit('GMAIL_MCP_TOKEN is required')
    uvicorn.run(ProtectedMCP(mcp.streamable_http_app()), host='127.0.0.1', port=int(setting('BIOFLOW_GMAIL_MCP_PORT', '4180')))

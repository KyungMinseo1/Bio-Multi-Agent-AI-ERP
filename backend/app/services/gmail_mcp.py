"""Runtime Gmail MCP client. Host-managed chat connectors do not expose app credentials."""
import asyncio
import base64
import json
import httpx
from contextlib import asynccontextmanager
from email.utils import parseaddr
from urllib.parse import urlsplit

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from ..config import setting
from .mailer import MailConfigurationError, MailDeliveryError, _attachment


def configured():
    return bool(setting("GMAIL_MCP_URL"))


def tool_name(kind):
    return setting(f"GMAIL_MCP_{kind.upper()}_TOOL", "gmail_" + {"profile": "get_profile", "send": "send_email", "search": "search_emails", "read": "read_email"}[kind])


@asynccontextmanager
async def session():
    url = setting("GMAIL_MCP_URL")
    parsed = urlsplit(url)
    if not url or parsed.username or parsed.password or parsed.query or (parsed.scheme != "https" and not (parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost", "::1"})):
        raise MailConfigurationError("ERP 서버의 GMAIL_MCP_URL을 HTTPS 또는 로컬 MCP 주소로 설정하세요.")
    token = setting("GMAIL_MCP_TOKEN")
    headers = {"Authorization": "Bearer " + token} if token else None
    async with asyncio.timeout(45):
        async with httpx.AsyncClient(headers=headers, timeout=httpx.Timeout(20, read=30), follow_redirects=False) as http_client:
            async with streamable_http_client(url, http_client=http_client) as (read, write, _):
                async with ClientSession(read, write) as client:
                    await client.initialize()
                    yield client


def configuration_error(exc):
    if isinstance(exc, MailConfigurationError):
        return exc
    for child in getattr(exc, 'exceptions', []):
        found = configuration_error(child)
        if found:
            return found
    return None


def unpack(result):
    if getattr(result, "isError", False):
        raise MailConfigurationError("Gmail MCP 도구가 오류를 반환했습니다.")
    data = getattr(result, "structuredContent", None)
    if data is not None:
        return data
    for part in getattr(result, "content", []):
        if getattr(part, "type", None) == "text":
            try:
                return json.loads(part.text)
            except ValueError:
                pass
    raise MailConfigurationError("Gmail MCP가 확인 가능한 구조화 결과를 반환하지 않았습니다.")


async def profile(client, sender):
    listed = {t.name for t in (await client.list_tools()).tools}
    if any(tool_name(k) not in listed for k in ("profile", "send")):
        raise MailConfigurationError("Gmail MCP의 profile/send 도구 이름과 권한을 확인하세요.")
    data = unpack(await client.call_tool(tool_name("profile"), {}))
    account = (data.get("email") or data.get("emailAddress") or "").lower()
    if not account or account != sender.lower():
        raise MailConfigurationError("Gmail MCP 연결 계정이 승인된 발신 주소와 다릅니다. 발신 계정으로 다시 연결하세요.")
    return account


async def connection_status(sender):
    if not configured():
        return {"configured": False, "ready": False, "message": "ERP 서버용 Gmail MCP URL과 인증을 설정하세요. Codex의 연결 계정은 서버 연결과 별개입니다."}
    try:
        async with session() as client:
            account = await profile(client, sender)
        return {"configured": True, "ready": True, "account": account, "message": "Gmail MCP 발신 계정 확인 완료"}
    except MailConfigurationError:
        raise
    except Exception as exc:
        raise configuration_error(exc) or MailConfigurationError("Gmail MCP 연결 확인에 실패했습니다. 서버·인증 설정을 확인하고 다시 시도하세요.") from None


async def send_quote(payload):
    attempted = False
    try:
        async with session() as client:
            await profile(client, payload.sender_email)
            filename, attachment = _attachment(payload)
            arguments = {"from_address": payload.sender_email, "to": payload.recipient_email, "subject": payload.subject,
                         "payload": {"mime_type": "multipart/mixed", "parts": [
                             {"mime_type": "text/plain", "charset": "utf-8", "body": {"content": payload.body}},
                             {"mime_type": "text/csv", "filename": filename, "content_disposition": "attachment",
                              "body": {"base64_url_content": base64.urlsafe_b64encode(attachment).decode()}}]}}
            attempted = True
            data = unpack(await client.call_tool(tool_name("send"), arguments))
            if not data.get("id"):
                raise ValueError("Missing Gmail message ID")
            return str(data["id"]), str(data.get("thread_id") or data.get("threadId") or ""), filename
    except Exception as exc:
        if attempted:
            raise MailDeliveryError("Gmail MCP 발송 결과가 불확실합니다. 메일함 확인 전 재전송하지 마세요.") from None
        raise configuration_error(exc) or MailConfigurationError("Gmail MCP 연결에 실패했습니다. 설정 확인 후 재시도하세요.") from None


def message_text(part):
    body = part.get("body") or {}
    text = body.get("content") or ""
    if not text and body.get("base64_url_content"):
        try:
            raw = body["base64_url_content"]
            text = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)).decode("utf-8", errors="replace")
        except (ValueError, TypeError):
            pass
    return text + "\n" + "\n".join(message_text(p) for p in part.get("parts", []) if isinstance(p, dict))


async def read_replies(delivery):
    try:
        async with session() as client:
            await profile(client, delivery.sender)
            data = unpack(await client.call_tool(tool_name("search"), {"query": f'from:{delivery.recipient} "{delivery.case_id}"', "max_results": 10}))
            found = data.get("messages") or data.get("emails") or data.get("results") or []
            result = []
            for item in found:
                identifier = item.get("id") or item.get("message_id")
                if not identifier:
                    continue
                message = unpack(await client.call_tool(tool_name("read"), {"message_id": identifier, "format": "full"}))
                payload = message.get("payload") or message
                headers = {h["name"].lower(): h.get("value", "") for h in payload.get("headers", [])}
                sender = parseaddr(headers.get("from") or message.get("from", ""))[1].lower()
                text = message_text(payload)
                thread = str(message.get("thread_id") or message.get("threadId") or "")
                if sender != delivery.recipient or delivery.case_id not in (headers.get("subject", "") + text):
                    continue
                if delivery.thread_id and thread != delivery.thread_id:
                    continue
                result.append({"id": str(identifier), "sender": sender, "subject": headers.get("subject", ""), "body": text[:24000], "thread_id": thread, "source": "gmail_mcp"})
            return result
    except MailConfigurationError:
        raise
    except Exception:
        raise MailConfigurationError("Gmail MCP 회신 조회에 실패했습니다. 설정과 읽기 권한을 확인하세요.") from None

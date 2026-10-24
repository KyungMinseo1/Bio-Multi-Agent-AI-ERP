"""Server-side SMTP delivery for approved BioFlow quote requests."""
import csv
import io
import json
import os
import re
import smtplib
import ssl
import tempfile
from dataclasses import dataclass
from datetime import date
from email.message import EmailMessage
from email.utils import formataddr
from pathlib import Path

from dotenv import dotenv_values

from ..config import setting
from ..schemas import QuoteEmailInput

EMAIL_RE = re.compile(r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+$")
RUNTIME_MAIL_FILE = Path(__file__).resolve().parents[3] / ".runtime" / "mail.env"


@dataclass(frozen=True)
class MailConfiguration:
    host: str
    port: int
    security: str
    username: str
    password: str
    default_sender: str
    default_recipient: str
    allowed_senders: tuple[str, ...]

    @property
    def configured(self) -> bool:
        return bool(
            self.host and self.username and self.password and self.allowed_senders
            and self.security in {"starttls", "ssl"} and 1 <= self.port <= 65535
        )


class MailConfigurationError(Exception):
    pass


class MailDeliveryError(Exception):
    pass


def mail_configuration() -> MailConfiguration:
    try:
        port = int(setting("BIOFLOW_SMTP_PORT", "587"))
    except ValueError:
        port = 0
    username = setting("BIOFLOW_SMTP_USERNAME").strip()
    default = setting("BIOFLOW_SMTP_DEFAULT_FROM", username).strip().lower()
    configured_senders = setting("BIOFLOW_SMTP_ALLOWED_FROM", default).split(",")
    allowed = tuple(dict.fromkeys(x.strip().lower() for x in configured_senders if x.strip()))
    saved = dotenv_values(RUNTIME_MAIL_FILE) if RUNTIME_MAIL_FILE.is_file() else {}
    saved_password = saved.get("BIOFLOW_SMTP_PASSWORD", "") if saved.get("BIOFLOW_SMTP_USERNAME") == username else ""
    return MailConfiguration(
        host=setting("BIOFLOW_SMTP_HOST").strip(),
        port=port,
        security=setting("BIOFLOW_SMTP_SECURITY", "starttls").strip().lower(),
        username=username,
        password=setting("BIOFLOW_SMTP_PASSWORD") or saved_password or "",
        default_sender=default,
        default_recipient=setting("BIOFLOW_SMTP_DEFAULT_TO").strip().lower(),
        allowed_senders=allowed,
    )


def public_mail_settings() -> dict:
    config = mail_configuration()
    return {
        "configured": config.configured,
        "provider": "SMTP",
        "mcp_configured": bool(setting("GMAIL_MCP_URL")),
        "simulation_available": True,
        "default_sender": config.default_sender,
        "default_recipient": config.default_recipient,
        "allowed_senders": list(config.allowed_senders),
        "security": config.security,
        "credential_present": bool(config.password),
        "connection_setup_available": config.host.lower() == "smtp.gmail.com",
        "authentication_required": True,
        "reply_sync": False,
    }


def connect_gmail(app_password: str) -> dict:
    """Verify SMTP authentication without sending mail, then save a private credential."""
    config = mail_configuration()
    password = "".join(app_password.split())
    if config.host.lower() != "smtp.gmail.com" or config.security not in {"starttls", "ssl"} or not 1 <= config.port <= 65535:
        raise MailConfigurationError("Gmail SMTP 서버 설정을 확인하세요.")
    if setting("BIOFLOW_SMTP_PASSWORD"):
        raise MailConfigurationError("환경변수에 SMTP 비밀번호가 이미 설정되어 있습니다. 서버 환경에서 변경하세요.")
    sender = validate_email_address(config.default_sender)
    if config.username.lower() != sender or sender not in config.allowed_senders:
        raise MailConfigurationError("SMTP 계정과 허용 발신 주소를 확인하세요.")
    if not re.fullmatch(r"[A-Za-z0-9]{16}", password):
        raise ValueError("Gmail에서 발급한 16자리 앱 비밀번호를 입력하세요.")
    try:
        if config.security == "ssl":
            with smtplib.SMTP_SSL(config.host, config.port, timeout=25, context=ssl.create_default_context()) as server:
                server.login(config.username, password)
        else:
            with smtplib.SMTP(config.host, config.port, timeout=25) as server:
                server.ehlo()
                server.starttls(context=ssl.create_default_context())
                server.ehlo()
                server.login(config.username, password)
    except (smtplib.SMTPException, OSError, TimeoutError):
        raise MailDeliveryError("Gmail 인증에 실패했습니다. 앱 비밀번호와 계정 보안 설정을 확인하세요.") from None
    RUNTIME_MAIL_FILE.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=RUNTIME_MAIL_FILE.parent, delete=False) as output:
            temporary = Path(output.name)
            os.chmod(temporary, 0o600)
            output.write(f"BIOFLOW_SMTP_USERNAME={json.dumps(config.username)}\nBIOFLOW_SMTP_PASSWORD={json.dumps(password)}\n")
        os.replace(temporary, RUNTIME_MAIL_FILE)
    finally:
        if temporary and temporary.exists():
            temporary.unlink()
    return {"status": "connected", **public_mail_settings()}


def validate_email_address(value: str) -> str:
    address = value.strip()
    if not EMAIL_RE.fullmatch(address) or any(ch in address for ch in "\r\n,;<>"):
        raise ValueError("올바른 단일 이메일 주소를 입력하세요.")
    return address.lower()


def _attachment(payload: QuoteEmailInput) -> tuple[str, bytes]:
    safe_case = re.sub(r"[^A-Za-z0-9_-]", "_", payload.case_id)[:80] or "request"
    filename = f"BioFlow_RFQ_{safe_case}.csv"
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow([
        "구매요청번호", "공급업체", "원료코드", "품명", "총 요청수량", "단위", "안전재고 참고",
        "생산번호", "필요일", "회차 요청량", "공급단가(업체기입)", "MOQ(업체기입)",
        "운송비(업체기입)", "회차 확약일(업체기입)", "납품Lot/CoA(업체기입)", "회신/비고",
    ])
    for line in payload.schedule:
        writer.writerow([
            payload.case_id, payload.vendor_name, payload.material_code, payload.material_name,
            payload.required_quantity, payload.unit, payload.safety_stock,
            line.production_id, line.needed_date, line.quantity, "", "", "", "", "", "",
        ])
    writer.writerow([
        payload.case_id, payload.vendor_name, payload.material_code, payload.material_name,
        payload.required_quantity, payload.unit, payload.safety_stock,
        "총계", "", sum(line.quantity for line in payload.schedule), "", "", "", "", "", "",
    ])
    return filename, ("\ufeff" + output.getvalue()).encode("utf-8")


def send_quote_email(payload: QuoteEmailInput, message_id: str) -> tuple[str, str]:
    config = mail_configuration()
    if not config.configured:
        raise MailConfigurationError("SMTP 설정이 완전하지 않습니다.")
    sender = validate_email_address(payload.sender_email)
    recipient = validate_email_address(payload.recipient_email)
    if sender not in config.allowed_senders:
        raise MailConfigurationError("발신 주소가 서버 허용 목록에 없습니다.")
    if "\r" in payload.subject or "\n" in payload.subject:
        raise ValueError("제목에 줄바꿈을 넣을 수 없습니다.")
    if len(payload.body.strip()) < 10:
        raise ValueError("메일 본문을 확인하세요.")
    for line in payload.schedule:
        date.fromisoformat(line.needed_date)

    msg = EmailMessage()
    msg["From"] = formataddr(("BioFlow 구매팀", sender))
    msg["To"] = recipient
    msg["Subject"] = payload.subject.strip()
    msg["Message-ID"] = message_id
    msg["X-BioFlow-Case"] = payload.case_id
    msg.set_content(payload.body.strip())
    filename, contents = _attachment(payload)
    msg.add_attachment(contents, maintype="text", subtype="csv", filename=filename)

    try:
        if config.security == "ssl":
            with smtplib.SMTP_SSL(config.host, config.port, timeout=25, context=ssl.create_default_context()) as server:
                server.login(config.username, config.password)
                refused = server.send_message(msg, from_addr=sender, to_addrs=[recipient])
        else:
            with smtplib.SMTP(config.host, config.port, timeout=25) as server:
                server.ehlo()
                server.starttls(context=ssl.create_default_context())
                server.ehlo()
                server.login(config.username, config.password)
                refused = server.send_message(msg, from_addr=sender, to_addrs=[recipient])
    except (smtplib.SMTPException, OSError, TimeoutError) as exc:
        raise MailDeliveryError(type(exc).__name__) from None
    if refused:
        raise MailDeliveryError("recipient_refused")
    return msg["Message-ID"], filename

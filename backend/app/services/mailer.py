"""Server-side SMTP delivery for approved BioFlow quote requests."""
import csv
import io
import re
import smtplib
import ssl
from dataclasses import dataclass
from datetime import date
from email.message import EmailMessage
from email.utils import formataddr, make_msgid

from ..config import setting
from ..schemas import QuoteEmailInput

EMAIL_RE = re.compile(r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+$")


@dataclass(frozen=True)
class MailConfiguration:
    host: str
    port: int
    security: str
    username: str
    password: str
    default_sender: str
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
    return MailConfiguration(
        host=setting("BIOFLOW_SMTP_HOST").strip(),
        port=port,
        security=setting("BIOFLOW_SMTP_SECURITY", "starttls").strip().lower(),
        username=username,
        password=setting("BIOFLOW_SMTP_PASSWORD"),
        default_sender=default,
        allowed_senders=allowed,
    )


def public_mail_settings() -> dict:
    config = mail_configuration()
    return {
        "configured": config.configured,
        "provider": "SMTP",
        "default_sender": config.default_sender if config.configured else "",
        "allowed_senders": list(config.allowed_senders) if config.configured else [],
        "security": config.security if config.configured else None,
        "authentication_required": True,
        "reply_sync": False,
    }


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

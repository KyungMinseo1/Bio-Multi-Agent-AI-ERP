"""Approval and source-version checks shared by simulation, SMTP and Gmail MCP."""
import hashlib
import json
from email.utils import make_msgid
from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from ..models import OutboundEmail, Scenario, AuditEvent, uid, now, utc_iso
from . import workspace, gmail_mcp
from .mailer import mail_configuration, validate_email_address, send_quote_email, MailConfigurationError, MailDeliveryError


def view(row):
    return {"id": row.id, "case_id": row.case_id, "vendor_id": row.vendor_id, "vendor_name": row.vendor_name,
            "sender": row.sender, "recipient": row.recipient, "subject": row.subject, "status": row.status,
            "delivery_mode": row.delivery_mode, "message_id": row.message_id, "thread_id": row.thread_id,
            "source_stamp": row.source_stamp, "payload": row.payload, "responses": row.responses or [],
            "error_code": row.error_code, "created_at": utc_iso(row.created_at)}


async def dispatch(db, body, key, user):
    if not body.final_confirmation:
        raise HTTPException(422, "수신처·수량·일정·본문을 확인하고 최종 발송 승인해야 합니다.")
    if not 16 <= len(key) <= 200:
        raise HTTPException(422, "발송 요청 식별자가 필요합니다.")
    row = db.get(Scenario, workspace.WORKSPACE)
    if not row or row.revision != body.expected_revision or row.data.get("workspace_stamp") != body.source_stamp:
        raise HTTPException(409, "원본 데이터 또는 승인 버전이 변경됐습니다. 저장·재검증 후 다시 승인하세요.")
    result = workspace.execute(row.data["_workflow"], "quoteDraft", {"vendor": body.vendor_id})
    canonical = result["quoteDraft"]
    for name in ("case_id", "vendor_name", "material_code", "material_name", "unit", "required_quantity", "safety_stock", "schedule"):
        value = [line.model_dump() for line in body.schedule] if name == "schedule" else getattr(body, name)
        if canonical[name] != value:
            raise HTTPException(409, "미리보기의 수량·일정·원료가 현재 ERP 계산과 다릅니다.")
    try:
        sender, recipient = validate_email_address(body.sender_email), validate_email_address(body.recipient_email)
        if "\r" in body.subject or "\n" in body.subject or len(body.body.strip()) < 10:
            raise ValueError("제목과 본문을 확인하세요.")
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    config = mail_configuration()
    if body.delivery_mode != "simulation":
        if sender not in config.allowed_senders:
            raise HTTPException(422, "발신 주소가 서버 허용 목록과 다릅니다.")
        if recipient not in {canonical.get("recipient_email"), config.default_recipient}:
            raise HTTPException(422, "CSV 업체 주소 또는 서버에 등록된 수신처만 승인할 수 있습니다.")
    business_source = [result["workflow"]["data"], result["workflow"]["orders"], result["workflow"]["produced"], body.vendor_id, recipient, body.delivery_mode]
    fingerprint = hashlib.sha256(json.dumps(business_source, sort_keys=True).encode()).hexdigest()
    dedup_key = "quote:" + fingerprint
    prior = db.scalar(select(OutboundEmail).where(OutboundEmail.idempotency_key == dedup_key))
    if prior and prior.status in {"sent", "simulated", "replied"}:
        return {**view(prior), "already_sent": True}
    if prior and prior.status != "failed":
        raise HTTPException(409, "같은 견적 요청이 처리 중이거나 결과가 불확실합니다. 발송 이력을 확인하세요.")
    if prior:
        changed = db.execute(update(OutboundEmail).where(OutboundEmail.id == prior.id, OutboundEmail.status == "failed").values(status="sending", error_code=None))
        if changed.rowcount != 1:
            db.rollback()
            raise HTTPException(409, "다른 발송 요청이 재시도를 처리하고 있습니다.")
        delivery = prior
        delivery.status = "sending"
        delivery.subject = body.subject
        delivery.source_stamp = body.source_stamp
        delivery.payload = {**body.model_dump(), "approved_data_revision": result["workflow"]["data"]["revision"]}
    else:
        delivery = OutboundEmail(id=uid(), idempotency_key=dedup_key, case_id=body.case_id, vendor_id=body.vendor_id,
                                 vendor_name=body.vendor_name, actor_id=user.id, sender=sender, recipient=recipient,
                                 subject=body.subject, status="sending", delivery_mode=body.delivery_mode,
                                 source_stamp=body.source_stamp, payload={**body.model_dump(), "approved_data_revision": result["workflow"]["data"]["revision"]}, created_at=now(), updated_at=now())
        db.add(delivery)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "동일 견적 요청이 이미 접수됐습니다. 이력을 새로고침하세요.") from None
    try:
        db.refresh(row)
        if row.revision != body.expected_revision:
            raise MailConfigurationError("발송 전 원본 버전이 변경됐습니다.")
        if body.delivery_mode == "simulation":
            delivery.status = "simulated"
            delivery.message_id = "SIM-" + delivery.id
        elif body.delivery_mode == "gmail_mcp":
            delivery.message_id, delivery.thread_id, _ = await gmail_mcp.send_quote(body)
            delivery.status = "sent"
        else:
            delivery.message_id, _ = send_quote_email(body, make_msgid(domain="bioflow.local"))
            delivery.status = "sent"
    except (MailConfigurationError, MailDeliveryError, ValueError) as exc:
        delivery.status = "uncertain" if isinstance(exc, MailDeliveryError) else "failed"
        delivery.error_code = type(exc).__name__
        delivery.updated_at = now()
        db.add(AuditEvent(scenario_id=body.case_id, actor=user.email, action="견적 요청 발송 오류", before=None,
                          after={"id": delivery.id, "mode": body.delivery_mode, "status": delivery.status}))
        db.commit()
        raise HTTPException(502, str(exc) if isinstance(exc, MailConfigurationError) else "발송 결과를 확인하지 못했습니다. 이력을 확인하세요. 결과 불확실 시 자동 재전송하지 않습니다.") from None
    delivery.updated_at = now()
    db.add(AuditEvent(scenario_id=body.case_id, actor=user.email, action="견적 요청 최종 승인·처리", before=None,
                      after={"id": delivery.id, "mode": body.delivery_mode, "status": delivery.status, "source_stamp": body.source_stamp, "quantity": body.required_quantity, "recipient": recipient}))
    db.commit()
    return {**view(delivery), "already_sent": False}

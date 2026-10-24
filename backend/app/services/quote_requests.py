"""Approval-bound drafts and delivery through the existing SMTP service."""
from email.utils import make_msgid
from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from ..models import OutboundEmail, Scenario, now, uid, utc_iso
from . import mailer, workspace
from .erp import audit


PROTECTED = {"sending", "sent", "unknown"}


def public(row):
    return {"id": row.id, "case_id": row.case_id, "vendor_id": row.vendor_id,
            "vendor_name": row.vendor_name, "sender": row.sender, "recipient": row.recipient,
            "original_recipient": row.request_data.get("recipient_email", row.recipient),
            "subject": row.subject, "status": row.status, "mode": row.mode,
            "reply_status": row.reply_status, "message_id": row.message_id,
            "error_code": row.error_code, "draft": row.request_data,
            "created_at": utc_iso(row.created_at), "updated_at": utc_iso(row.updated_at)}


def protected_vendors(db, case_id):
    return list(db.scalars(select(OutboundEmail.vendor_id).where(
        OutboundEmail.case_id == case_id, OutboundEmail.status.in_(PROTECTED),
        OutboundEmail.mode.in_(["live", "legacy", "test"]))))


def prepare(db, body, key, user):
    if not 16 <= len(key) <= 200:
        raise HTTPException(422, "유효한 Idempotency-Key가 필요합니다.")
    scope = f"{body.inquiry_id}:{mailer.mail_mode()}"
    prior_key = db.scalar(select(OutboundEmail).where(OutboundEmail.idempotency_key == key))
    if prior_key and prior_key.scope != scope:
        raise HTTPException(409, "다른 업체 또는 문의에 사용된 발송 키입니다.")
    row = db.scalar(select(OutboundEmail).where(OutboundEmail.scope == scope))
    if row and (row.case_id != body.case_id or row.vendor_id != body.vendor_id):
        raise HTTPException(409, "발송 키와 업체·구매요청 식별자가 일치하지 않습니다.")
    if row and row.status in PROTECTED:
        if row.status == "sent":
            return row, True
        raise HTTPException(409, detail={"code": "delivery_check_required", "status": row.status,
                                       "message": "처리 중이거나 발송 결과 확인이 필요합니다. 재발송하지 않습니다."})
    scenario = db.get(Scenario, workspace.WORKSPACE)
    if not scenario or scenario.revision != body.expected_revision:
        raise HTTPException(409, "승인된 서버 업무 버전이 변경됐습니다. 다시 확인하세요.")
    # Hold the same workspace write lock used by ERP mutations until the draft/claim commits.
    locked = db.execute(update(Scenario).where(Scenario.id == workspace.WORKSPACE,
                        Scenario.revision == body.expected_revision).values(revision=body.expected_revision))
    if locked.rowcount != 1:
        raise HTTPException(409, "서버 업무 버전 충돌")
    db.refresh(scenario)
    workflow = scenario.data["_workflow"]
    checked = workspace.execute(workflow, "startInquiries")  # validates the current first approval
    inquiry = next((q for q in workflow["inquiries"] if q["id"] == body.inquiry_id and q["vendor"] == body.vendor_id), None)
    vendor = next((v for v in workflow["data"]["vendors"] if v["id"] == body.vendor_id), None)
    if (not inquiry or not vendor or not vendor.get("approved") or not vendor.get("productApproved")
        or inquiry["status"] not in {"요청중", "미회신"}):
        raise HTTPException(409, "승인된 공급 확인 요청이 없거나 이미 회신 처리됐습니다.")
    if body.case_id != checked["case_id"]:
        raise HTTPException(422, "구매 요청 식별자가 일치하지 않습니다.")
    product = workflow["data"]["products"][0]
    expected_schedule = [{"production_id": p["id"], "needed_date": p["date"], "quantity": p["il7"]}
                         for p in workflow["data"]["productions"]]
    required = int(checked["projection"]["_canonical_calculation"]["materials"][0]["new_order_quantity"])
    if (body.vendor_name != vendor["name"] or body.recipient_email.strip().lower() != vendor.get("quoteEmail", "").strip().lower()
        or body.material_code != product["id"] or body.material_name != product["name"]
        or body.unit != product["unit"] or body.required_quantity != required
        or body.safety_stock != product["safety"] or [x.model_dump() for x in body.schedule] != expected_schedule):
        raise HTTPException(409, "업체 주소 또는 첨부 데이터가 승인된 ERP와 다릅니다. 업체 정보 수정·저장 후 다시 여세요.")
    # Legacy and previous-mode delivery records also prevent a second live dispatch.
    if mailer.mail_mode() == "live" and db.scalar(select(OutboundEmail.id).where(
        OutboundEmail.case_id == body.case_id, OutboundEmail.vendor_id == body.vendor_id,
        OutboundEmail.status.in_(PROTECTED), OutboundEmail.mode.in_(["live", "legacy"]))) is not None:
        raise HTTPException(409, "이 업체의 실제 발송 기록을 먼저 확인하세요.")
    if row is not None:
        db.refresh(row)
        if row.status in PROTECTED:
            raise HTTPException(409, "이미 처리 중이거나 발송됐습니다. 이력을 확인하세요.")
    if row is None:
        row = OutboundEmail(id=uid(), idempotency_key=key, scope=scope, case_id=body.case_id,
            vendor_id=body.vendor_id, vendor_name=vendor["name"], actor_id=user.id,
            sender=body.sender_email, recipient=body.recipient_email, subject=body.subject,
            mode=mailer.mail_mode(), status="draft", reply_status="not_requested",
            created_at=now(), updated_at=now(), request_data={})
        db.add(row)
    row.sender, row.subject = body.sender_email.strip().lower(), body.subject.strip()
    row.recipient = body.recipient_email.strip().lower()
    row.request_data = body.model_dump()
    row.updated_at = now()
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "동일 문의가 처리 중입니다. 발송 이력을 새로 확인하세요.") from None
    return row, False


def save(db, body, key, user, dispatch=False):
    row, prior = prepare(db, body, key, user)
    if prior:
        return {**public(row), "already_sent": True}
    # Save first: malformed addresses/configuration and provider failures never discard edits.
    db.commit()
    if not dispatch:
        return public(row)
    try:
        mailer.validate_email_address(body.recipient_email)
        if "\r" in body.subject or "\n" in body.subject:
            raise ValueError("제목에 줄바꿈을 넣을 수 없습니다.")
        if row.mode == "preview":
            row.status = "preview"
            row.reply_status = "not_requested"
            db.commit()
            return public(row)
        target = mailer.delivery_recipient(body.recipient_email)
        config = mailer.mail_configuration()
        sender = mailer.validate_email_address(body.sender_email)
        if not config.configured or sender not in config.allowed_senders:
            raise mailer.MailConfigurationError("SMTP와 허용 발신 주소를 설정하세요.")
    except (ValueError, mailer.MailConfigurationError) as exc:
        raise HTTPException(422, str(exc)) from None
    locked = db.execute(update(Scenario).where(Scenario.id == workspace.WORKSPACE,
                        Scenario.revision == body.expected_revision).values(revision=body.expected_revision))
    if locked.rowcount != 1:
        db.rollback()
        raise HTTPException(409, "발송 직전 승인된 업무 버전이 변경됐습니다. 초안을 다시 확인하세요.")
    # Claim once across processes, even if clients reopen the composer with different keys.
    claimed = db.execute(update(OutboundEmail).where(OutboundEmail.id == row.id, OutboundEmail.updated_at == row.updated_at,
        OutboundEmail.status.in_(["draft", "preview", "failed"])).values(
            status="sending", recipient=target, error_code=None, message_id=make_msgid(domain="bioflow.local"), updated_at=now()))
    if claimed.rowcount != 1:
        db.rollback()
        raise HTTPException(409, "이미 처리 중입니다. 이력을 확인하세요.")
    db.commit()
    db.refresh(row)
    try:
        message_id, _ = mailer.send_quote_email(body, row.message_id)
        row.status, row.message_id = "sent", message_id
        row.reply_status = "awaiting_reply" if row.mode == "live" else "test_only"
    except mailer.MailDeliveryUnknown:
        row.status, row.error_code, row.reply_status = "unknown", "smtp_result_unknown", "check_required"
    except (mailer.MailConfigurationError, mailer.MailDeliveryError, ValueError):
        row.status, row.error_code = "failed", "delivery_rejected"
    except Exception:
        # Unexpected errors after a network call must never invite an automatic retry.
        row.status, row.error_code, row.reply_status = "unknown", "delivery_result_unknown", "check_required"
    row.updated_at = now()
    audit(db, user.email, "mail." + row.status, body.case_id,
          after={"id": row.id, "vendor_id": row.vendor_id, "mode": row.mode,
                 "recipient": row.recipient, "reply_status": row.reply_status})
    db.commit()
    return public(row)

import copy
from decimal import Decimal
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from ..models import Approval, Recommendation, DiscussionRun, Scenario, ERPRecord, ExternalIssue, uid, now
from .erp import snapshot, lock_revision, audit, enqueue_recalculation, changed_since
from .external_sources import refresh_enabled, CollectionError
from .planning import validate_strategy
from ..config import planning_date


def stale(db, rec):
    raise HTTPException(409, detail={"code": "stale", "message": "Recommendation snapshot changed; start a new discussion", "expected_revision": rec.snapshot_revision, "current_revision": db.get(Scenario, rec.scenario_id).revision, "changed_items": changed_since(db, rec.scenario_id), "discussion_path": f"/api/v1/scenarios/{rec.scenario_id}/discussions"})


async def approve(db, recommendation_id, body, key, user):
    if not key or len(key) > 200:
        raise HTTPException(422, "Idempotency-Key header is required (maximum 200 characters)")
    prior = db.scalar(select(Approval).where(Approval.actor_id == user.id, Approval.idempotency_key == key))
    if prior:
        if prior.recommendation_id != recommendation_id:
            raise HTTPException(409, "Idempotency key already used for another recommendation")
        return prior.data
    rec = db.get(Recommendation, recommendation_id)
    if not rec:
        raise HTTPException(404, "Recommendation not found")
    if rec.scenario_id == "main-workspace":
        raise HTTPException(409, "통합 업무의 추천을 주 업무 화면으로 가져와 2차 발주 승인을 진행하세요.")
    scenario = db.get(Scenario, rec.scenario_id)
    if body.expected_revision != rec.snapshot_revision or scenario.revision != rec.snapshot_revision:
        stale(db, rec)
    if rec.status != "proposed":
        raise HTTPException(409, "Recommendation already selected or superseded")
    existing = db.scalar(select(Approval).where(Approval.scenario_id == rec.scenario_id, Approval.snapshot_revision == rec.snapshot_revision))
    if existing:
        raise HTTPException(409, "A recommendation from this snapshot was already approved")
    # End the read transaction before network work. Refresh writes its own durable source run records.
    db.rollback()
    try:
        synchronization = await refresh_enabled()
    except CollectionError as exc:
        raise HTTPException(503, detail={"code": "external_verification_failed", "message": str(exc), "retry_path": f"/api/v1/recommendations/{recommendation_id}/approve"}) from None
    db.expire_all()
    rec = db.get(Recommendation, recommendation_id)
    current = snapshot(db, rec.scenario_id)
    if current["revision"] != rec.snapshot_revision:
        stale(db, rec)
    fresh = validate_strategy(current, rec.data["candidate"], as_of=planning_date())
    validation = fresh["validation"]
    if not validation.get("hard_constraints_passed") or not validation.get("target_delivery_met") or not validation.get("cash_feasible", True):
        raise HTTPException(409, detail={"code": "validation_failed", "message": "Current quality, schedule, supply, capacity or cash conditions prevent approval", "validation": validation})
    old = rec.data["candidate"]
    if any(fresh.get(k) != old.get(k) for k in ("quantity", "deliveries", "costs", "payment_obligations")):
        stale(db, rec)
    unverified = [issue["id"] for issue in current["issues"] if issue.get("verification_status", "unverified") in {"unverified", "relevance_unconfirmed"}]
    unverified.extend(issue.id for issue in db.scalars(select(ExternalIssue)) if issue.data.get("verification_status", "unverified") in {"unverified", "relevance_unconfirmed"})
    if unverified and not body.acknowledge_unverified:
        raise HTTPException(422, detail={"code": "acknowledgement_required", "message": "Unverified external notices do not prove an impact. Acknowledge remaining relevance uncertainty before approval.", "issue_ids": unverified})
    total = Decimal(fresh["costs"]["total"])
    material_id = fresh["material_id"]
    relevant_budgets = [b for b in current["budgets"] if b.get("active", True) and not b.get("inactive") and (not b.get("material_id") or b["material_id"] == material_id)]
    budgets = [b for b in relevant_budgets if not b.get("payment_date")]
    available = sum((Decimal(str(b.get("approved_amount", 0))) - Decimal(str(b.get("committed_amount", 0))) for b in budgets), Decimal(0))
    additional = max(Decimal(0), total - available)
    if additional > 0 or validation.get("requires_budget_approval"):
        try:
            explicit = Decimal(body.budget_approval_amount or "0")
        except Exception:
            raise HTTPException(422, "budget_approval_amount must be a decimal")
        if not explicit.is_finite() or explicit < additional or not body.budget_approval_reason or not body.budget_approval_reason.strip():
            raise HTTPException(422, detail={"code": "budget_approval_required", "additional_amount": str(additional), "message": "Explicit additional budget amount and approval reason required"})
    else:
        explicit = Decimal(0)
    authorized_amount = explicit
    try:
        lock_revision(db, rec.scenario_id, rec.snapshot_revision)
        # This CAS is the cross-process lock even on SQLite; all mutable ERP writes use it.
        if not budgets:
            if explicit < total:
                raise HTTPException(422, "No purchase budget is available")
            budget = {"id": uid(), "material_id": material_id, "approved_amount": str(explicit), "committed_amount": "0", "revision": 1, "approval_reason": body.budget_approval_reason}
            row = ERPRecord(scenario_id=rec.scenario_id, collection="budgets", record_id=budget["id"], revision=1, data=budget)
            db.add(row)
            budgets = [budget]
            explicit = Decimal(0)
        remaining = total
        for index, budget in enumerate(budgets):
            row = db.scalar(select(ERPRecord).where(ERPRecord.scenario_id == rec.scenario_id, ERPRecord.collection == "budgets", ERPRecord.record_id == budget["id"]))
            if row is None:  # Newly allocated budget pending flush.
                db.flush()
                row = db.scalar(select(ERPRecord).where(ERPRecord.scenario_id == rec.scenario_id, ERPRecord.collection == "budgets", ERPRecord.record_id == budget["id"]))
            before = copy.deepcopy(row.data)
            value = copy.deepcopy(row.data)
            if index == 0 and explicit:
                value["approved_amount"] = str(Decimal(value["approved_amount"]) + explicit)
                value["additional_approval_reason"] = body.budget_approval_reason
            capacity = max(Decimal(0), Decimal(value["approved_amount"]) - Decimal(str(value.get("committed_amount", 0))))
            amount = min(remaining, capacity)
            value["committed_amount"] = str(Decimal(str(value.get("committed_amount", 0))) + amount)
            value["revision"] = row.revision + 1
            row.data, row.revision = value, value["revision"]
            remaining -= amount
            audit(db, user.email, "budget.commit", rec.scenario_id, before, value)
        if remaining > 0:
            raise HTTPException(409, "Budget commitment cannot be satisfied")
        for payment in fresh["payment_obligations"]:
            unpaid = Decimal(payment["amount"])
            limits = [b for b in relevant_budgets if b.get("payment_date") == payment["payment_date"]]
            for limit in limits:
                row = db.scalar(select(ERPRecord).where(ERPRecord.scenario_id == rec.scenario_id, ERPRecord.collection == "budgets", ERPRecord.record_id == limit["id"]))
                before = copy.deepcopy(row.data)
                value = copy.deepcopy(row.data)
                capacity = max(Decimal(0), Decimal(str(value.get("cash_limit", 0))) - Decimal(str(value.get("cash_committed", 0))))
                amount = min(unpaid, capacity)
                value["cash_committed"] = str(Decimal(str(value.get("cash_committed", 0))) + amount)
                value["revision"] = row.revision + 1
                row.data, row.revision = value, value["revision"]
                unpaid -= amount
                audit(db, user.email, "cash.commit", rec.scenario_id, before, value)
            if unpaid > 0:
                raise HTTPException(409, "Payment-date cash commitment cannot be satisfied")
        offers = {o["id"]: o for o in current["offers"]}
        lines = []
        for offer_id in fresh.get("offer_ids", [fresh.get("offer_id")]):
            if not offer_id:
                continue
            deliveries = [d for d in fresh["deliveries"] if d["offer_id"] == offer_id]
            offer = offers[offer_id]
            lines.append({"offer_id": offer_id, "supplier_id": offer["supplier_id"], "material_id": material_id, "quantity": str(sum((Decimal(d["quantity"]) for d in deliveries), Decimal(0))), "unit_price": offer["unit_price"]})
        po_id = uid()
        order = {"id": po_id, "code": f"PO-{now():%Y%m%d}-{po_id[:8].upper()}", "name": "내부 승인 발주", "revision": 1, "material_id": material_id, "status": "approved", "internal_only": True, "recommendation_id": rec.id, "run_id": rec.run_id, "snapshot_revision": rec.snapshot_revision, "lines": lines, "deliveries": fresh["deliveries"], "quantity": fresh["quantity"], "total_cost": str(total), "costs": fresh["costs"], "confirmed": validation.get("supply_evidence_level") == "confirmed", "approved_by": user.email, "approved_at": now().isoformat(), "rationale_items": rec.data["rationale_items"], "remaining_risks": rec.data.get("remaining_risks", []), "quality_use_approval": "not_granted"}
        db.add(ERPRecord(scenario_id=rec.scenario_id, collection="purchase_orders", record_id=po_id, revision=1, data=order))
        result = {"id": po_id, "purchase_order": order, "scenario_revision": rec.snapshot_revision + 1, "external_sync": synchronization, "message": "내부 발주 등록 완료. 공급업체 전송 및 QC/QA 사용 승인이 아닙니다."}
        db.add(Approval(scenario_id=rec.scenario_id, snapshot_revision=rec.snapshot_revision, recommendation_id=rec.id, actor_id=user.id, idempotency_key=key, amount=total, data=result))
        rec.status = "selected"
        db.get(DiscussionRun, rec.run_id).status = "completed"
        audit(db, user.email, "purchase_order.approve", rec.scenario_id, after={**order, "budget_approval_amount": str(authorized_amount), "budget_approval_reason": body.budget_approval_reason, "acknowledged_issue_ids": unverified})
        enqueue_recalculation(db, rec.scenario_id)
        # The selected run is completed, not stale merely because its own PO was registered.
        db.get(DiscussionRun, rec.run_id).status = "completed"
        db.commit()
        return result
    except IntegrityError:
        db.rollback()
        prior = db.scalar(select(Approval).where(Approval.actor_id == user.id, Approval.idempotency_key == key))
        if prior and prior.recommendation_id == recommendation_id:
            return prior.data
        raise HTTPException(409, "This snapshot was approved concurrently; no additional order was created") from None
    except Exception as exc:
        db.rollback()
        if isinstance(exc, HTTPException) and exc.status_code == 409:
            prior = db.scalar(select(Approval).where(Approval.actor_id == user.id, Approval.idempotency_key == key))
            if prior and prior.recommendation_id == recommendation_id:
                return prior.data
        raise

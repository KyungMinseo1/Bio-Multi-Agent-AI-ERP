import copy
from datetime import date
from decimal import Decimal, InvalidOperation
from uuid import UUID
from fastapi import HTTPException
from sqlalchemy import select, update
from ..config import COLLECTIONS
from ..models import Scenario, ERPRecord, AuditEvent, Job, DiscussionRun, uid
from ..scenarios import load_scenario
from ..db import insert_if_missing
from ..models import utc_iso


REQUIRED = {
    "materials": ["name", "base_unit"], "suppliers": ["name"],
    "lots": ["material_id", "quantity", "expiry_date", "qc_status", "qa_status"],
    "reservations": ["lot_id", "production_plan_id", "quantity"],
    "consumptions": ["lot_id", "quantity"], "requirements": ["material_id", "quantity", "production_plan_id", "use_date"],
    "offers": ["material_id", "supplier_id", "unit_price", "moq", "order_multiple", "valid_until"],
    "supplier_materials": ["material_id", "supplier_id"],
    "storage_capacities": ["storage_condition", "capacity"],
    "budgets": ["approved_amount"], "production_plans": ["name"],
    "customer_orders": ["product", "delivery_date", "quantity"], "issues": ["summary"],
    "resource_calendars": ["resource_type", "capacity"],
    "purchase_orders": ["material_id", "status", "deliveries"],
}
NUMERIC = {"quantity", "total_quantity", "safety_stock", "daily_usage_fallback", "unit_price", "moq", "order_multiple", "available_quantity", "capacity", "approved_amount", "committed_amount", "cash_limit", "transport_cost", "testing_cost", "storage_cost_per_unit_day", "disposal_cost_per_unit", "space_per_unit", "conversion_factor", "production_quantity"}
NUMERIC.update({"consumed_quantity", "cash_committed", "reserved"})
POSITIVE = {"moq", "order_multiple", "conversion_factor", "space_per_unit"}
REFS = {"material_id": "materials", "supplier_id": "suppliers", "lot_id": "lots", "production_plan_id": "production_plans", "customer_order_id": "customer_orders", "offer_id": "offers", "purchase_order_id": "purchase_orders"}


def ensure_scenario(db, scenario_id):
    existing = db.get(Scenario, scenario_id)
    if existing:
        return existing
    try:
        data = load_scenario(scenario_id)
    except (KeyError, ValueError, FileNotFoundError):
        raise HTTPException(404, "Scenario not found")
    metadata = {k: v for k, v in data.items() if k not in COLLECTIONS}
    inserted = insert_if_missing(db, Scenario, {"id": scenario_id, "revision": int(data.get("revision", 1)), "data": metadata}, ["id"])
    row = db.get(Scenario, scenario_id)
    if inserted.rowcount == 0:
        return row
    for collection in COLLECTIONS:
        for record in data.get(collection, []):
            value = copy.deepcopy(record)
            value.setdefault("revision", 1)
            db.add(ERPRecord(scenario_id=scenario_id, collection=collection, record_id=value["id"], revision=value["revision"], data=value))
    db.flush()
    return row


def snapshot(db, scenario_id):
    row = ensure_scenario(db, scenario_id)
    data = copy.deepcopy(row.data)
    data.pop('_workflow', None)
    data.update(id=scenario_id, revision=row.revision)
    data.update({key: [] for key in COLLECTIONS})
    records = db.scalars(select(ERPRecord).where(ERPRecord.scenario_id == scenario_id).order_by(ERPRecord.collection, ERPRecord.record_id)).all()
    for record in records:
        data[record.collection].append(copy.deepcopy(record.data))
    return data


def lock_revision(db, scenario_id, expected=None):
    row = ensure_scenario(db, scenario_id)
    old = row.revision if expected is None else expected
    result = db.execute(update(Scenario).where(Scenario.id == scenario_id, Scenario.revision == old).values(revision=old + 1))
    if result.rowcount != 1:
        db.rollback()
        current = db.get(Scenario, scenario_id)
        raise HTTPException(409, detail={"code": "stale", "message": "ERP data changed; recalculate and restart discussion", "current_revision": current.revision, "expected_revision": old, "changed_items": changed_since(db, scenario_id)})
    db.expire(row)
    return old + 1


def changed_since(db, scenario_id):
    rows = db.scalars(select(AuditEvent).where(AuditEvent.scenario_id == scenario_id).order_by(AuditEvent.created_at.desc()).limit(15)).all()
    return [{"action": r.action, "at": utc_iso(r.created_at), "id": (r.after or r.before or {}).get("id")} for r in rows]


def audit(db, actor, action, scenario_id=None, before=None, after=None):
    db.add(AuditEvent(actor=actor, action=action, scenario_id=scenario_id, before=before, after=after))


def enqueue_recalculation(db, scenario_id):
    if not db.scalar(select(Job.id).where(Job.scenario_id == scenario_id, Job.kind == "recalculate", Job.status == "queued")):
        db.add(Job(scenario_id=scenario_id, kind="recalculate", payload={}))
    for run in db.scalars(select(DiscussionRun).where(DiscussionRun.scenario_id == scenario_id, DiscussionRun.status.in_(["completed", "awaiting_review"]))):
        run.status = "stale"


def decimal(value, name):
    try:
        number = Decimal(str(value))
        if not number.is_finite():
            raise InvalidOperation()
        return number
    except (InvalidOperation, ValueError, TypeError):
        raise HTTPException(422, f"{name} must be a finite decimal")


def validate_record(data, collection, state, previous=None):
    if data.get("inactive") is True:
        data["active"] = False
    if any(key.lower() in {"password", "password_hash", "api_key", "secret", "session_secret"} or key.lower().endswith("_api_key") for key in data):
        raise HTTPException(422, "Secrets must be configured only through server environment variables")
    for key in REQUIRED.get(collection, []):
        if data.get(key) is None or data.get(key) == "":
            raise HTTPException(422, f"{key} is required")
    for key, value in list(data.items()):
        if key in NUMERIC and value is not None:
            number = decimal(value, key)
            if number < 0 or (key in POSITIVE and number <= 0):
                raise HTTPException(422, f"{key} must be {'positive' if key in POSITIVE else 'nonnegative'}")
            data[key] = str(number)
        if key.endswith("_date") or key in {"valid_until", "as_of", "date"}:
            if value:
                try:
                    date.fromisoformat(str(value))
                except ValueError:
                    raise HTTPException(422, f"{key} must be an ISO calendar date")
        if key.endswith("_days") and value is not None:
            if isinstance(value, bool) or not str(value).isdigit():
                raise HTTPException(422, f"{key} must be a nonnegative integer")
        if key in REFS and value:
            if not any(r["id"] == value for r in state[REFS[key]]):
                raise HTTPException(422, f"Unknown {key}")
    for field in ("confirmed", "allow_split", "active", "inactive", "approved", "material_approved", "supplier_approved", "is_synthetic"):
        if field in data and not isinstance(data[field], bool):
            raise HTTPException(422, f"{field} must be boolean")
    if "unit_conversions" in data:
        if not isinstance(data["unit_conversions"], dict):
            raise HTTPException(422, "unit_conversions must map units to positive factors")
        data["unit_conversions"] = {unit: str(decimal(factor, "conversion_factor")) for unit, factor in data["unit_conversions"].items()}
        if any(decimal(factor, "conversion_factor") <= 0 for factor in data["unit_conversions"].values()):
            raise HTTPException(422, "Unit conversion factors must be positive")
    if collection in {"offers", "purchase_orders"} and "deliveries" in data:
        if not isinstance(data["deliveries"], list):
            raise HTTPException(422, "deliveries must be an array")
        normalized = []
        for delivery in data["deliveries"]:
            if not isinstance(delivery, dict) or not delivery.get("arrival_date") or "quantity" not in delivery:
                raise HTTPException(422, "Each delivery requires quantity and arrival_date")
            value = copy.deepcopy(delivery)
            if decimal(value["quantity"], "delivery.quantity") <= 0:
                raise HTTPException(422, "Delivery quantity must be positive")
            value["quantity"] = str(decimal(value["quantity"], "delivery.quantity"))
            for key in ("arrival_date", "available_date", "expiry_date", "payment_date"):
                if value.get(key):
                    try:
                        date.fromisoformat(value[key])
                    except (ValueError, TypeError):
                        raise HTTPException(422, f"Invalid delivery {key}")
            if "confirmed" in value and not isinstance(value["confirmed"], bool):
                raise HTTPException(422, "Delivery confirmed must be boolean")
            normalized.append(value)
        data["deliveries"] = normalized
    if collection in {"reservations", "consumptions"} and decimal(data["quantity"], "quantity") <= 0:
        raise HTTPException(422, "Reservation/consumption quantity must be positive")
    if collection == "resource_calendars" and data["resource_type"] not in {"qc", "production"}:
        raise HTTPException(422, "resource_type must be qc or production")
    if collection == "budgets":
        if previous and any(decimal(data.get(key, 0), key) != decimal(previous.get(key, 0), key) for key in ("committed_amount", "cash_committed")):
            raise HTTPException(422, "Budget and cash commitments are maintained by the approval transaction")
        if decimal(data.get("committed_amount", 0), "committed_amount") > decimal(data["approved_amount"], "approved_amount"):
            raise HTTPException(422, "Committed budget cannot exceed approved amount")
        if decimal(data.get("cash_committed", 0), "cash_committed") > decimal(data.get("cash_limit", 0), "cash_limit"):
            raise HTTPException(422, "Cash commitments cannot exceed payment-date cash limit")
    if collection == "lots":
        if data["qc_status"] not in {"pending", "passed", "failed", "hold"} or data["qa_status"] not in {"pending", "approved", "rejected", "hold"}:
            raise HTTPException(422, "Invalid QC/QA status")
    if collection == "materials" and previous and data.get("base_unit") != previous.get("base_unit"):
        if any(r.get("material_id") == data["id"] for c in COLLECTIONS if c != "materials" for r in state[c]):
            raise HTTPException(409, "Cannot change unit of a material in use")
    if collection == "lots" and previous:
        referenced = any(r.get("lot_id") == data["id"] for c in ("reservations", "consumptions") for r in state[c])
        if referenced and any(data.get(key) != previous.get(key) for key in ("material_id", "unit")):
            raise HTTPException(409, "Cannot change material or unit of a lot in use")
    if data.get("material_id") and data.get("unit"):
        material = next(m for m in state["materials"] if m["id"] == data["material_id"])
        if data["unit"] != material["base_unit"]:
            factors = material.get("unit_conversions", {})
            if data["unit"] not in factors or decimal(factors[data["unit"]], "conversion_factor") <= 0:
                raise HTTPException(422, "Unregistered unit conversion")
            if "quantity" in data:
                data["quantity"] = str(decimal(data["quantity"], "quantity") * decimal(factors[data["unit"]], "conversion_factor"))
            data["unit"] = material["base_unit"]
    if collection in {"reservations", "consumptions", "lots"}:
        lot_id = data["id"] if collection == "lots" else data["lot_id"]
        lot = data if collection == "lots" else next(l for l in state["lots"] if l["id"] == lot_id)
        reservations = [r for r in state["reservations"] if r.get("lot_id") == lot_id and r["id"] != data["id"] and r.get("active", True)]
        consumptions = [r for r in state["consumptions"] if r.get("lot_id") == lot_id and r["id"] != data["id"]]
        if collection == "reservations" and data.get("active", True):
            reservations.append(data)
        if collection == "consumptions":
            consumptions.append(data)
            key = data.get("idempotency_key")
            if key and any(r.get("idempotency_key") == key for r in state["consumptions"] if r["id"] != data["id"]):
                raise HTTPException(409, "Consumption already recorded")
            if not key:
                raise HTTPException(422, "Consumption requires idempotency_key")
        used = max(decimal(lot.get("consumed_quantity", 0), "consumed_quantity"), sum((decimal(r["quantity"], "quantity") for r in consumptions), Decimal(0)))
        # Recorded consumption fulfills its own production reservation, never another production's allocation.
        reserved_by_plan = {}
        for reservation in reservations:
            plan = reservation.get("production_plan_id")
            reserved_by_plan[plan] = reserved_by_plan.get(plan, Decimal(0)) + decimal(reservation["quantity"], "quantity")
        remaining_reserved = Decimal(0)
        for plan, quantity in reserved_by_plan.items():
            own_consumed = sum((decimal(c["quantity"], "quantity") for c in consumptions if c.get("production_plan_id") == plan), Decimal(0))
            remaining_reserved += max(Decimal(0), quantity - own_consumed)
        if used + remaining_reserved > decimal(lot.get("quantity", lot.get("total_quantity", 0)), "quantity"):
            raise HTTPException(409, "Lot consumption and reservations exceed stock")
    return data


def mutate(db, scenario_id, collection, body, actor, record_id=None):
    if scenario_id == "main-workspace":
        raise HTTPException(409, "통합 업무의 원본은 구매요청·원료·생산·공급업체 폼에서 수정한 뒤 서버에 저장하세요. 파생 ERP 표를 별도로 수정할 수 없습니다.")
    if collection not in COLLECTIONS:
        raise HTTPException(404, "Unknown collection")
    state = snapshot(db, scenario_id)
    row = None
    previous = None
    if record_id:
        row = db.scalar(select(ERPRecord).where(ERPRecord.scenario_id == scenario_id, ERPRecord.collection == collection, ERPRecord.record_id == record_id))
        if not row:
            raise HTTPException(404, "Record not found")
        if body.get("revision") != row.revision:
            raise HTTPException(409, detail={"code": "revision_conflict", "current_revision": row.revision})
        previous = copy.deepcopy(row.data)
    elif body.get("id") and any(r["id"] == body["id"] for r in state[collection]):
        raise HTTPException(409, "Record already exists")
    data = {**(previous or {}), **body, "id": record_id or body.get("id") or uid(), "revision": (row.revision + 1) if row else 1}
    try:
        if not isinstance(data["id"], str):
            raise ValueError()
        UUID(data["id"])
    except (ValueError, TypeError):
        raise HTTPException(422, "Record id must be a UUID")
    validate_record(data, collection, state, previous)
    lock_revision(db, scenario_id, state["revision"])
    if row:
        row.data, row.revision = data, data["revision"]
    else:
        db.add(ERPRecord(scenario_id=scenario_id, collection=collection, record_id=data["id"], revision=1, data=data))
    audit(db, actor, f"{collection}.{'update' if row else 'create'}", scenario_id, previous, data)
    enqueue_recalculation(db, scenario_id)
    db.commit()
    return data

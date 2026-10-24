"""Calendar-day, Decimal-only planning. Future quality release is always a forecast.

All evidence IDs are stable for a scenario/revision. This module has no database,
network, provider or clock dependency when an as_of date is supplied.
"""
from collections import defaultdict
from copy import deepcopy
from datetime import date, timedelta
from decimal import Decimal, ROUND_CEILING
from itertools import combinations
from uuid import NAMESPACE_URL, uuid5

ZERO = Decimal("0")
ONE = Decimal("1")


def dec(value=0):
    result = Decimal(str(value if value is not None else 0))
    if not result.is_finite():
        raise ValueError("Quantity and cost must be finite")
    return result


def day(value):
    return value if isinstance(value, date) else date.fromisoformat(str(value)[:10])


def identifier(*parts):
    return str(uuid5(NAMESPACE_URL, "bio-erp/calculation/" + "/".join(map(str, parts))))


def json_safe(value):
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    return value


def active(records):
    return [record for record in records if record.get("active", True)]


def remaining(data, lot):
    # consumed_quantity is a cumulative ERP summary; ledger entries are not added twice.
    entries = {r.get("id", str(i)): r for i, r in enumerate(data.get("consumptions", []))
               if r.get("lot_id") == lot["id"]}
    consumed = max(dec(lot.get("consumed_quantity")), sum((dec(r["quantity"]) for r in entries.values()), ZERO))
    quantity = dec(lot["quantity"])
    if quantity < ZERO or consumed < ZERO or consumed > quantity:
        raise ValueError(f"Invalid lot balance: {lot['id']}")
    return quantity - consumed


def reservations(data, lot_id):
    grouped = {}
    for row in active(data.get("reservations", [])):
        if row.get("lot_id") != lot_id:
            continue
        quantity = dec(row["quantity"])
        if quantity < ZERO:
            raise ValueError(f"Negative reservation: {row['id']}")
        production = row.get("production_plan_id")
        if production not in grouped:
            grouped[production] = {**row, "quantity": ZERO}
        grouped[production]["quantity"] += quantity
    entries = {row.get("id", str(index)): row for index, row in enumerate(data.get("consumptions", []))
               if row.get("lot_id") == lot_id}
    for production, row in grouped.items():
        consumed = sum((dec(entry["quantity"]) for entry in entries.values()
                        if production is not None and entry.get("production_plan_id") == production), ZERO)
        row["quantity"] = max(ZERO, row["quantity"] - consumed)
    return list(grouped.values())


def quality_ok(lot):
    return (lot.get("qc_status") == "passed" and lot.get("qa_status") == "approved"
            and lot.get("temperature_status", "passed") == "passed")


def material_requirements(data, material, as_of):
    plans = {p["id"]: p for p in active(data.get("production_plans", []))}
    result = []
    horizon = as_of + timedelta(days=int(material.get("planning_horizon_days", 60)))
    for row in active(data.get("requirements", [])):
        if row.get("material_id") != material["id"]:
            continue
        use = day(row["use_date"])
        if use < as_of or use > horizon:
            continue
        conversion = ONE
        if row.get("unit", material["base_unit"]) != material["base_unit"]:
            conversion = dec(material.get("unit_conversions", {}).get(row["unit"]))
            if conversion <= ZERO:
                raise ValueError(f"Missing positive unit conversion: {row['id']}")
        quantity = dec(row["quantity"]) * conversion
        if quantity < ZERO:
            raise ValueError("Requirement quantity cannot be negative")
        plan = plans.get(row.get("production_plan_id"), {})
        duration_fields = ("production_days", "finished_testing_days", "packaging_days", "shipping_days", "customer_transport_days")
        latest = None
        if plan.get("customer_delivery_date") and all(field in plan for field in duration_fields):
            latest = day(plan["customer_delivery_date"]) - timedelta(days=sum(int(plan[field]) for field in duration_fields))
        result.append({**row, "date": use, "quantity": quantity, "latest_use_date": latest})
    # A daily rate is an alternative for dates without an explicit production schedule.
    rate = dec(material.get("daily_usage_fallback"))
    if rate > ZERO and not result:
        for offset in range(1, (horizon - as_of).days + 1):
            use = as_of + timedelta(days=offset)
            result.append({"id": identifier(material["id"], "daily", use), "date": use,
                           "quantity": rate, "production_plan_id": None, "latest_use_date": None})
    return sorted(result, key=lambda r: (r["date"], r["id"]))


def issue_targets(issue):
    """Latest confirmation for each exact scope wins over earlier history."""
    targets = issue.get("links") or [issue]
    latest = {}
    for target in sorted(targets, key=lambda row: str(row.get("confirmed_at") or "")):
        scope = tuple(target.get(key) for key in ("supplier_id", "material_id", "offer_id", "lot_id", "lot_code", "purchase_order_id"))
        latest[scope] = target
    return latest.values()


def quality_blocked(data, item):
    for issue in active(data.get("issues", [])):
        for target in issue_targets(issue):
            if target.get("verification_status", issue.get("verification_status")) != "quality_impact_confirmed":
                continue
            keys = [key for key in ("supplier_id", "material_id", "offer_id", "lot_id", "lot_code", "purchase_order_id") if target.get(key)]
            if keys and all(target[key] == item.get(key) for key in keys):
                return True
    return False


def inventory(data, material, as_of):
    result = []
    for lot in active(data.get("lots", [])):
        if lot.get("material_id") != material["id"]:
            continue
        quantity = remaining(data, lot)
        held = reservations(data, lot["id"])
        reserved = sum((dec(r["quantity"]) for r in held), ZERO)
        if any(dec(r["quantity"]) < ZERO for r in held) or reserved > quantity:
            raise ValueError(f"Reservation exceeds remaining stock: {lot['id']}")
        if quality_ok(lot) and not quality_blocked(data, {**lot, "lot_id": lot["id"], "lot_code": lot.get("code")}) and day(lot["expiry_date"]) >= as_of:
            result.append({"id": lot["id"], "quantity": quantity, "arrival": as_of,
                "available": as_of, "expiry": day(lot["expiry_date"]), "reservations": deepcopy(held),
                "candidate": False, "offer_id": None})
    for po in active(data.get("purchase_orders", [])):
        if po.get("status") not in ("approved", "confirmed", "received"):
            continue
        for index, shipment in enumerate(po.get("deliveries", [])):
            if shipment.get("material_id", po.get("material_id")) != material["id"] or not shipment.get("confirmed", False):
                continue
            if quality_blocked(data, {**po, **shipment, "material_id": material["id"], "purchase_order_id": po["id"]}):
                continue
            # Once received into a Lot, the PO must not count a second time.
            if shipment.get("lot_id") or shipment.get("received", False):
                continue
            if not shipment.get("available_date") or not shipment.get("expiry_date"):
                continue
            result.append({"id": shipment.get("id", identifier(po["id"], index)),
                "quantity": dec(shipment["quantity"]), "arrival": day(shipment["arrival_date"]),
                "available": day(shipment["available_date"]), "expiry": day(shipment["expiry_date"]),
                "reservations": [], "candidate": False, "offer_id": None, "po_id": po["id"]})
    return result


def project(data, material, as_of, shipments=(), optimistic=False):
    stocks = inventory(data, material, as_of)
    for shipment in shipments:
        if (shipment["confirmed"] or optimistic) and shipment.get("temperature_status", "passed") == "passed" and not shipment.get("quality_hold", False):
            stocks.append({"id": shipment["id"], "quantity": dec(shipment["quantity"]),
                "arrival": day(shipment["arrival_date"]), "available": day(shipment["available_date"]),
                "expiry": day(shipment["expiry_date"]), "reservations": [], "candidate": True,
                "offer_id": shipment["offer_id"]})
    requirements = material_requirements(data, material, as_of)
    timeline, usages, shortages = [], [], []
    safety = dec(material.get("safety_stock"))
    first_safety = None
    def free(on):
        return sum((max(ZERO, stock["quantity"] - sum((dec(r["quantity"]) for r in stock["reservations"]), ZERO))
                    for stock in stocks if stock["available"] <= on <= stock["expiry"]), ZERO)
    if free(as_of) < safety:
        first_safety = as_of
    timeline.append({"date": as_of, "event": "opening", "quantity": ZERO,
                     "available_quantity": free(as_of), "evidence_refs": [s["id"] for s in stocks if s["available"] <= as_of]})
    events = defaultdict(list)
    for stock in stocks:
        if stock["available"] > as_of:
            events[stock["available"]].append(("quality_release_forecast", stock))
        events[stock["expiry"] + timedelta(days=1)].append(("expiry", stock))
    for requirement in requirements:
        events[requirement["date"]].append(("demand", requirement))
    horizon = as_of + timedelta(days=int(material.get("planning_horizon_days", 60)))
    for on in sorted(events):
        if on > horizon:
            continue
        for kind, row in sorted(events[on], key=lambda item: item[0] == "demand"):
            if kind != "demand":
                if free(on) < safety and first_safety is None:
                    first_safety = on
                timeline.append({"date": on, "event": kind,
                    "quantity": row["quantity"] if kind != "expiry" else -row["quantity"],
                    "available_quantity": free(on), "evidence_refs": [row["id"]]})
                continue
            need = row["quantity"]
            for stock in sorted(stocks, key=lambda s: (s["expiry"], s["available"], s["arrival"], s["id"])):
                if not stock["available"] <= on <= stock["expiry"]:
                    continue
                own = [r for r in stock["reservations"] if r.get("production_plan_id") == row.get("production_plan_id")]
                other = sum((dec(r["quantity"]) for r in stock["reservations"] if r not in own), ZERO)
                take = min(need, max(ZERO, stock["quantity"] - other))
                if take <= ZERO:
                    continue
                stock["quantity"] -= take
                need -= take
                reserved_used = take
                for reservation in own:
                    used = min(dec(reservation["quantity"]), reserved_used)
                    reservation["quantity"] = dec(reservation["quantity"]) - used
                    reserved_used -= used
                usages.append({"date": on, "quantity": take, "stock_id": stock["id"], "requirement_id": row["id"],
                               "offer_id": stock["offer_id"], "candidate": stock["candidate"]})
                if need == ZERO:
                    break
            if need > ZERO:
                shortages.append({"date": on, "quantity": need, "requirement_id": row["id"],
                                  "production_plan_id": row.get("production_plan_id")})
            balance = free(on)
            if balance < safety and first_safety is None:
                first_safety = on
            timeline.append({"date": on, "event": "production_use", "quantity": -row["quantity"],
                "available_quantity": balance, "shortage_quantity": need,
                "production_plan_id": row.get("production_plan_id"), "evidence_refs": [row["id"]]})
    last_use = max((r["date"] for r in requirements), default=as_of)
    return {"timeline": timeline, "stocks": stocks, "usages": usages, "shortages": shortages,
            "ending_available": free(last_use), "first_safety": first_safety,
            "first_shortage": shortages[0]["date"] if shortages else None}


def rounding(quantity, offer):
    multiple, minimum = dec(offer.get("order_multiple", 1)), dec(offer.get("moq", 1))
    if multiple <= ZERO or minimum < ZERO:
        raise ValueError(f"Invalid MOQ/order multiple: {offer['id']}")
    return (max(quantity, minimum) / multiple).to_integral_value(rounding=ROUND_CEILING) * multiple


def matching_issues(data, offer, shipment=None):
    for issue in active(data.get("issues", [])):
        targets = issue_targets(issue)
        for target in targets:
            if target.get("supplier_id") and target["supplier_id"] != offer["supplier_id"]:
                continue
            if target.get("material_id") and target["material_id"] != offer["material_id"]:
                continue
            if target.get("offer_id") and target["offer_id"] != offer["id"]:
                continue
            if target.get("purchase_order_id"):
                continue
            if target.get("lot_id") and (shipment is None or target["lot_id"] != shipment.get("lot_id")):
                continue
            if target.get("lot_code") and (shipment is None or target["lot_code"] != shipment.get("lot_code")):
                continue
            if not any(target.get(key) for key in ("supplier_id", "material_id", "offer_id", "lot_code", "lot_id")):
                continue
            yield issue, target
            break


def resource_slot(data, kind, start, duration, booked, line_id=None):
    calendars = [r for r in active(data.get("resource_calendars", [])) if r.get("resource_type") == kind
                 and (not r.get("line_id") or r.get("line_id") == line_id)]
    if not calendars:
        return start, False
    for offset in range(366):
        candidate = start + timedelta(days=offset)
        feasible = True
        for step in range(max(1, duration)):
            on = candidate + timedelta(days=step)
            dated = [r for r in calendars if r.get("date") == on.isoformat()]
            defaults = [r for r in calendars if not r.get("date")]
            selected = dated or defaults
            capacity = sum((dec(r.get("capacity")) - dec(r.get("reserved")) for r in selected), ZERO)
            if capacity - booked[(kind, line_id, on)] < ONE:
                feasible = False
                break
        if feasible:
            for step in range(max(1, duration)):
                booked[(kind, line_id, candidate + timedelta(days=step))] += ONE
            return candidate, True
    return start + timedelta(days=366), False


def build_deliveries(data, offer, quantity, as_of, split, booked):
    explicit = offer.get("deliveries", [])
    if split and explicit:
        allocations, remaining_quantity = [], quantity
        for item in explicit:
            take = min(dec(item["quantity"]), remaining_quantity)
            if take > ZERO:
                allocations.append({**item, "quantity": take})
                remaining_quantity -= take
        # Explicit schedules are supply commitments, never invent an extra shipment.
        if remaining_quantity > ZERO:
            allocations.append({**explicit[-1], "quantity": remaining_quantity,
                "confirmed": False, "uncontracted": True})
    elif explicit:
        allocations = [{**explicit[0], "quantity": quantity}]
    else:
        arrival = as_of + timedelta(days=sum(int(offer.get(key, 0)) for key in ("preparation_days", "transport_days", "receiving_days")))
        allocations = [{"quantity": quantity, "arrival_date": arrival.isoformat(), "confirmed": offer.get("confirmed", False)}]
        if split and quantity >= dec(offer.get("order_multiple", 1)) * 2:
            multiple = dec(offer.get("order_multiple", 1))
            half = (quantity / 2 / multiple).to_integral_value() * multiple
            allocations = [{**allocations[0], "quantity": half},
                {**allocations[0], "quantity": quantity - half, "arrival_date": (arrival + timedelta(days=7)).isoformat()}]
    result = []
    for index, item in enumerate(allocations):
        arrival = day(item["arrival_date"])
        delay = 0
        for issue, target in matching_issues(data, offer, item):
            status = target.get("verification_status", issue.get("verification_status"))
            if status == "supply_impact_confirmed" and target.get("delay_days", issue.get("delay_days")) is not None:
                delay = max(delay, int(target.get("delay_days", issue.get("delay_days", 0))))
        arrival += timedelta(days=delay)
        qc_start, resource_ok = resource_slot(data, "qc", arrival, int(offer.get("qc_days", 0)), booked)
        available = qc_start + timedelta(days=int(offer.get("qc_days", 0)) + int(offer.get("qa_days", 0)))
        result.append({"id": identifier(data["id"], offer["id"], quantity, split, index, qc_start, available),
            "offer_id": offer["id"], "supplier_id": offer["supplier_id"], "quantity": dec(item["quantity"]),
            "arrival_date": arrival, "qc_start_date": qc_start, "available_date": available,
            "expiry_date": day(item["expiry_date"]) if item.get("expiry_date") else arrival + timedelta(days=int(offer.get("shelf_life_days", 90))),
            "payment_date": arrival + timedelta(days=int(offer.get("payment_days", 0))),
            "confirmed": bool(item.get("confirmed", offer.get("confirmed", False))),
            "resource_feasible": resource_ok, "lot_code": item.get("lot_code"),
            "lot_id": item.get("lot_id"), "quality_hold": bool(item.get("quality_hold")) or item.get("qa_status") in ("pending", "rejected", "hold"),
            "temperature_status": item.get("temperature_status", "passed"), "uncontracted": item.get("uncontracted", False)})
    return result


def finding(code, message, refs):
    return {"code": code, "message": message, "evidence_refs": list(dict.fromkeys(refs))}


def assess(data, material, deliveries, as_of, candidate_id, name):
    offers = {o["id"]: o for o in data.get("offers", [])}
    suppliers = {s["id"]: s for s in data.get("suppliers", [])}
    used_offers = list(dict.fromkeys(d["offer_id"] for d in deliveries))
    reasons, warnings = [], []
    for index, shipment in enumerate(deliveries):
        shipment["id"] = identifier(candidate_id, "delivery", index)
    costs = {key: ZERO for key in ("purchase", "transport", "storage", "testing", "disposal")}
    grouped = defaultdict(list)
    for shipment in deliveries:
        grouped[shipment["offer_id"]].append(shipment)
    for offer_id, shipments in grouped.items():
        offer = offers[offer_id]
        supplier = suppliers.get(offer["supplier_id"], {})
        refs = [offer_id, offer["supplier_id"]]
        qualification = [q for q in active(data.get("supplier_materials", []))
            if q.get("supplier_id") == offer["supplier_id"] and q.get("material_id") == material["id"]]
        if not supplier.get("approved", False) or not supplier.get("active", True):
            reasons.append(finding("supplier_unapproved", "업체 승인이 없습니다.", refs))
        if not offer.get("approved", False) or not offer.get("product_approved", False) or (qualification and not all(q.get("approved", False) for q in qualification)):
            reasons.append(finding("product_unapproved", "원료/제품 승인이 없습니다.", refs + [q["id"] for q in qualification]))
        if day(offer["valid_until"]) < as_of:
            reasons.append(finding("offer_expired", "견적 유효기간이 지났습니다.", refs))
        quantity = sum((dec(s["quantity"]) for s in shipments), ZERO)
        multiple = dec(offer.get("order_multiple", 1))
        if quantity <= ZERO or quantity < dec(offer.get("moq", 1)) or multiple <= ZERO or quantity % multiple != ZERO:
            reasons.append(finding("order_quantity", "MOQ/주문배수를 충족하지 않습니다.", refs))
        if quantity > dec(offer.get("available_quantity")):
            reasons.append(finding("supply_capacity", "공급 가능량을 초과합니다.", refs))
        if len(shipments) > 1 and not offer.get("allow_split", False):
            reasons.append(finding("split_not_allowed", "분할입고가 허용되지 않습니다.", refs))
        if len(shipments) > int(offer.get("max_deliveries", 2)):
            reasons.append(finding("delivery_count", "계약된 분할 회차를 초과합니다.", refs))
        for shipment in shipments:
            if shipment.get("uncontracted"):
                reasons.append(finding("uncontracted_schedule", "등록된 회차 공급량을 초과합니다.", refs))
            if day(shipment["arrival_date"]) < as_of:
                reasons.append(finding("arrival_in_past", "과거 입고 일정으로 신규 발주할 수 없습니다.", refs))
            if not shipment.get("resource_feasible", True):
                reasons.append(finding("qc_capacity", "QC 처리 가능한 일정이 없습니다.", refs + [r["id"] for r in data.get("resource_calendars", [])]))
            if shipment.get("temperature_status") != "passed" or offer.get("storage_condition") != material.get("storage_condition"):
                reasons.append(finding("temperature", "운송 온도/보관 조건을 충족하지 않습니다.", refs))
            if shipment.get("quality_hold"):
                reasons.append(finding("quality_hold", "해당 납품 Lot가 QA 보류 상태입니다.", refs))
            if day(shipment["expiry_date"]) < day(shipment["available_date"]):
                reasons.append(finding("expiry_before_release", "사용 가능 예상일 이전에 만료됩니다.", refs))
            for issue, target in matching_issues(data, offer, shipment):
                status = target.get("verification_status", issue.get("verification_status"))
                if status == "quality_impact_confirmed":
                    reasons.append(finding("quality_issue", "확인된 해당 제품/Lot 품질 영향으로 보류합니다.", [issue["id"], offer_id]))
                    shipment["quality_hold"] = True
                elif status in ("unverified", "relevance_unconfirmed"):
                    warnings.append(finding("unverified_issue", "외부 공지 관련성 미확인: 자동 감점하지 않습니다.", [issue["id"]]))
                elif status == "supply_impact_confirmed" and target.get("delay_days", issue.get("delay_days")) is None:
                    warnings.append(finding("unknown_supply_delay", "공급차질 영향은 확인됐지만 지연일은 미확인입니다.", [issue["id"]]))
            costs["purchase"] += dec(shipment["quantity"]) * dec(offer["unit_price"])
            costs["transport"] += dec(offer.get("transport_cost"))
            costs["testing"] += dec(offer.get("testing_cost"))
    projection = project(data, material, as_of, deliveries)
    optimistic = project(data, material, as_of, deliveries, optimistic=True)
    if projection["shortages"]:
        reasons.append(finding("demand_shortage", "확정 공급의 QC/QA 완료일 기준 생산 투입량이 부족합니다.",
            [s["requirement_id"] for s in projection["shortages"]] + [d["id"] for d in deliveries]))
    if projection["ending_available"] < dec(material.get("safety_stock")):
        warnings.append(finding("safety_stock", "계획 최종 투입 후 안전재고가 부족합니다.", [material["id"]]))
    horizon = as_of + timedelta(days=int(material.get("planning_horizon_days", 60)))
    for shipment in deliveries:
        offer = offers[shipment["offer_id"]]
        arrival, expiry = day(shipment["arrival_date"]), day(shipment["expiry_date"])
        uses = [u for u in optimistic["usages"] if u["stock_id"] == shipment["id"]]
        used = sum((u["quantity"] for u in uses), ZERO)
        remainder = dec(shipment["quantity"]) - used
        holding = sum((u["quantity"] * max(0, (u["date"] - arrival).days) for u in uses), ZERO)
        holding += remainder * max(0, (min(expiry, horizon) - arrival).days)
        costs["storage"] += holding * dec(offer.get("storage_cost_per_unit_day"))
        if expiry <= horizon and remainder > ZERO:
            costs["disposal"] += remainder * dec(offer.get("disposal_cost_per_unit"))
            warnings.append(finding("expected_disposal", f"기한 내 미소진 예상 폐기 {remainder} {material['base_unit']}", [shipment["id"], offer["id"]]))
    # Physical space includes held/expired stock until a recorded removal, not just usable stock.
    storage_rows = [r for r in data.get("storage_capacities", []) if r.get("storage_condition") == material.get("storage_condition")]
    capacity = sum((dec(r.get("capacity")) for r in storage_rows), ZERO)
    all_materials = {m["id"]: m for m in data.get("materials", [])}
    shared_owners = [owner for owner in all_materials.values() if owner.get("storage_condition") == material.get("storage_condition")]
    owner_projections = {owner["id"]: optimistic if owner["id"] == material["id"] else project(data, owner, as_of) for owner in shared_owners}
    incoming = [(owner, stock) for owner in shared_owners for stock in inventory(data, owner, as_of) if stock.get("po_id")]
    check_days = ({as_of} | {day(d["arrival_date"]) for d in deliveries}
        | {stock["arrival"] for _, stock in incoming}
        | {r["date"] for owner in shared_owners for r in material_requirements(data, owner, as_of)})
    max_space = ZERO
    for on in sorted(check_days):
        space = ZERO
        for lot in active(data.get("lots", [])):
            owner = all_materials.get(lot.get("material_id"), {})
            if lot.get("storage_condition", owner.get("storage_condition")) != material.get("storage_condition"):
                continue
            if lot.get("removed_date") and day(lot["removed_date"]) <= on:
                continue
            owner_usage = owner_projections.get(owner.get("id"), {}).get("usages", [])
            consumed = sum((u["quantity"] for u in owner_usage if u["stock_id"] == lot["id"] and u["date"] < on), ZERO)
            space += max(ZERO, remaining(data, lot) - consumed) * dec(owner.get("space_per_unit", 1))
        for shipment in deliveries:
            if day(shipment["arrival_date"]) <= on:
                used = sum((u["quantity"] for u in optimistic["usages"] if u["stock_id"] == shipment["id"] and u["date"] < on), ZERO)
                space += (dec(shipment["quantity"]) - used) * dec(material.get("space_per_unit", 1))
        for owner, stock in incoming:
            if stock["arrival"] <= on:
                used = sum((u["quantity"] for u in owner_projections[owner["id"]]["usages"] if u["stock_id"] == stock["id"] and u["date"] < on), ZERO)
                space += max(ZERO, stock["quantity"] - used) * dec(owner.get("space_per_unit", 1))
        max_space = max(max_space, space)
    if not storage_rows or max_space > capacity:
        reasons.append(finding("storage_capacity", f"최대 필요 공간 {max_space}, 등록 용량 {capacity}", [r["id"] for r in storage_rows] + [material["id"]]))
    # Production resource scheduling remains separate from the predicted QA release.
    plans = {p["id"]: p for p in data.get("production_plans", [])}
    booked = defaultdict(lambda: ZERO)
    for requirement in material_requirements(data, material, as_of):
        plan = plans.get(requirement.get("production_plan_id"))
        if not plan:
            continue
        start, feasible = resource_slot(data, "production", requirement["date"], int(plan.get("production_days", 1)), booked, plan.get("line_id"))
        if not feasible or (requirement["latest_use_date"] is not None and start > requirement["latest_use_date"]):
            reasons.append(finding("production_capacity", "생산 라인 대기 후 고객 납기 역산 마감일을 넘습니다.", [plan["id"], requirement["id"]]))
        if requirement["latest_use_date"] is None:
            warnings.append(finding("customer_schedule_missing", "후속 생산/납품 일정이 없어 고객 납기 충족을 확정할 수 없습니다.", [plan["id"]]))
    costs["subtotal"] = costs["purchase"] + costs["transport"]
    costs["total"] = sum((costs[key] for key in ("purchase", "transport", "storage", "testing", "disposal")), ZERO)
    relevant_budgets = [b for b in active(data.get("budgets", [])) if b.get("material_id") in (None, material["id"])]
    spending = [b for b in relevant_budgets if not b.get("payment_date")]
    budget = sum((dec(b.get("approved_amount")) - dec(b.get("committed_amount")) for b in spending), ZERO)
    needs_budget = costs["total"] > budget
    if needs_budget:
        warnings.append(finding("budget_approval", f"잔여 예산 {budget} 대비 추가 승인 {costs['total'] - budget}", [b["id"] for b in spending]))
    payments = defaultdict(lambda: ZERO)
    for shipment in deliveries:
        offer = offers[shipment["offer_id"]]
        payments[day(shipment["payment_date"]) ] += dec(shipment["quantity"]) * dec(offer["unit_price"]) + dec(offer.get("transport_cost")) + dec(offer.get("testing_cost"))
    if payments:
        payments[max(payments)] += costs["storage"] + costs["disposal"]
    cash_ok = True
    for payment_date, amount in payments.items():
        limits = [b for b in relevant_budgets if b.get("payment_date") == payment_date.isoformat()]
        if not limits or amount > sum((dec(b.get("cash_limit")) - dec(b.get("cash_committed")) for b in limits), ZERO):
            cash_ok = False
            reasons.append(finding("cash_limit", f"{payment_date} 지급액 {amount}의 현금 한도가 부족하거나 미등록입니다.", [b["id"] for b in limits]))
    confirmed = all(s["confirmed"] for s in deliveries)
    evidence_level = "confirmed" if confirmed else ("supported" if all(int(offers[o].get("performance_count", 0)) > 0 for o in used_offers) else "unconfirmed")
    if any(w["code"] == "unknown_supply_delay" for w in warnings):
        evidence_level = "unconfirmed"
    production_valid = not any(r["code"] in ("demand_shortage", "production_capacity") for r in reasons)
    customer_known = not any(w["code"] == "customer_schedule_missing" for w in warnings)
    refs = list(dict.fromkeys([material["id"]] + used_offers + [r["id"] for r in material_requirements(data, material, as_of)]))
    expected_disposal = sum((s["quantity"] for s in optimistic["stocks"] if s["candidate"] and s["expiry"] <= horizon), ZERO)
    retained_existing = sum((s["quantity"] for s in optimistic["stocks"] if not s["candidate"] and s["expiry"] > horizon), ZERO)
    last_use = max((r["date"] for r in material_requirements(data, material, as_of)), default=as_of)
    if expected_disposal > ZERO and retained_existing > ZERO:
        warnings.append(finding("residual_composition",
            f"FEFO 배정: 신규 입고 중 폐기 예상 {expected_disposal}, 계획 범위 이후에도 유효한 기존 재고 {retained_existing}. 잔량 전체를 폐기량으로 계산하지 않습니다.",
            [s["id"] for s in optimistic["stocks"] if s["quantity"] > ZERO]))
    return {"id": candidate_id, "material_id": material["id"], "name": name,
        "offer_id": used_offers[0] if len(used_offers) == 1 else None,
        "supplier_id": offers[used_offers[0]]["supplier_id"] if len(used_offers) == 1 else None,
        "offer_ids": used_offers, "supplier_ids": list(dict.fromkeys(offers[o]["supplier_id"] for o in used_offers)),
        "quantity": sum((dec(d["quantity"]) for d in deliveries), ZERO), "deliveries": deliveries,
        "validation": {"hard_constraints_passed": not reasons, "target_delivery_met": production_valid and customer_known,
            "requires_budget_approval": needs_budget, "cash_feasible": cash_ok, "supply_evidence_level": evidence_level,
            "reasons": reasons, "warnings": warnings}, "costs": costs,
        "budget_available": budget, "additional_budget_required": max(ZERO, costs["total"] - budget),
        "payment_obligations": [{"payment_date": payment_date, "amount": amount} for payment_date, amount in sorted(payments.items())],
        "remaining_quantity": optimistic["ending_available"], "expected_disposal_quantity": expected_disposal,
        "residual_lots": [{"stock_id": s["id"], "quantity": s["quantity"], "expiry_date": s["expiry"], "is_new_purchase": s["candidate"]} for s in optimistic["stocks"] if s["quantity"] > ZERO and s["expiry"] >= last_use],
        "first_shortage_date": projection["first_shortage"], "maximum_storage": max_space,
        "timeline": projection["timeline"], "optimistic_timeline": optimistic["timeline"], "evidence_refs": refs}


def generate_candidates(data, material, quantity, as_of):
    offers = [o for o in active(data.get("offers", [])) if o.get("material_id") == material["id"]]
    candidates = []
    for offer in offers:
        amount = rounding(quantity, offer)
        explicit_split = bool(offer.get("deliveries")) and len(offer["deliveries"]) > 1
        variants = [explicit_split]
        if offer.get("allow_split") and not explicit_split:
            variants.append(True)
        for split in variants:
            deliveries = build_deliveries(data, offer, amount, as_of, split, defaultdict(lambda: ZERO))
            cid = identifier(data["id"], material["id"], offer["id"], amount, split)
            label = f"{offer.get('name', offer.get('code', '견적'))} · {len(deliveries)}회 입고"
            candidates.append(assess(data, material, deliveries, as_of, cid, label))
    # Enumerate every order-multiple allocation, subject to each supplier's MOQ.
    for left, right in combinations(offers, 2):
        if left["supplier_id"] == right["supplier_id"]:
            continue
        step = dec(left.get("order_multiple", 1))
        minimum = rounding(dec(left.get("moq", 1)), left)
        maximum = min(dec(left.get("available_quantity")), rounding(quantity, left))
        amount = minimum
        while amount <= maximum:
            other = rounding(max(ZERO, quantity - amount), right)
            if amount + other >= quantity and other <= dec(right.get("available_quantity")):
                booked = defaultdict(lambda: ZERO)
                shipments = build_deliveries(data, left, amount, as_of, len(left.get("deliveries", [])) > 1, booked)
                shipments += build_deliveries(data, right, other, as_of, len(right.get("deliveries", [])) > 1, booked)
                cid = identifier(data["id"], material["id"], left["id"], amount, right["id"], other)
                candidates.append(assess(data, material, shipments, as_of, cid,
                    f"{left.get('code')} + {right.get('code')} 분할발주"))
            amount += step
    candidates.sort(key=lambda c: (not c["validation"]["hard_constraints_passed"],
        not c["validation"]["target_delivery_met"], {"confirmed": 0, "supported": 1, "unconfirmed": 2}[c["validation"]["supply_evidence_level"]],
        c["costs"]["total"], c["id"]))
    return candidates[:200]


def evaluate(data, as_of=None):
    as_of = day(as_of or data.get("as_of") or date.today())
    result = {"scenario_id": data["id"], "revision": data.get("revision", 1), "as_of": as_of,
              "materials": [], "alerts": [], "candidates": [], "timelines": {}, "evidence": []}
    for material in active(data.get("materials", [])):
        projection = project(data, material, as_of)
        reqs = material_requirements(data, material, as_of)
        stock = inventory(data, material, as_of)
        first_use = reqs[0]["date"] if reqs else as_of
        usable = sum((max(ZERO, s["quantity"] - sum((dec(r["quantity"]) for r in s["reservations"]), ZERO))
                      for s in stock if s["available"] <= as_of and s["expiry"] >= first_use), ZERO)
        shortage = sum((s["quantity"] for s in projection["shortages"]), ZERO)
        required = sum((r["quantity"] for r in reqs), ZERO)
        new_quantity = shortage + max(ZERO, dec(material.get("safety_stock")) - projection["ending_available"])
        offers = [o for o in active(data.get("offers", [])) if o.get("material_id") == material["id"] and day(o["valid_until"]) >= as_of]
        leads = [sum(int(o.get(k, 0)) for k in ("preparation_days", "transport_days", "receiving_days", "qc_days", "qa_days")) for o in offers]
        lead = min(leads) if leads else None
        rate = dec(material.get("daily_usage_fallback"))
        first_shortage = projection["first_shortage"]
        review = int(material.get("review_days", 0))
        deadline = first_shortage - timedelta(days=lead) if first_shortage and lead is not None else None
        safety_deadline = projection["first_safety"] - timedelta(days=lead) if projection["first_safety"] and lead is not None else None
        if rate > ZERO and not any(r.get("material_id") == material["id"] for r in active(data.get("requirements", []))) and lead is not None:
            # 35 at daily usage 1, lead 30, safety 5 -> warning; 34 -> urgent.
            threshold = rate * (lead + review) + dec(material.get("safety_stock"))
            status = "warning" if usable == threshold else "urgent" if usable < threshold else "resolved"
            deadline = as_of + timedelta(days=int((usable - dec(material.get("safety_stock"))) / rate) - lead)
        elif not offers:
            status = "data_missing"
        elif any(s["date"] <= as_of for s in projection["shortages"]) or (deadline and deadline < as_of):
            status = "urgent"
        elif new_quantity > ZERO and ((deadline and deadline <= as_of + timedelta(days=review)) or (safety_deadline and safety_deadline <= as_of + timedelta(days=review))):
            status = "warning"
        else:
            status = "resolved"
        evidence_id = identifier(data["id"], data.get("revision", 1), material["id"], "projection", as_of)
        refs = [material["id"]] + [r["id"] for r in reqs] + [l["id"] for l in data.get("lots", []) if l.get("material_id") == material["id"]]
        summary = {"id": evidence_id, "material_id": material["id"], "code": material["code"], "name": material["name"],
            "base_unit": material["base_unit"], "book_quantity": sum((remaining(data, l) for l in data.get("lots", []) if l.get("material_id") == material["id"]), ZERO),
            "free_available_quantity": usable, "usable_for_production": usable,
            "currently_quality_released_quantity": sum((s["quantity"] for s in stock if s["available"] <= as_of), ZERO),
            "required_quantity": required, "new_order_quantity": new_quantity, "safety_stock": dec(material.get("safety_stock")),
            "alert_status": status, "first_shortage_date": first_shortage, "first_safety_breach_date": projection["first_safety"],
            "expected_stockout_date": first_shortage, "latest_order_date": deadline, "lead_time_days": lead,
            "lead_time_breakdown": [{"offer_id": o["id"], **{k: int(o.get(k, 0)) for k in ("preparation_days", "transport_days", "receiving_days", "qc_days", "qa_days")}} for o in offers],
            "affected_production_ids": list(dict.fromkeys(s["production_plan_id"] for s in projection["shortages"])),
            "existing_receipts": [s for s in stock if s.get("po_id")], "evidence_refs": [evidence_id] + refs}
        result["materials"].append(summary)
        result["timelines"][material["id"]] = projection["timeline"]
        result["evidence"].append({"id": evidence_id, "kind": "material_projection", "label": material["name"] + " 날짜별 가용량 계산", "record_ids": refs,
            "details": {"timeline": projection["timeline"], "shortages": projection["shortages"]}})
        if status != "resolved":
            result["alerts"].append({"id": identifier(data["id"], material["id"], "procurement"),
                "material_id": material["id"], "status": status, "kind": "procurement", "message": "유효 견적/조달 근거 입력 필요" if status == "data_missing" else "QC/QA 완료일 기준 발주 검토 필요",
                "first_shortage_date": first_shortage, "latest_order_date": deadline, "evidence_refs": [evidence_id]})
        if new_quantity > ZERO and required > ZERO:
            candidates = generate_candidates(data, material, new_quantity, as_of)
            for rank, candidate in enumerate(candidates, len(result["candidates"]) + 1):
                candidate["rank"] = rank
                result["evidence"].append({"id": candidate["id"], "kind": "candidate_validation", "label": candidate["name"],
                    "record_ids": candidate["evidence_refs"], "details": {"costs": candidate["costs"], "validation": candidate["validation"]}})
                for shipment in candidate["deliveries"]:
                    result["evidence"].append({"id": shipment["id"], "kind": "delivery_forecast", "label": candidate["name"] + " 입고/승인 예측", "record_ids": [shipment["offer_id"]], "details": shipment})
            result["candidates"].extend(candidates)
    return json_safe(result)


def evaluate_material(data, material_id, as_of=None):
    result = evaluate(data, as_of)
    return {"material": next(m for m in result["materials"] if m["material_id"] == str(material_id)),
            "candidates": [c for c in result["candidates"] if c["material_id"] == str(material_id)],
            "timeline": result["timelines"][str(material_id)]}


def validate_strategy(data, strategy, as_of=None):
    """Resolve registered candidates rather than trusting LLM-supplied price/quality fields.

    New strategies may change allowed quantity allocations, but not invent dates,
    supplier identities, lot quality, or supply confirmations.
    """
    as_of = day(as_of or data.get("as_of") or date.today())
    current = evaluate(data, as_of)
    candidate_id = strategy.get("candidate_id", strategy.get("id"))
    known = next((c for c in current["candidates"] if c["id"] == candidate_id), None)
    if known and (not strategy.get("deliveries") or strategy["deliveries"] == known["deliveries"]):
        return known
    material = next((m for m in data.get("materials", []) if m["id"] == strategy.get("material_id")), None)
    if material is None:
        raise ValueError("Unknown strategy material")
    offers = {o["id"]: o for o in data.get("offers", []) if o.get("material_id") == material["id"]}
    requested = strategy.get("deliveries", [])
    if not requested:
        raise ValueError("Strategy must contain registered deliveries")
    grouped = defaultdict(list)
    for shipment in requested:
        if shipment.get("offer_id") not in offers:
            raise ValueError("Unknown strategy offer")
        grouped[shipment["offer_id"]].append(shipment)
    canonical, booked = [], defaultdict(lambda: ZERO)
    for offer_id, rows in grouped.items():
        amount = sum((dec(row["quantity"]) for row in rows), ZERO)
        shipments = build_deliveries(data, offers[offer_id], amount, as_of, len(rows) > 1, booked)
        if len(shipments) != len(rows):
            raise ValueError("Strategy delivery count differs from registered contract")
        for row, expected in zip(rows, shipments):
            for field in ("arrival_date", "expiry_date", "supplier_id"):
                if field in row and str(row[field]) != str(expected[field]):
                    raise ValueError(f"Strategy cannot change registered {field}")
            if dec(row["quantity"]) != dec(expected["quantity"]):
                raise ValueError("Strategy allocation differs from registered contract")
        canonical.extend(shipments)
    cid = identifier(data["id"], material["id"], "strategy", *[f"{s['offer_id']}:{s['quantity']}" for s in canonical])
    result = assess(data, material, canonical, as_of, cid, strategy.get("name", "검증 전략"))
    result["rank"] = None
    return json_safe(result)

from copy import deepcopy
from decimal import Decimal

import pytest

from app.scenarios import list_scenarios, load_scenario
from app.services.planning import evaluate, validate_strategy


def il7_result(data=None):
    data = data or load_scenario("scenario_1")
    result = evaluate(data)
    material = next(m for m in result["materials"] if m["code"] == "MAT-IL7")
    return data, result, material


def supplier_candidate(data, result, code):
    offer = next(o for o in data["offers"] if o["code"] == code)
    return next(c for c in result["candidates"] if c["offer_ids"] == [offer["id"]])


def codes(candidate):
    return {r["code"] for r in candidate["validation"]["reasons"]}


def test_scenario_one_uses_two_not_six_and_orders_twelve():
    _, _, material = il7_result()
    assert material["book_quantity"] == "6"
    assert material["usable_for_production"] == "2"
    assert material["new_order_quantity"] == "12"
    assert material["first_shortage_date"] == "2026-11-04"


def test_bulk_moq_residual_expiry_and_budget_are_distinct_from_hard_failure():
    data, result, _ = il7_result()
    candidate = supplier_candidate(data, result, "OFFER-A-IL7")
    assert candidate["quantity"] == "20"
    assert candidate["remaining_quantity"] == "10"
    assert candidate["expected_disposal_quantity"] == "8"
    assert candidate["costs"]["subtotal"] == "16100000"
    assert candidate["costs"]["disposal"] == "80000"
    assert {(r["quantity"], r["expiry_date"]) for r in candidate["residual_lots"]} == {("8", "2026-11-30"), ("2", "2027-03-31")}
    assert candidate["validation"]["requires_budget_approval"] is True
    assert candidate["validation"]["hard_constraints_passed"] is True


def test_three_confirmed_split_shipments_preserve_two_after_every_production():
    data, result, _ = il7_result()
    candidate = supplier_candidate(data, result, "OFFER-B-IL7")
    assert [d["available_date"] for d in candidate["deliveries"]] == ["2026-11-02", "2026-11-09", "2026-11-16"]
    assert [row["available_quantity"] for row in candidate["timeline"] if row["event"] == "production_use"] == ["2", "2", "2"]
    assert candidate["costs"]["subtotal"] == "12300000"
    assert candidate["costs"]["testing"] == "300000"
    assert Decimal(candidate["costs"]["total"]) == sum(Decimal(candidate["costs"][key]) for key in ("purchase", "transport", "storage", "testing", "disposal"))
    assert Decimal(candidate["costs"]["total"]) < Decimal("13000000")
    assert sum(Decimal(payment["amount"]) for payment in candidate["payment_obligations"]) == Decimal(candidate["costs"]["total"])
    assert [payment["payment_date"] for payment in candidate["payment_obligations"]] == ["2026-10-30", "2026-11-06", "2026-11-13"]
    assert candidate["validation"]["hard_constraints_passed"] is True
    assert candidate["validation"]["requires_budget_approval"] is False


def test_unconfirmed_cheap_offer_does_not_cover_confirmed_demand():
    data, result, _ = il7_result()
    candidate = supplier_candidate(data, result, "OFFER-C-IL7")
    assert candidate["validation"]["supply_evidence_level"] == "unconfirmed"
    assert "demand_shortage" in codes(candidate)
    assert candidate["first_shortage_date"] == "2026-11-04"
    assert [r["shortage_quantity"] for r in candidate["optimistic_timeline"] if r["event"] == "production_use"] == ["0", "0", "0"]
    assert candidate["rank"] > supplier_candidate(data, result, "OFFER-B-IL7")["rank"]


def test_qc_bottleneck_moves_release_to_twelfth_and_misses_second_production():
    data, result, _ = il7_result(load_scenario("scenario_1_qc_bottleneck"))
    candidate = supplier_candidate(data, result, "OFFER-B-IL7")
    assert candidate["deliveries"][1]["available_date"] == "2026-11-12"
    assert candidate["first_shortage_date"] == "2026-11-11"
    assert "demand_shortage" in codes(candidate)
    second = next(r for r in candidate["timeline"] if r["event"] == "production_use" and r["date"] == "2026-11-11")
    assert second["shortage_quantity"] == "2"


def test_registry_loads_independent_data_and_scopes_all_foreign_keys():
    original = load_scenario("scenario_1")
    variant = load_scenario("scenario_1_qc_bottleneck")
    assert original["materials"][0]["id"] != variant["materials"][0]["id"]
    assert variant["requirements"][0]["material_id"] in {m["id"] for m in variant["materials"]}
    original["lots"][0]["quantity"] = "999"
    assert load_scenario("scenario_1")["lots"][0]["quantity"] == "2"
    baseline = load_scenario("baseline")
    assert len(baseline["materials"]) == 3 and len(baseline["suppliers"]) == 4
    assert not {m["id"] for m in baseline["materials"]} & {m["id"] for m in original["materials"]}
    assert {s["id"] for s in list_scenarios()} >= {"baseline", "scenario_1", "scenario_1_qc_bottleneck"}


def test_quality_hold_and_unverified_news_have_different_effects():
    data = load_scenario("scenario_1")
    offer = next(o for o in data["offers"] if o["code"] == "OFFER-B-IL7")
    data["issues"] = [{"id": "quality-evidence", "material_id": offer["material_id"], "supplier_id": offer["supplier_id"],
        "lot_code": offer["deliveries"][1]["lot_code"], "verification_status": "relevance_unconfirmed"}]
    candidate = supplier_candidate(data, evaluate(data), "OFFER-B-IL7")
    assert candidate["validation"]["hard_constraints_passed"] is True
    data["issues"][0]["verification_status"] = "quality_impact_confirmed"
    candidate = supplier_candidate(data, evaluate(data), "OFFER-B-IL7")
    assert "quality_issue" in codes(candidate)
    assert candidate["validation"]["hard_constraints_passed"] is False


def test_cash_shortfall_is_not_solved_by_budget_approval():
    data = load_scenario("scenario_1")
    for budget in data["budgets"]:
        if budget.get("payment_date") == "2026-11-06":
            budget["cash_limit"] = "1"
    candidate = supplier_candidate(data, evaluate(data), "OFFER-B-IL7")
    assert "cash_limit" in codes(candidate)
    assert candidate["validation"]["cash_feasible"] is False
    assert candidate["validation"]["requires_budget_approval"] is False


def test_expired_and_held_stock_still_occupy_physical_storage():
    data = load_scenario("scenario_1")
    data["storage_capacities"][0]["capacity"] = "0.29"
    candidate = supplier_candidate(data, evaluate(data), "OFFER-B-IL7")
    # 26 existing vials, including held and soon-expired stock, plus first delivery 4.
    assert candidate["maximum_storage"] == "0.30"
    assert "storage_capacity" in codes(candidate)


def test_reservations_are_used_once_for_the_owning_production_and_not_shared():
    data = load_scenario("scenario_1")
    good_lot = data["lots"][0]
    good_lot["quantity"] = "4"
    data["reservations"] = [{"id": "reservation", "lot_id": good_lot["id"], "quantity": "4",
        "production_plan_id": data["production_plans"][1]["id"]}]
    _, result, material = il7_result(data)
    timeline = result["timelines"][material["material_id"]]
    uses = [r for r in timeline if r["event"] == "production_use"]
    assert [r["shortage_quantity"] for r in uses] == ["4", "0", "4"]
    assert material["new_order_quantity"] == "10"
    data["reservations"][0]["quantity"] = "5"
    with pytest.raises(ValueError, match="Reservation exceeds"):
        evaluate(data)


def test_consumption_summary_and_ledger_do_not_double_subtract():
    data = load_scenario("scenario_1")
    lot = data["lots"][0]
    lot.update(quantity="4", consumed_quantity="2")
    data["consumptions"] = [{"id": "consumption", "lot_id": lot["id"], "quantity": "2"}]
    assert il7_result(data)[2]["usable_for_production"] == "2"


def test_late_existing_po_release_cannot_hide_intermediate_shortage():
    data = load_scenario("scenario_1")
    material_id = data["materials"][0]["id"]
    data["purchase_orders"] = [{"id": "po", "material_id": material_id, "status": "approved", "deliveries": [
        {"id": "delivery", "quantity": "12", "arrival_date": "2026-10-30", "available_date": "2026-11-05",
         "expiry_date": "2027-03-31", "confirmed": True}]}]
    assert il7_result(data)[2]["first_shortage_date"] == "2026-11-04"


def test_expiry_day_is_usable_but_next_day_is_not():
    data = load_scenario("scenario_1")
    data["lots"][0]["expiry_date"] = "2026-11-04"
    assert il7_result(data)[2]["usable_for_production"] == "2"
    data["lots"][0]["expiry_date"] = "2026-11-03"
    assert il7_result(data)[2]["usable_for_production"] == "0"


def test_strategy_validation_rejects_invented_supplier_dates_and_never_releases_lots():
    data, result, _ = il7_result()
    before = deepcopy(data["lots"])
    candidate = supplier_candidate(data, result, "OFFER-B-IL7")
    assert validate_strategy(data, candidate)["costs"] == candidate["costs"]
    changed = deepcopy(candidate)
    changed["deliveries"][0]["arrival_date"] = "2026-10-25"
    with pytest.raises(ValueError, match="cannot change"):
        validate_strategy(data, changed)
    assert data["lots"] == before


def test_production_line_capacity_recalculates_customer_deadline():
    data = load_scenario("scenario_1")
    data["resource_calendars"].append({"id": "line-block", "resource_type": "production", "line_id": "CELL-PILOT-1",
        "date": "2026-11-04", "capacity": "0"})
    candidate = supplier_candidate(data, evaluate(data), "OFFER-B-IL7")
    assert "production_capacity" in codes(candidate)
    assert candidate["validation"]["target_delivery_met"] is False


@pytest.mark.parametrize("stock,status", [("40", "resolved"), ("35", "warning"), ("34", "urgent")])
def test_daily_usage_reorder_boundary(stock, status):
    data = load_scenario("scenario_1")
    material = data["materials"][0]
    material.update(safety_stock="5", review_days=0, daily_usage_fallback="1", planning_horizon_days=60)
    data["materials"] = [material]
    data["requirements"] = []
    data["lots"] = [{**data["lots"][0], "quantity": stock}]
    offer = data["offers"][0]
    offer.update(preparation_days=24, transport_days=2, receiving_days=1, qc_days=2, qa_days=1)
    data["offers"] = [offer]
    assert evaluate(data)["materials"][0]["alert_status"] == status


def test_lot_scoped_quality_issue_does_not_block_unrelated_deliveries():
    data = load_scenario("scenario_1")
    offer = next(o for o in data["offers"] if o["code"] == "OFFER-B-IL7")
    data["issues"] = [{"id": "unrelated-lot", "supplier_id": offer["supplier_id"],
        "material_id": offer["material_id"], "lot_id": data["lots"][1]["id"],
        "verification_status": "quality_impact_confirmed"}]
    candidate = supplier_candidate(data, evaluate(data), "OFFER-B-IL7")
    assert candidate["validation"]["hard_constraints_passed"] is True


def test_quality_confirmation_and_clearance_change_actual_lot_availability():
    data = load_scenario("scenario_1")
    lot = data["lots"][0]
    data["issues"] = [{"id": "lot-quality", "links": [
        {"id": "confirmation", "lot_id": lot["id"], "verification_status": "quality_impact_confirmed", "confirmed_at": "2026-10-24T01:00:00Z"}]}]
    assert il7_result(data)[2]["usable_for_production"] == "0"
    data["issues"][0]["links"].insert(0, {"id": "clearance", "lot_id": lot["id"], "verification_status": "cleared", "confirmed_at": "2026-10-24T02:00:00Z"})
    assert il7_result(data)[2]["usable_for_production"] == "2"


def test_unapproved_cheap_product_is_a_quality_failure_not_supply_uncertainty():
    data = load_scenario("scenario_1")
    offer = next(o for o in data["offers"] if o["code"] == "OFFER-C-IL7")
    offer["product_approved"] = False
    candidate = supplier_candidate(data, evaluate(data), "OFFER-C-IL7")
    assert "product_unapproved" in codes(candidate)
    assert candidate["validation"]["supply_evidence_level"] == "unconfirmed"


def test_consumption_reduces_aggregate_reservation_once_per_production():
    data = load_scenario("scenario_1")
    lot = data["lots"][0]
    lot.update(quantity="6", consumed_quantity="2")
    production_id = data["production_plans"][0]["id"]
    data["reservations"] = [
        {"id": "reserved-a", "lot_id": lot["id"], "production_plan_id": production_id, "quantity": "3"},
        {"id": "reserved-b", "lot_id": lot["id"], "production_plan_id": production_id, "quantity": "3"}]
    data["consumptions"] = [{"id": "actual-use", "lot_id": lot["id"],
        "production_plan_id": production_id, "quantity": "2"}]
    _, result, material = il7_result(data)
    assert material["usable_for_production"] == "0"
    uses = [r for r in result["timelines"][material["material_id"]] if r["event"] == "production_use"]
    assert [r["shortage_quantity"] for r in uses] == ["0", "4", "4"]

from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from sqlalchemy import select, func
from app.db import SessionLocal
from app.models import DiscussionRun, Recommendation, ExternalSource, ERPRecord, Approval
from app.services.erp import snapshot
from app.services.planning import evaluate
from app.services.external_sources import CollectionError

API = "/api/v1"


def recommendation(client, expensive=False):
    client.get(f"{API}/scenarios/scenario_1")
    with SessionLocal() as db:
        for source in db.scalars(select(ExternalSource)):
            source.data = {**source.data, "enabled": False}
        if expensive:
            for budget in db.scalars(select(ERPRecord).where(ERPRecord.scenario_id == "scenario_1", ERPRecord.collection == "budgets")):
                if not budget.data.get("payment_date"):
                    budget.data = {**budget.data, "approved_amount": "0"}
            db.flush()
        state = snapshot(db, "scenario_1")
        result = evaluate(state, as_of="2026-10-24")
        candidates = [c for c in result["candidates"] if c["validation"]["hard_constraints_passed"] and c["validation"]["target_delivery_met"] and c["validation"].get("cash_feasible", True)]
        if expensive:
            candidate = next(c for c in candidates if c["validation"]["requires_budget_approval"])
        else:
            candidate = next(c for c in candidates if not c["validation"]["requires_budget_approval"] and c["validation"]["supply_evidence_level"] == "confirmed")
        run = DiscussionRun(scenario_id="scenario_1", snapshot_revision=state["revision"], snapshot=state, calculation=result, status="awaiting_review", progress={})
        db.add(run)
        db.flush()
        rec = Recommendation(run_id=run.id, scenario_id="scenario_1", snapshot_revision=state["revision"], candidate_id=candidate["id"], data={"candidate": candidate, "rationale_items": [], "remaining_risks": []})
        db.add(rec)
        db.commit()
        return rec.id, state


def test_approval_idempotent_and_never_grants_quality_use(client):
    rec_id, state = recommendation(client)
    original_lots = state["lots"]
    body = {"expected_revision": state["revision"], "acknowledge_unverified": True}
    url = f"{API}/recommendations/{rec_id}/approve"
    first = client.post(url, json=body, headers={"Idempotency-Key": "once"})
    assert first.status_code == 200, first.text
    second = client.post(url, json=body, headers={"Idempotency-Key": "once"})
    assert second.status_code == 200
    assert second.json()["id"] == first.json()["id"]
    after = client.get(f"{API}/scenarios/scenario_1").json()
    assert after["lots"] == original_lots
    assert after["purchase_orders"][0]["quality_use_approval"] == "not_granted"
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Approval)) == 1
        committed = sum(Decimal(b["committed_amount"]) for b in after["budgets"])
        assert committed == Decimal(first.json()["purchase_order"]["total_cost"])
        assert sum(Decimal(b.get("cash_committed", "0")) for b in after["budgets"]) == committed


def test_old_snapshot_cannot_create_order(client):
    rec_id, state = recommendation(client)
    material = state["materials"][0]
    changed = client.patch(f"{API}/scenarios/scenario_1/materials/{material['id']}", json={"revision": material["revision"], "safety_stock": "7"})
    assert changed.status_code == 200
    response = client.post(f"{API}/recommendations/{rec_id}/approve", json={"expected_revision": state["revision"], "acknowledge_unverified": True}, headers={"Idempotency-Key": "stale"})
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "stale"
    assert client.get(f"{API}/scenarios/scenario_1/purchase-orders").json() == []


def test_external_failure_leaves_no_order_or_budget_commit(client, monkeypatch):
    rec_id, state = recommendation(client)
    async def failed():
        raise CollectionError("fixture source unavailable")
    monkeypatch.setattr("app.services.approvals.refresh_enabled", failed)
    response = client.post(f"{API}/recommendations/{rec_id}/approve", json={"expected_revision": state["revision"], "acknowledge_unverified": True}, headers={"Idempotency-Key": "failure"})
    assert response.status_code == 503
    after = client.get(f"{API}/scenarios/scenario_1").json()
    assert after["purchase_orders"] == []
    assert after["budgets"] == state["budgets"]


def test_parallel_approval_creates_only_one_order(client):
    rec_id, state = recommendation(client)
    body = {"expected_revision": state["revision"], "acknowledge_unverified": True}
    def submit(key):
        return client.post(f"{API}/recommendations/{rec_id}/approve", json=body, headers={"Idempotency-Key": key})
    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(executor.map(submit, ["parallel-a", "parallel-b"]))
    assert sorted(r.status_code for r in responses) == [200, 409]
    assert len(client.get(f"{API}/scenarios/scenario_1/purchase-orders").json()) == 1


def test_operator_cannot_approve_even_valid_recommendation(client):
    rec_id, state = recommendation(client)
    client.post(f"{API}/auth/logout")
    client.post(f"{API}/auth/login", json={"email": "operator@example.test", "password": "test-only-operator-password"})
    response = client.post(f"{API}/recommendations/{rec_id}/approve", json={"expected_revision": state["revision"], "acknowledge_unverified": True}, headers={"Idempotency-Key": "operator"})
    assert response.status_code == 403


def test_budget_overage_requires_explicit_amount_and_reason(client):
    rec_id, state = recommendation(client, expensive=True)
    body = {"expected_revision": state["revision"], "acknowledge_unverified": True}
    url = f"{API}/recommendations/{rec_id}/approve"
    response = client.post(url, json=body, headers={"Idempotency-Key": "budget"})
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "budget_approval_required"
    with SessionLocal() as db:
        amount = db.get(Recommendation, rec_id).data["candidate"]["costs"]["total"]
    response = client.post(url, json={**body, "budget_approval_reason": "명시적 추가 승인", "budget_approval_amount": amount}, headers={"Idempotency-Key": "budget"})
    assert response.status_code == 200, response.text
    after = client.get(f"{API}/scenarios/scenario_1").json()
    spending = [b for b in after["budgets"] if not b.get("payment_date")]
    assert sum(Decimal(b["approved_amount"]) for b in spending) == Decimal(amount)
    assert sum(Decimal(b["committed_amount"]) for b in spending) == Decimal(amount)

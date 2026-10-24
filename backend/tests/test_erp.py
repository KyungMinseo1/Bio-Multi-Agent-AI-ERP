from sqlalchemy import select
from app.db import SessionLocal
from app.models import ERPRecord, AuditEvent
from app.services.erp import ensure_scenario

API = "/api/v1/scenarios"


def test_revision_conflict_and_non_destructive_seed(client):
    original = client.get(f"{API}/scenario_1").json()
    material = original["materials"][0]
    response = client.patch(f"{API}/scenario_1/materials/{material['id']}", json={"revision": material["revision"], "name": "사용자 변경 원료"})
    assert response.status_code == 200
    stale = client.patch(f"{API}/scenario_1/materials/{material['id']}", json={"revision": material["revision"], "name": "덮어쓰기"})
    assert stale.status_code == 409
    with SessionLocal() as db:
        ensure_scenario(db, "scenario_1")
        db.commit()
    state = client.get(f"{API}/scenario_1").json()
    assert next(m for m in state["materials"] if m["id"] == material["id"])["name"] == "사용자 변경 원료"
    assert state["revision"] == original["revision"] + 1
    with SessionLocal() as db:
        events = db.scalars(select(AuditEvent).where(AuditEvent.action == "materials.update")).all()
        assert events[0].before["name"] == material["name"]
        assert events[0].after["name"] == "사용자 변경 원료"


def test_scenario_isolation_and_unit_lock(client):
    first = client.get(f"{API}/scenario_1").json()
    other = client.get(f"{API}/scenario_1_qc_bottleneck").json()
    material = first["materials"][0]
    response = client.patch(f"{API}/scenario_1/materials/{material['id']}", json={"revision": material["revision"], "base_unit": "kg"})
    assert response.status_code == 409
    assert client.get(f"{API}/scenario_1_qc_bottleneck").json() == other


def test_overreservation_duplicate_consumption_and_negative_quantity(client):
    state = client.get(f"{API}/scenario_1").json()
    lot = state["lots"][0]
    plan = state["production_plans"][0]
    reservation = {"lot_id": lot["id"], "production_plan_id": plan["id"], "quantity": "9999"}
    assert client.post(f"{API}/scenario_1/reservations", json=reservation).status_code == 409
    consumption = {"lot_id": lot["id"], "production_plan_id": plan["id"], "quantity": "1", "idempotency_key": "consumed-once"}
    assert client.post(f"{API}/scenario_1/consumptions", json=consumption).status_code == 201
    assert client.post(f"{API}/scenario_1/consumptions", json=consumption).status_code == 409
    assert client.post(f"{API}/scenario_1/consumptions", json={**consumption, "quantity": "-1", "idempotency_key": "negative"}).status_code == 422
    assert client.post(f"{API}/scenario_1/consumptions", json={**consumption, "lot_id": "missing", "idempotency_key": "missing"}).status_code == 422


def test_mutations_need_session_and_budget_approver(client):
    client.get(f"{API}/scenario_1")
    client.post("/api/v1/auth/logout")
    assert client.post(f"{API}/scenario_1/materials", json={"name": "거부", "base_unit": "vial"}).status_code == 401
    client.post("/api/v1/auth/login", json={"email": "operator@example.test", "password": "test-only-operator-password"})
    assert client.post(f"{API}/scenario_1/budgets", json={"approved_amount": "100"}).status_code == 403
    assert client.post(f"{API}/scenario_1/materials", json={"name": "허용", "base_unit": "vial"}).status_code == 201


def test_missing_llm_configuration_is_explicit_no_fake_run(client):
    state = client.get(f"{API}/scenario_1").json()
    response = client.post(f"{API}/scenario_1/discussions", json={"expected_revision": state["revision"]})
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "configuration_error"
    assert client.get(f"{API}/scenario_1/discussions").json() == []

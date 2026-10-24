from app.db import SessionLocal
from app.models import DiscussionRun
from app.services.erp import snapshot
from app.services.discussions import artifact, check_turn, known_identifiers


def turn():
    return {"role": "admin", "strategy_id": "strategy", "version": 1, "proposal": {"candidate_ids": ["candidate"], "summary": "IL-7 투입 일정 검토"}, "impacts": [], "reasons": [], "evidence_refs": ["lot"], "change_requests": [], "position": "accept", "recommendations": [{"candidate_id": "candidate", "claim": "PROD-01 계획에 맞는 분할 공급", "evidence_refs": ["lot"], "message_refs": ["message"], "change_refs": ["strategy"], "remaining_risks": []}]}


def test_numeric_contradictions_and_nonexistent_message_references_rejected():
    candidates = {"candidate": {"quantity": "12", "costs": {"total": "12300000"}, "validation": {"hard_constraints_passed": True, "target_delivery_met": True, "cash_feasible": True}}}
    value = turn()
    labels = known_identifiers({"materials": [{"name": "재조합 인간 IL-7"}], "production_plans": [{"code": "PROD-01"}]})
    assert check_turn(value, "admin", "strategy", 1, {"lot"}, candidates, {"message"}, {"strategy"}, labels) == []
    value["impacts"] = [{"candidate_id": "candidate", "metric": "total", "value": "12", "evidence_ref": "lot"}]
    assert any("metric" in error for error in check_turn(value, "admin", "strategy", 1, {"lot"}, candidates, {"message"}, {"strategy"}, labels))
    value["impacts"] = []
    value["recommendations"][0]["message_refs"] = ["invented-message"]
    assert any("message IDs" in error for error in check_turn(value, "admin", "strategy", 1, {"lot"}, candidates, {"message"}, {"strategy"}, labels))


def test_sse_reconnect_and_immutable_snapshot_after_erp_edit(client):
    state = client.get("/api/v1/scenarios/scenario_1").json()
    with SessionLocal() as db:
        run = DiscussionRun(scenario_id="scenario_1", snapshot_revision=state["revision"], snapshot=state, calculation={}, status="failed", progress={})
        db.add(run)
        db.flush()
        artifact(db, run.id, "status", {"status": "queued"})
        artifact(db, run.id, "error", {"code": "fixture_failure"})
        db.commit()
        run_id = run.id
    material = state["materials"][0]
    client.patch(f"/api/v1/scenarios/scenario_1/materials/{material['id']}", json={"revision": material["revision"], "name": "변경된 현재 원료"})
    history = client.get(f"/api/v1/discussions/{run_id}").json()
    assert history["snapshot"]["materials"][0]["name"] == material["name"]
    response = client.get(f"/api/v1/discussions/{run_id}/events", headers={"Last-Event-ID": "1"})
    assert response.status_code == 200
    assert "id: 1\n" not in response.text
    assert "id: 2\n" in response.text
    assert "fixture_failure" in response.text

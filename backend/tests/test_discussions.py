import asyncio
import json

import pytest

from app.providers import ProviderError
from app.services import discussions
from app.db import SessionLocal
from app.models import DiscussionRun
from app.services.erp import snapshot
from app.services.discussions import artifact, check_turn, known_identifiers

REVIEW_ROLES = {"purchasing", "inventory_planning", "quality", "finance"}


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


def configure_review_provider(monkeypatch, rounds):
    monkeypatch.setenv("LLM_PROVIDER", "vllm")
    monkeypatch.setenv("VLLM_MODEL", "test-review-model")
    monkeypatch.setenv("VLLM_BASE_URL", "http://127.0.0.1:9999/v1")
    monkeypatch.setenv("LLM_REVIEW_ROUNDS", str(rounds))


def create_review(client):
    state = client.get("/api/v1/scenarios/scenario_1").json()
    response = client.post("/api/v1/scenarios/scenario_1/discussions", json={"expected_revision": state["revision"]})
    assert response.status_code == 202, response.text
    return response.json()


def review_turn(role, context, recommendation_ids=()):
    evidence = context["snapshot"]["materials"][0]["id"]
    return {
        "role": role, "strategy_id": context["strategy_id"], "version": context["version"],
        "proposal": {"candidate_ids": context["current_candidate_ids"] if role != "admin" else list(recommendation_ids), "summary": "등록안과 공급 조건 검토"},
        "impacts": [], "reasons": ["공급 확약과 품질 사용 승인 확인 필요"],
        "evidence_refs": [evidence], "change_requests": ["공급 확약 재확인"], "position": "accept",
        "recommendations": [{
            "candidate_id": candidate_id, "claim": "부서 의견을 종합한 우선 제안으로 사람의 승인 필요",
            "evidence_refs": [evidence], "message_refs": [message["id"] for message in context["messages"]],
            "change_refs": [strategy["id"] for strategy in context["strategy_versions"]],
            "remaining_risks": ["사용 전 품질 승인 및 공급 확약 확인 필요"],
        } for candidate_id in recommendation_ids],
    }


@pytest.mark.parametrize("rounds", [1, 2])
def test_parallel_review_barrier_frozen_rounds_full_context_and_admin_order(client, monkeypatch, rounds):
    configure_review_provider(monkeypatch, rounds)
    queued = create_review(client)
    assert queued["calculation"]["review_rounds"] == rounds
    eligible = [
        candidate for candidate in queued["calculation"]["candidates"]
        if candidate["validation"]["hard_constraints_passed"]
        and candidate["validation"]["target_delivery_met"]
        and candidate["validation"].get("cash_feasible", True)
    ]
    assert len(eligible) >= 2
    # The Admin deliberately prefers a different order than the calculator.
    chosen = [candidate["id"] for candidate in sorted(eligible, key=lambda candidate: candidate["rank"], reverse=True)[:2]]
    calls, started, finished, barriers = {}, {}, {}, {}

    async def generate(role, messages, schema):
        context = json.loads(messages[-1]["content"])
        version = context["version"]
        calls[(version, role)] = context
        if role == "admin":
            assert finished == {round_number: REVIEW_ROLES for round_number in range(1, rounds + 1)}
            return review_turn(role, context, chosen)
        started.setdefault(version, set()).add(role)
        barrier = barriers.setdefault(version, asyncio.Event())
        if started[version] == REVIEW_ROLES:
            barrier.set()
        # No reviewer can finish until purchasing and every other reviewer start.
        await asyncio.wait_for(barrier.wait(), timeout=2)
        finished.setdefault(version, set()).add(role)
        return review_turn(role, context)

    monkeypatch.setattr(discussions, "generate_json", generate)
    # A queued run uses its frozen policy, never a new worker environment value.
    monkeypatch.setenv("LLM_REVIEW_ROUNDS", "2" if rounds == 1 else "1")
    asyncio.run(discussions.run_discussion(queued["id"]))
    result = client.get(f"/api/v1/discussions/{queued['id']}").json()
    assert result["status"] == "awaiting_review", result.get("error")
    assert result["progress"]["round"] == rounds
    assert result["progress"]["review_rounds"] == rounds
    assert set(calls) == {
        (version, role) for version in range(1, rounds + 1) for role in REVIEW_ROLES
    } | {(rounds, "admin")}
    assert [strategy["version"] for strategy in result["strategies"]] == list(range(1, rounds + 1))
    assert len(result["messages"]) == 4 * rounds + 1
    for version in range(1, rounds + 1):
        contexts = [calls[(version, role)] for role in REVIEW_ROLES]
        normalized = [{key: value for key, value in context.items() if key != "assigned_role"} for context in contexts]
        assert all(context == normalized[0] for context in normalized)
        previous = contexts[0]["previous_messages"]
        assert {(message["version"], message["role"]) for message in previous} == {
            (prior, role) for prior in range(1, version) for role in REVIEW_ROLES
        }
        assert contexts[0]["snapshot"] == queued["snapshot"]
        assert contexts[0]["registered_candidates"] == queued["calculation"]["candidates"]
        assert contexts[0]["calculation"] == queued["calculation"]
    admin = calls[(rounds, "admin")]
    assert [{key: value for key, value in message.items() if key != "sequence"} for message in admin["messages"]] == [
        message for message in result["messages"] if message["role"] != "admin"
    ]
    assert [{key: value for key, value in strategy.items() if key != "sequence"} for strategy in admin["strategy_versions"]] == result["strategies"]
    assert admin["calculation"] == queued["calculation"]
    assert [recommendation["candidate_id"] for recommendation in result["recommendations"]] == chosen
    assert [recommendation["rank"] for recommendation in result["recommendations"]] == [1, 2]
    assert all(recommendation["status"] == "proposed" for recommendation in result["recommendations"])


def test_failed_parallel_role_blocks_next_round_and_admin(client, monkeypatch):
    configure_review_provider(monkeypatch, 2)
    queued = create_review(client)
    started, finished = set(), set()
    barrier = None

    async def generate(role, messages, schema):
        nonlocal barrier
        assert role != "admin"
        context = json.loads(messages[-1]["content"])
        assert context["version"] == 1
        started.add(role)
        if barrier is None:
            barrier = asyncio.Event()
        if started == REVIEW_ROLES:
            barrier.set()
        await asyncio.wait_for(barrier.wait(), timeout=2)
        finished.add(role)
        if role == "finance":
            raise ProviderError("transport", "Provider unavailable", role)
        return review_turn(role, context)

    monkeypatch.setattr(discussions, "generate_json", generate)
    asyncio.run(discussions.run_discussion(queued["id"]))
    result = client.get(f"/api/v1/discussions/{queued['id']}").json()
    assert started == finished == REVIEW_ROLES
    assert result["status"] == "failed"
    assert result["error"]["code"] == "transport"
    assert result["error"]["role"] == "finance"
    assert result["progress"]["finance"] == "failed"
    assert {(message["version"], message["role"]) for message in result["messages"]} == {
        (1, role) for role in REVIEW_ROLES if role != "finance"
    }
    assert result["recommendations"] == []


@pytest.mark.parametrize("value", ["0", "-1", "1.5", "6", "", "not-a-number"])
def test_invalid_review_rounds_block_readiness_and_run_creation(client, monkeypatch, value):
    configure_review_provider(monkeypatch, value)
    settings = client.get("/api/v1/settings").json()["llm"]
    assert settings["configured"] is False
    assert settings["review_rounds"] is None
    assert "LLM_REVIEW_ROUNDS" in settings["configuration_error"]
    state = client.get("/api/v1/scenarios/scenario_1").json()
    response = client.post("/api/v1/scenarios/scenario_1/discussions", json={"expected_revision": state["revision"]})
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "configuration_error"
    assert client.get("/api/v1/scenarios/scenario_1/discussions").json() == []


def test_default_review_rounds_canonical_configuration_and_obsolete_role_rejection(client, monkeypatch):
    configure_review_provider(monkeypatch, 1)
    monkeypatch.delenv("LLM_REVIEW_ROUNDS")
    settings = client.get("/api/v1/settings").json()["llm"]
    assert settings["review_rounds"] == 1
    assert settings["configured"] is True
    assert set(settings["roles"]) == {"purchasing", "inventory_planning", "quality", "finance", "admin"}
    response = client.post("/api/v1/settings/test-provider", json={"role": "qc"})
    assert response.status_code == 422
    monkeypatch.setenv("LLM_ROLE_MAPPING", json.dumps({"qc": "vllm"}))
    settings = client.get("/api/v1/settings").json()["llm"]
    assert settings["configured"] is False
    assert all("Unknown LLM_ROLE_MAPPING" in role["configuration_error"] for role in settings["roles"].values())


def test_admin_can_choose_single_best_eligible_plan_but_not_ineligible_plan():
    value = turn()
    eligible = {"quantity": "12", "costs": {"total": "12300000"}, "validation": {"hard_constraints_passed": True, "target_delivery_met": True, "cash_feasible": True}}
    candidates = {"candidate": eligible, "alternative": eligible}
    identifiers = {"IL-7", "PROD-01"}
    assert check_turn(value, "admin", "strategy", 1, {"lot"}, candidates, {"message"}, {"strategy"}, identifiers) == []
    candidates["candidate"] = {**eligible, "validation": {**eligible["validation"], "cash_feasible": False}}
    assert "Recommendation violates deterministic constraints" in check_turn(value, "admin", "strategy", 1, {"lot"}, candidates, {"message"}, {"strategy"}, identifiers)

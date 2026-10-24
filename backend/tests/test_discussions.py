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
    return {"role": "orchestrator", "strategy_id": "strategy", "version": 1, "proposal": {"candidate_ids": ["candidate"], "summary": "IL-7 투입 일정 검토"}, "impacts": [], "reasons": [], "evidence_refs": ["lot"], "change_requests": [], "position": "accept", "recommendations": [{"candidate_id": "candidate", "claim": "PROD-01 계획에 맞는 분할 공급", "evidence_refs": ["lot"], "message_refs": ["message"], "change_refs": ["strategy"], "remaining_risks": []}]}


def test_numeric_contradictions_and_nonexistent_message_references_rejected():
    candidates = {"candidate": {"quantity": "12", "costs": {"total": "12300000"}, "validation": {"hard_constraints_passed": True, "target_delivery_met": True, "cash_feasible": True}}}
    value = turn()
    labels = known_identifiers({"materials": [{"name": "재조합 인간 IL-7"}], "production_plans": [{"code": "PROD-01"}]})
    assert check_turn(value, "orchestrator", "strategy", 1, {"lot"}, candidates, {"message"}, {"strategy"}, labels) == []
    value["impacts"] = [{"candidate_id": "candidate", "metric": "total", "value": "12", "evidence_ref": "lot"}]
    assert any("metric" in error for error in check_turn(value, "orchestrator", "strategy", 1, {"lot"}, candidates, {"message"}, {"strategy"}, labels))
    value["impacts"] = []
    value["recommendations"][0]["message_refs"] = ["invented-message"]
    assert any("message IDs" in error for error in check_turn(value, "orchestrator", "strategy", 1, {"lot"}, candidates, {"message"}, {"strategy"}, labels))


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
    if role != "orchestrator":
        first = context["current_candidate_ids"][0]
        # Models refer to plans by ID in prose; the server renders the registered name.
        return {"position": "accept", "candidate_ids": [first], "summary": f"{first} 우선 검토",
                "reasons": ["공급 확약과 품질 사용 승인 확인 필요"], "change_requests": ["공급 확약 재확인"],
                "evidence_refs": [context["erp_data"]["materials"][0]["id"]],
                "metrics": [{"candidate_id": first, "metric": "total"}]}
    evidence = context["materials"][0]["id"]
    return {
        "role": role, "strategy_id": context["strategy_id"], "version": context["version"],
        "proposal": {"candidate_ids": list(recommendation_ids), "summary": "등록안과 공급 조건 검토"},
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
def test_parallel_review_barrier_frozen_rounds_compact_context_and_orchestrator_order(client, monkeypatch, rounds):
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
    # The Orchestrator deliberately prefers a different order than the calculator.
    chosen = [candidate["id"] for candidate in sorted(eligible, key=lambda candidate: candidate["rank"], reverse=True)[:2]]
    calls, started, finished, barriers = {}, {}, {}, {}

    async def generate(role, messages, schema):
        context = json.loads(messages[-1]["content"])
        version = context["version"]
        calls[(version, role)] = context
        if role == "orchestrator":
            assert finished == {round_number: REVIEW_ROLES for round_number in range(1, rounds + 1)}
            return review_turn(role, context, chosen)
        started.setdefault(version, set()).add(role)
        barrier = barriers.setdefault(version, asyncio.Event())
        if started[version] == REVIEW_ROLES:
            barrier.set()
        # No reviewer can finish until purchasing and every other reviewer start.
        await asyncio.wait_for(barrier.wait(), timeout=2)
        finished.setdefault(version, set()).add(role)
        value = review_turn(role, context)
        if role == "quality":
            value["position"] = "object"
            value["change_requests"] = ["출하 Lot별 미확인 품질 문서 확인"]
        elif role == "finance":
            value["position"] = "needs_information"
            value["change_requests"] = ["지급 조건과 현금 한도 재확인"]
        return value

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
    } | {(rounds, "orchestrator")}
    assert [strategy["version"] for strategy in result["strategies"]] == list(range(1, rounds + 1))
    assert len(result["messages"]) == 4 * rounds + 1
    for version in range(1, rounds + 1):
        contexts = {role: calls[(version, role)] for role in REVIEW_ROLES}
        for role, context in contexts.items():
            previous = context["previous_messages"]
            assert {(message["version"], message["role"]) for message in previous} == {
                (prior, role) for prior in range(1, version) for role in REVIEW_ROLES
            }
            # Every reviewer judges every plan, but only with its own department's ERP records.
            assert context["current_candidate_ids"] == [c["id"] for c in queued["calculation"]["candidates"]]
            assert "snapshot" not in context and "calculation" not in context
            assert set(context["erp_data"]) == {name for name in discussions.ROLE_DATA[role] if name in queued["snapshot"]}
            assert context["goal"]["materials"] == queued["calculation"]["materials"]
            assert all("timeline" not in c and "optimistic_timeline" not in c for c in context["registered_candidates"])
        assert "budgets" not in contexts["quality"]["erp_data"] and "lots" not in contexts["finance"]["erp_data"]
        by_id = {c["id"]: c for c in contexts["finance"]["registered_candidates"]}
        assert all("payment_obligations" in by_id[c["id"]] for c in eligible)
        assert all("payment_obligations" not in c for c in contexts["quality"]["registered_candidates"])
        # Ineligible plans are listed without role detail, so many offers cannot dominate the prompt.
        ineligible = [c for c in queued["calculation"]["candidates"] if c not in eligible]
        assert ineligible and all(set(by_id[c["id"]]) <= set(discussions.CANDIDATE_BASE) for c in ineligible)
    orchestrator = calls[(rounds, "orchestrator")]
    reviews = [message for message in result["messages"] if message["role"] != "orchestrator"]
    assert orchestrator["messages"] == [{key: value for key, value in message.items() if key not in {"sequence", "recommendations"}}
                                        for message in reviews]
    # Reviewers only name metrics; stored values and identity come from the server, never the model.
    costs = {candidate["id"]: candidate["costs"] for candidate in queued["calculation"]["candidates"]}
    strategy_versions = {strategy["id"]: strategy["version"] for strategy in result["strategies"]}
    names = {candidate["id"]: candidate["name"] for candidate in queued["calculation"]["candidates"]}
    for message in reviews:
        assert strategy_versions[message["strategy_id"]] == message["version"]
        [impact] = message["impacts"]
        assert impact["value"] == str(costs[impact["candidate_id"]]["total"])
        assert impact["evidence_ref"] == impact["candidate_id"]
        # Names contain digits (delivery counts); a rendered name must still pass the prose digit check.
        assert message["proposal"]["summary"] == f"{names[message['proposal']['candidate_ids'][0]]} 우선 검토"
    assert [(strategy["id"], strategy["version"]) for strategy in orchestrator["strategy_versions"]] == [
        (strategy["id"], strategy["version"]) for strategy in result["strategies"]
    ]
    # Discussion-only integration: no ERP records, only reviews plus the registered plan table.
    assert set(orchestrator) - {"assigned_role", "strategy_id", "version", "reference_contract", "impact_contract"} == {
        "materials", "registered_candidates", "messages", "strategy_versions"}
    compact_candidates = {candidate["id"]: candidate for candidate in orchestrator["registered_candidates"]}
    assert set(compact_candidates) == {candidate["id"] for candidate in queued["calculation"]["candidates"]}
    for candidate in queued["calculation"]["candidates"]:
        assert compact_candidates[candidate["id"]]["validation"] == candidate["validation"]
        assert "deliveries" not in compact_candidates[candidate["id"]]
    cited = {ref for message in reviews for ref in message["evidence_refs"]}
    assert set(orchestrator["reference_contract"]["evidence_ids"]) - set(compact_candidates) - {m["id"] for m in orchestrator["materials"]} <= cited
    assert any(not candidate["validation"]["hard_constraints_passed"] for candidate in compact_candidates.values())
    objections = [message for message in orchestrator["messages"] if message["position"] != "accept"]
    assert {(message["version"], message["position"]) for message in objections} == {
        (version, position) for version in range(1, rounds + 1) for position in ("object", "needs_information")
    }
    stored_objections = [{key: value for key, value in message.items() if key != "sequence"} for message in reviews if message["position"] != "accept"]
    assert all([{key: value for key, value in message.items() if key != "sequence"}
                for message in recommendation["unresolved_objections"]] == stored_objections
               for recommendation in result["recommendations"])
    assert [recommendation["candidate_id"] for recommendation in result["recommendations"]] == chosen
    assert [recommendation["rank"] for recommendation in result["recommendations"]] == [1, 2]
    assert all(recommendation["status"] == "proposed" for recommendation in result["recommendations"])


def test_failed_parallel_role_blocks_next_round_and_orchestrator(client, monkeypatch):
    configure_review_provider(monkeypatch, 2)
    queued = create_review(client)
    started, finished = set(), set()
    barrier = None

    async def generate(role, messages, schema):
        nonlocal barrier
        assert role != "orchestrator"
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


@pytest.mark.parametrize("obsolete_role", ["qc", "admin"])
def test_default_review_rounds_canonical_configuration_and_obsolete_role_rejection(client, monkeypatch, obsolete_role):
    configure_review_provider(monkeypatch, 1)
    monkeypatch.delenv("LLM_REVIEW_ROUNDS")
    settings = client.get("/api/v1/settings").json()["llm"]
    assert settings["review_rounds"] == 1
    assert settings["configured"] is True
    assert set(settings["roles"]) == {"purchasing", "inventory_planning", "quality", "finance", "orchestrator"}
    response = client.post("/api/v1/settings/test-provider", json={"role": obsolete_role})
    assert response.status_code == 422
    monkeypatch.setenv("LLM_ROLE_MAPPING", json.dumps({obsolete_role: "vllm"}))
    settings = client.get("/api/v1/settings").json()["llm"]
    assert settings["configured"] is False
    assert all("Unknown LLM_ROLE_MAPPING" in role["configuration_error"] for role in settings["roles"].values())


def test_orchestrator_can_choose_single_best_eligible_plan_but_not_ineligible_plan():
    value = turn()
    eligible = {"quantity": "12", "costs": {"total": "12300000"}, "validation": {"hard_constraints_passed": True, "target_delivery_met": True, "cash_feasible": True}}
    candidates = {"candidate": eligible, "alternative": eligible}
    identifiers = {"IL-7", "PROD-01"}
    assert check_turn(value, "orchestrator", "strategy", 1, {"lot"}, candidates, {"message"}, {"strategy"}, identifiers) == []
    candidates["candidate"] = {**eligible, "validation": {**eligible["validation"], "cash_feasible": False}}
    assert "Recommendation violates deterministic constraints" in check_turn(value, "orchestrator", "strategy", 1, {"lot"}, candidates, {"message"}, {"strategy"}, identifiers)


@pytest.mark.parametrize("repair", [True, False])
def test_quality_reference_correction_preserves_only_grounded_results(client, monkeypatch, repair):
    configure_review_provider(monkeypatch, 1)
    queued = create_review(client)
    eligible = next(candidate["id"] for candidate in queued["calculation"]["candidates"]
                    if candidate["validation"]["hard_constraints_passed"]
                    and candidate["validation"]["target_delivery_met"]
                    and candidate["validation"].get("cash_feasible", True))
    quality_calls = 0
    orchestrator_called = False

    async def generate(role, messages, schema):
        nonlocal quality_calls, orchestrator_called
        context = json.loads(messages[1]["content"])
        if role == "orchestrator":
            orchestrator_called = True
            return review_turn(role, context, [eligible])
        value = review_turn(role, context)
        if role == "quality":
            quality_calls += 1
            if quality_calls == 1 or not repair:
                value["evidence_refs"] = ["invented-quality-document"]
            else:
                # A repair needs the rejected output and exact allowed IDs, not just an opaque error.
                rejected = json.loads(messages[-2]["content"])
                correction = json.loads(messages[-1]["content"])
                assert rejected["evidence_refs"] == ["invented-quality-document"]
                assert "invented-quality-document" in correction["validation_errors"]
                assert value["evidence_refs"][0] in correction["reference_contract"]["evidence_ids"]
        return value

    monkeypatch.setattr(discussions, "generate_json", generate)
    asyncio.run(discussions.run_discussion(queued["id"]))
    result = client.get(f"/api/v1/discussions/{queued['id']}").json()
    assert quality_calls == 2
    assert orchestrator_called is repair
    assert result["status"] == ("awaiting_review" if repair else "failed")
    quality = [message for message in result["messages"] if message["role"] == "quality"]
    if repair:
        assert len(result["recommendations"]) == 1
        assert len(quality) == 1
        assert set(quality[0]["evidence_refs"]).issubset(discussions.all_ids(queued["snapshot"]))
    else:
        assert quality == []
        assert result["recommendations"] == []
        assert result["error"]["role"] == "quality"
        assert "invented-quality-document" in result["error"]["message"]


def test_disposal_metric_is_cost_not_discarded_quantity():
    value = turn()
    candidates = {"candidate": {"quantity": "20", "costs": {"disposal": "16000"},
                                "validation": {"hard_constraints_passed": True, "target_delivery_met": True, "cash_feasible": True}}}
    value["impacts"] = [{"candidate_id": "candidate", "metric": "disposal", "value": "8", "evidence_ref": "lot"}]
    errors = check_turn(value, "orchestrator", "strategy", 1, {"lot"}, candidates, {"message"}, {"strategy"}, {"IL-7", "PROD-01"})
    assert any("received 8, expected 16000" in error and "monetary amounts" in error for error in errors)
    value["impacts"][0]["value"] = "16000"
    assert check_turn(value, "orchestrator", "strategy", 1, {"lot"}, candidates, {"message"}, {"strategy"}, {"IL-7", "PROD-01"}) == []


def test_codes_in_supplied_findings_are_permitted_but_plain_numbers_are_not_identifiers():
    value = turn()
    candidates = {"candidate": {"quantity": "12", "costs": {"total": "12300000"},
                               "validation": {"hard_constraints_passed": True, "target_delivery_met": True, "cash_feasible": True}}}
    identifiers = known_identifiers({"reasons": ["SYN-COA-IL7-1 확인 필요", "IL-7과 PROD-01 검토"],
                                     "records": [{"name": "12", "id": "12300000"}]})
    value["reasons"] = ["SYN-COA-IL7-1 문서 확인 필요"]
    assert check_turn(value, "orchestrator", "strategy", 1, {"lot"}, candidates, {"message"}, {"strategy"}, identifiers) == []
    value["reasons"] = ["구매량 12"]
    assert any("Numerical claims" in error for error in check_turn(
        value, "orchestrator", "strategy", 1, {"lot"}, candidates, {"message"}, {"strategy"}, identifiers))


def test_prose_ids_render_as_names_and_unknown_ids_are_rejected():
    known, unknown = "0b3c9a1e-1111-4a2b-8c3d-000000000001", "0b3c9a1e-9999-4a2b-8c3d-000000000009"
    candidates = {"candidate": {"quantity": "12", "costs": {"total": "12300000"},
                                "validation": {"hard_constraints_passed": True, "target_delivery_met": True, "cash_feasible": True}}}
    value = turn()
    value["reasons"] = [f"{known}는 공급 확약 확인 필요"]
    rendered = discussions.humanize(value, {known: "OFFER-2 · 2회 입고"})
    assert value["reasons"] == ["OFFER-2 · 2회 입고는 공급 확약 확인 필요"]
    fixture_codes = known_identifiers(turn())
    assert check_turn(value, "orchestrator", "strategy", 1, {"lot"}, candidates, {"message"}, {"strategy"}, rendered | fixture_codes) == []
    value["reasons"] = [f"{unknown}는 확인 필요"]
    rendered = discussions.humanize(value, {known: "OFFER-2 · 2회 입고"})
    assert unknown in value["reasons"][0]
    assert any("Numerical claims" in error for error in check_turn(
        value, "orchestrator", "strategy", 1, {"lot"}, candidates, {"message"}, {"strategy"}, rendered | fixture_codes))


def test_orchestrator_cannot_cite_erp_records_no_department_cited(client, monkeypatch):
    configure_review_provider(monkeypatch, 1)
    queued = create_review(client)
    eligible = next(candidate["id"] for candidate in queued["calculation"]["candidates"]
                    if candidate["validation"]["hard_constraints_passed"]
                    and candidate["validation"]["target_delivery_met"]
                    and candidate["validation"].get("cash_feasible", True))
    # A real snapshot record, but no reviewer cited it.
    uncited = queued["snapshot"]["lots"][0]["id"]
    orchestrator_calls = 0

    async def generate(role, messages, schema):
        nonlocal orchestrator_calls
        context = json.loads(messages[1]["content"])
        value = review_turn(role, context, [eligible] if role == "orchestrator" else [])
        if role == "orchestrator":
            orchestrator_calls += 1
            assert uncited not in context["reference_contract"]["evidence_ids"]
            value["recommendations"][0]["evidence_refs"] = [uncited]
        return value

    monkeypatch.setattr(discussions, "generate_json", generate)
    asyncio.run(discussions.run_discussion(queued["id"]))
    result = client.get(f"/api/v1/discussions/{queued['id']}").json()
    assert orchestrator_calls == 2
    assert result["status"] == "failed"
    assert result["error"]["role"] == "orchestrator"
    assert "Unknown recommendation evidence_refs" in result["error"]["message"]
    assert result["recommendations"] == []


def test_final_deterministic_revalidation_vetoes_compact_context_recommendation(client, monkeypatch):
    configure_review_provider(monkeypatch, 1)
    queued = create_review(client)
    eligible = next(candidate for candidate in queued["calculation"]["candidates"]
                    if candidate["validation"]["hard_constraints_passed"]
                    and candidate["validation"]["target_delivery_met"]
                    and candidate["validation"].get("cash_feasible", True))
    validated = []

    async def generate(role, messages, schema):
        context = json.loads(messages[1]["content"])
        return review_turn(role, context, [eligible["id"]] if role == "orchestrator" else [])

    def reject_original_snapshot(data, candidate, as_of=None):
        validated.append((data, candidate, as_of))
        return {**candidate, "validation": {**candidate["validation"], "cash_feasible": False}}

    monkeypatch.setattr(discussions, "generate_json", generate)
    monkeypatch.setattr(discussions, "validate_strategy", reject_original_snapshot)
    asyncio.run(discussions.run_discussion(queued["id"]))
    result = client.get(f"/api/v1/discussions/{queued['id']}").json()
    assert validated == [(queued["snapshot"], eligible, queued["calculation"]["as_of"])]
    assert result["status"] == "failed"
    assert result["error"]["message"] == "Recommendation failed final deterministic validation"
    assert result["recommendations"] == []

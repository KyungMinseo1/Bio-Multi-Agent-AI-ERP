import asyncio
import json
from types import SimpleNamespace

import pytest

from app import providers
from app.schemas import DepartmentTurn, ReviewTurn


@pytest.fixture
def provider_config(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "vllm")
    monkeypatch.setenv("VLLM_MODEL", "test-model")
    monkeypatch.setenv("VLLM_BASE_URL", "http://localhost:9999/v1")
    monkeypatch.setenv("LLM_ROLE_MAPPING", "{}")
    monkeypatch.delenv("LLM_TIMEOUT_SECONDS", raising=False)
    monkeypatch.delenv("LLM_ORCHESTRATOR_TIMEOUT_SECONDS", raising=False)
    monkeypatch.setattr(providers, "_clients", {})


def test_role_deadline_defaults_and_override(provider_config, monkeypatch):
    assert providers.configuration("orchestrator")["timeout"] == 180
    for role in ("purchasing", "inventory_planning", "quality", "finance"):
        assert providers.configuration(role)["timeout"] == 60
    monkeypatch.setenv("LLM_TIMEOUT_SECONDS", "12")
    monkeypatch.setenv("LLM_ORCHESTRATOR_TIMEOUT_SECONDS", "240")
    assert providers.configuration("finance")["timeout"] == 12
    assert providers.configuration("orchestrator")["timeout"] == 240
    monkeypatch.setenv("LLM_ROLE_MAPPING", json.dumps({"orchestrator": {"timeout": 90}}))
    assert providers.configuration("orchestrator")["timeout"] == 90
    # An explicit role deadline replaces, rather than validates, an unused environment default.
    monkeypatch.setenv("LLM_ORCHESTRATOR_TIMEOUT_SECONDS", "invalid")
    assert providers.configuration("orchestrator")["configured"] is True


@pytest.mark.parametrize("value", ["0", "-1", "nan", "inf", "-inf", "", "invalid"])
def test_invalid_orchestrator_environment_blocks_readiness(provider_config, monkeypatch, value):
    monkeypatch.setenv("LLM_ORCHESTRATOR_TIMEOUT_SECONDS", value)
    settings = providers.public_settings()
    assert settings["configured"] is False
    assert settings["roles"]["finance"]["configured"] is True
    assert "LLM_ORCHESTRATOR_TIMEOUT_SECONDS" in settings["roles"]["orchestrator"]["configuration_error"]
    with pytest.raises(providers.ProviderError) as raised:
        providers.require_configuration()
    assert raised.value.role == "orchestrator"
    assert raised.value.code == "configuration_error"


@pytest.mark.parametrize("value", [0, -1, True, None, "nan", "inf", [], {}])
def test_invalid_explicit_role_deadlines_are_not_fallbacks(provider_config, monkeypatch, value):
    monkeypatch.setenv("LLM_ROLE_MAPPING", json.dumps({"orchestrator": {"timeout": value}}))
    config = providers.configuration("orchestrator")
    assert config["configured"] is False
    assert "finite positive" in config["configuration_error"]


@pytest.mark.parametrize("override", [False, True])
def test_actual_async_deadlines_separate_reviewers_from_synthesis(provider_config, monkeypatch, override):
    monkeypatch.setenv("LLM_TIMEOUT_SECONDS", "0.02")
    monkeypatch.setenv("LLM_ORCHESTRATOR_TIMEOUT_SECONDS", "0.02" if override else "0.5")
    if override:
        monkeypatch.setenv("LLM_ROLE_MAPPING", json.dumps({"orchestrator": {"timeout": 0.5}}))
    calls, sdk_deadlines, cancelled = [], [], []

    def client(**kwargs):
        sdk_deadlines.append((kwargs["timeout"], kwargs["max_retries"]))

        async def create(**request):
            role = request["messages"][0]["content"]
            calls.append(role)
            try:
                await asyncio.sleep(0.1)
            except asyncio.CancelledError:
                cancelled.append(role)
                raise
            result = {"role": role, "strategy_id": "strategy", "version": 1,
                      "proposal": {"candidate_ids": [], "summary": "검토"},
                      "impacts": [], "reasons": [], "evidence_refs": [], "change_requests": [],
                      "position": "needs_information", "recommendations": []}
            return SimpleNamespace(choices=[SimpleNamespace(finish_reason="stop", message=SimpleNamespace(content=json.dumps(result)))])

        return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))

    monkeypatch.setattr(providers, "AsyncOpenAI", client)

    async def scenario():
        return await asyncio.gather(*[
            providers.generate_json(role, [{"role": "user", "content": role}], DepartmentTurn)
            for role in ("finance", "orchestrator")
        ], return_exceptions=True)

    reviewer, orchestrator = asyncio.run(scenario())
    assert isinstance(reviewer, providers.ProviderError)
    assert reviewer.code == "timeout"
    assert "0.02 seconds" in reviewer.message
    assert "LLM_TIMEOUT_SECONDS" in reviewer.message
    assert orchestrator["role"] == "orchestrator"
    assert cancelled == ["finance"]
    assert calls == ["finance", "orchestrator"]
    assert sdk_deadlines == [(0.02, 0), (0.5, 0)]


def test_uuids_are_aliased_on_the_wire_and_restored_in_output(provider_config, monkeypatch):
    lot, candidate = "0b3c9a1e-1111-4a2b-8c3d-000000000001", "0b3c9a1e-2222-4a2b-8c3d-000000000002"
    sent = []

    def client(**kwargs):
        async def create(**request):
            sent.append(request["messages"])
            text = request["messages"][0]["content"]
            # The data already contains "R1", so aliases must not collide with it.
            aliases = json.loads(text)["ids"]
            result = {"position": "accept", "candidate_ids": [aliases[1]], "summary": f"{aliases[1]}를 우선 검토", "reasons": ["R1 코드 확인"],
                      "change_requests": [], "evidence_refs": [aliases[0], "RR99"],
                      "metrics": [{"candidate_id": aliases[1], "metric": "total"}]}
            return SimpleNamespace(choices=[SimpleNamespace(finish_reason="stop", message=SimpleNamespace(content=json.dumps(result)))])
        return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))

    monkeypatch.setattr(providers, "AsyncOpenAI", client)
    content = json.dumps({"ids": [lot, candidate], "code": "R1", "again": lot})
    result = asyncio.run(providers.generate_json("finance", [{"role": "user", "content": content}], ReviewTurn))
    wire = sent[0][0]["content"]
    assert lot not in wire and candidate not in wire and '"R1"' in wire
    assert wire.count(json.loads(wire)["ids"][0]) == 2
    assert result["candidate_ids"] == [candidate]
    assert result["metrics"][0]["candidate_id"] == candidate
    # Aliases in prose are restored too (even before a Korean particle) for the caller to render as names;
    # data text that merely resembles an alias is untouched, and an invented alias stays visible to validation.
    assert result["summary"] == f"{candidate}를 우선 검토"
    assert result["evidence_refs"] == [lot, "RR99"]
    assert result["reasons"] == ["R1 코드 확인"]


@pytest.mark.parametrize("sdk_timeout", [False, True])
def test_timeout_diagnostics_consistent_and_not_retried(provider_config, monkeypatch, sdk_timeout):
    monkeypatch.setenv("LLM_ORCHESTRATOR_TIMEOUT_SECONDS", "0.02")
    calls = []
    class APITimeoutError(Exception):
        pass

    def client(**kwargs):
        async def create(**request):
            calls.append(request)
            if sdk_timeout:
                raise APITimeoutError("secret provider payload must not escape")
            await asyncio.sleep(1)
        return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))

    monkeypatch.setattr(providers, "AsyncOpenAI", client)
    with pytest.raises(providers.ProviderError) as raised:
        asyncio.run(providers.generate_json("orchestrator", [], DepartmentTurn))
    error = raised.value
    assert (error.code, error.role) == ("timeout", "orchestrator")
    assert "0.02 seconds" in error.message
    assert "LLM_ORCHESTRATOR_TIMEOUT_SECONDS" in error.message
    assert "LLM_ROLE_MAPPING.orchestrator.timeout" in error.message
    assert "secret" not in error.message
    assert len(calls) == 1

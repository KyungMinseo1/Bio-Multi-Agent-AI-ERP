import asyncio
import json

import pytest

from app import providers
from app.config import CANONICAL_ROLES
from app.schemas import DepartmentTurn


@pytest.fixture
def reasoning_config(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai_compatible")
    monkeypatch.setenv("OPENAI_COMPATIBLE_MODEL", "configured-model")
    monkeypatch.setenv("OPENAI_COMPATIBLE_BASE_URL", "http://localhost:9999/v1")
    monkeypatch.setenv("LLM_ROLE_MAPPING", "{}")
    monkeypatch.setenv("LLM_REVIEW_ROUNDS", "1")
    for name in ("LLM_REASONING_EFFORT", "LLM_TIMEOUT_SECONDS", "LLM_ORCHESTRATOR_TIMEOUT_SECONDS"):
        monkeypatch.delenv(name, raising=False)


def test_absent_reasoning_setting_preserves_model_default(reasoning_config):
    settings = providers.public_settings()
    assert settings["configured"] is True
    assert all(role["reasoning_effort"] == "auto" for role in settings["roles"].values())


@pytest.mark.parametrize("effort", ["auto", "low", "medium", "high"])
def test_global_reasoning_setting_applies_to_every_role(reasoning_config, monkeypatch, effort):
    monkeypatch.setenv("LLM_REASONING_EFFORT", effort)
    for role in CANONICAL_ROLES:
        config = providers.configuration(role)
        assert config["configured"] is True
        assert config["reasoning_effort"] == effort


@pytest.mark.parametrize("effort", ["auto", "low", "medium", "high"])
def test_role_reasoning_override_takes_precedence(reasoning_config, monkeypatch, effort):
    monkeypatch.setenv("LLM_REASONING_EFFORT", "medium")
    monkeypatch.setenv("LLM_ROLE_MAPPING", json.dumps({"orchestrator": {"reasoning_effort": effort}}))
    settings = providers.public_settings()
    assert settings["configured"] is True
    assert settings["roles"]["orchestrator"]["reasoning_effort"] == effort
    assert settings["roles"]["finance"]["reasoning_effort"] == "medium"


@pytest.mark.parametrize("value", ["", "LOW", " low", "low ", "none", "minimal", "invalid"])
def test_invalid_global_reasoning_blocks_readiness(reasoning_config, monkeypatch, value):
    monkeypatch.setenv("LLM_REASONING_EFFORT", value)
    settings = providers.public_settings()
    assert settings["configured"] is False
    assert all(role["configured"] is False for role in settings["roles"].values())
    with pytest.raises(providers.ProviderError) as raised:
        providers.require_configuration()
    assert raised.value.code == "configuration_error"
    assert "LLM_REASONING_EFFORT" in raised.value.message


@pytest.mark.parametrize("value", [None, True, False, 0, 1, [], {}, "LOW", "", "none"])
def test_invalid_role_reasoning_is_not_normalized_or_replaced(reasoning_config, monkeypatch, value):
    monkeypatch.setenv("LLM_REASONING_EFFORT", "low")
    monkeypatch.setenv("LLM_ROLE_MAPPING", json.dumps({"orchestrator": {"reasoning_effort": value}}))
    settings = providers.public_settings()
    assert settings["configured"] is False
    assert settings["roles"]["finance"]["configured"] is True
    assert settings["roles"]["orchestrator"]["configured"] is False
    with pytest.raises(providers.ProviderError) as raised:
        providers.require_configuration()
    assert (raised.value.code, raised.value.role) == ("configuration_error", "orchestrator")
    assert "LLM_ROLE_MAPPING.orchestrator.reasoning_effort" in raised.value.message


def test_explicit_role_settings_replace_unused_invalid_global(reasoning_config, monkeypatch):
    monkeypatch.setenv("LLM_REASONING_EFFORT", "invalid")
    monkeypatch.setenv("LLM_ROLE_MAPPING", json.dumps({role: {"reasoning_effort": "auto"} for role in CANONICAL_ROLES}))
    settings = providers.public_settings()
    assert settings["configured"] is True
    assert all(role["reasoning_effort"] == "auto" for role in settings["roles"].values())


@pytest.mark.parametrize("effort", ["low", "medium", "high"])
def test_native_gemini_rejects_unmapped_reasoning_before_request(reasoning_config, monkeypatch, effort):
    monkeypatch.setenv("GEMINI_MODEL", "gemini-2.5-pro")
    monkeypatch.setenv("GEMINI_API_KEY", "test-only-key")
    monkeypatch.setenv("LLM_REASONING_EFFORT", "low")
    monkeypatch.setenv("LLM_ROLE_MAPPING", json.dumps({"orchestrator": {"provider": "gemini", "reasoning_effort": effort}}))
    settings = providers.public_settings()
    assert settings["configured"] is False
    assert settings["roles"]["finance"]["configured"] is True
    with pytest.raises(providers.ProviderError) as raised:
        asyncio.run(providers.generate_json("orchestrator", [], DepartmentTurn))
    assert (raised.value.code, raised.value.role) == ("configuration_error", "orchestrator")
    assert "Native Gemini" in raised.value.message
    assert "auto" in raised.value.message
    monkeypatch.setenv("LLM_ROLE_MAPPING", json.dumps({"orchestrator": {"provider": "gemini", "reasoning_effort": "auto"}}))
    assert providers.public_settings()["configured"] is True

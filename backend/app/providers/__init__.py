import asyncio
import json
from openai import AsyncOpenAI
from google import genai
from google.genai import types
from jsonschema import Draft202012Validator
from ..config import CANONICAL_ROLES, setting, role_mapping, review_rounds
from ..schemas import DepartmentTurn

NAMES = ("openai", "gemini", "openrouter", "vllm", "openai_compatible")
_clients = {}


class ProviderError(Exception):
    def __init__(self, code, message, role=None):
        super().__init__(message)
        self.code, self.message, self.role = code, message, role


def configuration(role=None):
    mappings = role_mapping()
    mapping = mappings.get(role, {}) if role else {}
    error = mappings.get("__configuration_error__")
    if role is not None and role not in CANONICAL_ROLES:
        error = "Unknown department role"
    if isinstance(mapping, str):
        mapping = {"provider": mapping}
    if not isinstance(mapping, dict):
        mapping, error = {}, "Role mapping must be an object or provider name"
    name = mapping.get("provider", setting("LLM_PROVIDER"))
    if not isinstance(name, str):
        name, error = "", "Provider name must be a string"
    prefix = name.upper()
    model = mapping.get("model", setting(f"{prefix}_MODEL"))
    key = setting(f"{prefix}_API_KEY")
    base = mapping.get("base_url", setting(f"{prefix}_BASE_URL"))
    try:
        timeout = float(mapping.get("timeout", setting("LLM_TIMEOUT_SECONDS", "60")))
        if not 0 < timeout < float("inf"):
            raise ValueError()
    except (ValueError, TypeError):
        timeout, error = 60, "Timeout must be a finite positive number"
    configured = not error and name in NAMES and isinstance(model, str) and bool(model) and (isinstance(base, str) and bool(base) if name in {"vllm", "openai_compatible"} else bool(key))
    return {"provider": name, "model": model, "configured": bool(configured), "base_url": base, "timeout": timeout, "configuration_error": error}


def public_settings():
    roles = {r: {key: value for key, value in configuration(r).items() if key != "base_url"} for r in CANONICAL_ROLES}
    try:
        rounds, error = review_rounds(), None
    except ValueError as exc:
        rounds, error = None, str(exc)
    return {"provider": setting("LLM_PROVIDER"), "configured": not error and all(value["configured"] for value in roles.values()), "review_rounds": rounds, "configuration_error": error, "providers": {name: {"configured": bool(setting(f"{name.upper()}_MODEL")) and bool(setting(f"{name.upper()}_BASE_URL")) if name in {"vllm", "openai_compatible"} else bool(setting(f"{name.upper()}_MODEL") and setting(f"{name.upper()}_API_KEY")), "model": setting(f"{name.upper()}_MODEL")} for name in NAMES}, "roles": roles}


def require_configuration():
    try:
        review_rounds()
    except ValueError as exc:
        raise ProviderError("configuration_error", str(exc)) from None
    for role in CANONICAL_ROLES:
        if not configuration(role)["configured"]:
            raise ProviderError("configuration_error", f"Configure provider credentials and explicit model for {role}", role)


async def close_clients():
    for client in _clients.values():
        if isinstance(client, AsyncOpenAI):
            await client.close()
        else:
            await client.aio.aclose()
    _clients.clear()


async def generate_json(role: str, messages: list[dict], schema: dict) -> dict:
    config = configuration(role)
    if not config["configured"]:
        raise ProviderError("configuration_error", f"Provider/model not configured for {role}", role)
    name, model = config["provider"], config["model"]
    timeout = config["timeout"]
    cache_key = (name, config["base_url"], timeout)
    try:
        if cache_key not in _clients:
            if name == "gemini":
                _clients[cache_key] = genai.Client(api_key=setting("GEMINI_API_KEY"), http_options=types.HttpOptions(timeout=int(timeout * 1000)))
            else:
                base = config["base_url"] or {"openai": "https://api.openai.com/v1", "openrouter": "https://openrouter.ai/api/v1"}.get(name)
                if name in {"vllm", "openai_compatible"} and not base.rstrip("/").endswith("/v1"):
                    raise ProviderError("configuration_error", f"{name.upper()}_BASE_URL must end in /v1", role)
                _clients[cache_key] = AsyncOpenAI(api_key=setting(f"{name.upper()}_API_KEY") or "not-required", base_url=base, timeout=timeout, max_retries=0)
        client = _clients[cache_key]
        async with asyncio.timeout(timeout):
            if name == "openai":
                response = await client.responses.parse(model=model, input=messages, text_format=DepartmentTurn)
                if response.status != "completed":
                    raise ProviderError("incomplete", "Provider response was incomplete", role)
                if response.output_parsed is None:
                    raise ProviderError("refused_or_blocked", "Provider refused or produced no parsed output", role)
                result = response.output_parsed.model_dump()
            elif name == "gemini":
                system = "\n".join(m["content"] for m in messages if m["role"] == "system")
                contents = json.dumps([m for m in messages if m["role"] != "system"], ensure_ascii=False)
                response = await client.aio.models.generate_content(model=model, contents=contents, config=types.GenerateContentConfig(system_instruction=system, response_mime_type="application/json", response_json_schema=schema))
                if getattr(response, "prompt_feedback", None) and getattr(response.prompt_feedback, "block_reason", None):
                    raise ProviderError("refused_or_blocked", "Provider blocked prompt", role)
                if not response.candidates:
                    raise ProviderError("refused_or_blocked", "Provider returned no candidates", role)
                reason = str(response.candidates[0].finish_reason).split(".")[-1]
                if reason != "STOP":
                    raise ProviderError("incomplete", "Provider did not finish normally", role)
                result = json.loads(response.text)
            else:
                kwargs = {"extra_body": {"provider": {"require_parameters": True}}} if name == "openrouter" else {}
                response = await client.chat.completions.create(model=model, messages=messages, response_format={"type": "json_schema", "json_schema": {"name": "department_turn", "strict": True, "schema": schema}}, **kwargs)
                if getattr(response, "error", None):
                    raise ProviderError("provider_rejected", "Provider returned an error payload", role)
                if not response.choices or response.choices[0].finish_reason != "stop":
                    raise ProviderError("incomplete", "Provider did not finish normally", role)
                message = response.choices[0].message
                if getattr(message, "refusal", None) or not message.content:
                    raise ProviderError("refused_or_blocked", "Provider refused or returned empty content", role)
                result = json.loads(message.content)
            Draft202012Validator(schema).validate(result)
            return DepartmentTurn.model_validate(result).model_dump()
    except ProviderError:
        raise
    except (TimeoutError, asyncio.TimeoutError):
        raise ProviderError("timeout", "LLM request timed out", role) from None
    except Exception as exc:
        kind = type(exc).__name__
        if kind in {"ValidationError", "JSONDecodeError"}:
            code = "invalid_output"
        elif "Timeout" in kind:
            code = "timeout"
        elif "Connection" in kind or "Transport" in kind:
            code = "transport"
        else:
            code = "provider_rejected"
        raise ProviderError(code, f"LLM request failed ({code}); verify provider configuration and structured-output support", role) from None

import asyncio
import json
import re
from openai import AsyncOpenAI
from google import genai
from google.genai import types
from jsonschema import Draft202012Validator
from pydantic import BaseModel
from ..config import CANONICAL_ROLES, setting, role_mapping, review_rounds

UUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
# ASCII-only boundaries: Korean particles are word characters, so \b would miss "R84를".
ALIAS = re.compile(r"(?<![A-Za-z0-9])R+\d+(?![0-9])")


def alias_uuids(messages):
    """Replace UUIDs with short aliases on the wire.

    A UUID costs roughly twenty tokens and is easy to miscopy; IDs are most of
    the structured output. Returns aliased messages and the alias -> UUID map.
    """
    text = "\n".join(message["content"] for message in messages)
    prefix = "R"
    while re.search(rf"(?<![A-Za-z0-9]){prefix}\d+(?![0-9])", text):
        prefix += "R"
    forward = {}
    for identifier in UUID.findall(text):
        forward.setdefault(identifier, f"{prefix}{len(forward) + 1}")
    aliased = [{**message, "content": UUID.sub(lambda match: forward[match.group(0)], message["content"])} for message in messages]
    return aliased, {alias: identifier for identifier, alias in forward.items()}


def unalias(value, reverse):
    """Restore UUIDs, including aliases a model wrote inside prose.

    Unknown aliases stay as-is so validation rejects them; the caller renders
    restored prose IDs as readable names.
    """
    if isinstance(value, dict):
        return {key: unalias(item, reverse) for key, item in value.items()}
    if isinstance(value, list):
        return [unalias(item, reverse) for item in value]
    if isinstance(value, str):
        return ALIAS.sub(lambda match: reverse.get(match.group(0), match.group(0)), value)
    return value

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
    timeout_setting = "LLM_ORCHESTRATOR_TIMEOUT_SECONDS" if role == "orchestrator" else "LLM_TIMEOUT_SECONDS"
    default_timeout = 180 if role == "orchestrator" else 60
    try:
        raw_timeout = mapping.get("timeout", setting(timeout_setting, str(default_timeout)))
        if isinstance(raw_timeout, bool):
            raise ValueError()
        timeout = float(raw_timeout)
        if not 0 < timeout < float("inf"):
            raise ValueError()
    except (ValueError, TypeError, OverflowError):
        timeout, error = default_timeout, f"{timeout_setting} or LLM_ROLE_MAPPING.{role}.timeout must be a finite positive number"
    reasoning_effort = mapping.get("reasoning_effort", setting("LLM_REASONING_EFFORT", "auto"))
    if not isinstance(reasoning_effort, str) or reasoning_effort not in {"auto", "low", "medium", "high"}:
        error = f"LLM_REASONING_EFFORT or LLM_ROLE_MAPPING.{role}.reasoning_effort must be auto, low, medium, or high"
    elif name == "gemini" and reasoning_effort != "auto":
        error = (
            "Native Gemini reasoning_effort is unsupported by this integration: thinking_level and "
            "thinking_budget support depends on the model. Set reasoning_effort to auto for Gemini."
        )
    configured = not error and name in NAMES and isinstance(model, str) and bool(model) and (isinstance(base, str) and bool(base) if name in {"vllm", "openai_compatible"} else bool(key))
    return {"provider": name, "model": model, "configured": bool(configured), "base_url": base, "timeout": timeout, "reasoning_effort": reasoning_effort, "configuration_error": error}


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
        config = configuration(role)
        if not config["configured"]:
            raise ProviderError("configuration_error", config["configuration_error"] or f"Configure provider credentials and explicit model for {role}", role)


async def close_clients():
    for client in _clients.values():
        if isinstance(client, AsyncOpenAI):
            await client.close()
        else:
            await client.aio.aclose()
    _clients.clear()


async def generate_json(role: str, messages: list[dict], output: type[BaseModel]) -> dict:
    schema = output.model_json_schema()
    messages, reverse = alias_uuids(messages)
    config = configuration(role)
    if not config["configured"]:
        raise ProviderError("configuration_error", config["configuration_error"] or f"Provider/model not configured for {role}", role)
    name, model = config["provider"], config["model"]
    timeout = config["timeout"]
    timeout_setting = "LLM_ORCHESTRATOR_TIMEOUT_SECONDS" if role == "orchestrator" else "LLM_TIMEOUT_SECONDS"
    timeout_message = (
        f"LLM request timed out after configured deadline of {timeout:g} seconds for {role}; "
        f"adjust {timeout_setting} or LLM_ROLE_MAPPING.{role}.timeout "
        "(explicit role timeout takes precedence). No automatic timeout retry was attempted."
    )
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
                kwargs = {"reasoning": {"effort": config["reasoning_effort"]}} if config["reasoning_effort"] != "auto" else {}
                response = await client.responses.parse(model=model, input=messages, text_format=output, **kwargs)
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
                if config["reasoning_effort"] != "auto":
                    kwargs["reasoning_effort"] = config["reasoning_effort"]
                response = await client.chat.completions.create(model=model, messages=messages, response_format={"type": "json_schema", "json_schema": {"name": output.__name__, "strict": True, "schema": schema}}, **kwargs)
                if getattr(response, "error", None):
                    raise ProviderError("provider_rejected", "Provider returned an error payload", role)
                if not response.choices or response.choices[0].finish_reason != "stop":
                    raise ProviderError("incomplete", "Provider did not finish normally", role)
                message = response.choices[0].message
                if getattr(message, "refusal", None) or not message.content:
                    raise ProviderError("refused_or_blocked", "Provider refused or returned empty content", role)
                result = json.loads(message.content)
            Draft202012Validator(schema).validate(result)
            return unalias(output.model_validate(result).model_dump(), reverse)
    except ProviderError:
        raise
    except (TimeoutError, asyncio.TimeoutError):
        raise ProviderError("timeout", timeout_message, role) from None
    except Exception as exc:
        kind = type(exc).__name__
        if kind in {"ValidationError", "JSONDecodeError"}:
            code = "invalid_output"
        elif "Timeout" in kind:
            raise ProviderError("timeout", timeout_message, role) from None
        elif "Connection" in kind or "Transport" in kind:
            code = "transport"
        else:
            code = "provider_rejected"
        raise ProviderError(code, f"LLM request failed ({code}); verify provider configuration, structured-output support, and model/server reasoning-effort support", role) from None

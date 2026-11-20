"""LLM configuration loaded from environment variables (and an optional .env file)."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

ENV_HINT = "Copy .env.example to .env and set it, or export it in your shell."

# Provider-specific fallbacks for the API key, checked after LLM_API_KEY.
_API_KEY_FALLBACKS: dict[str, tuple[str, ...]] = {
    "openai": ("OPENAI_API_KEY",),
    "azure": ("AZURE_OPENAI_API_KEY",),
}


class ConfigError(ValueError):
    """Raised when the LLM configuration is missing or invalid."""


@dataclass(frozen=True)
class LLMConfig:
    provider: str
    api_key: str = field(repr=False)
    model: str
    model_light: str | None = None
    base_url: str | None = None
    timeout: float = 600.0
    max_attempts: int = 3
    extra_headers: tuple[tuple[str, str], ...] = ()
    azure_api_version: str | None = None

    def describe(self) -> str:
        """Human-readable summary that never includes the API key."""
        parts = [f"provider={self.provider}", f"model={self.model}"]
        if self.model_light:
            parts.append(f"light_model={self.model_light}")
        parts.append(f"base_url={self.base_url or '(provider default)'}")
        return ", ".join(parts)


def _get(env: dict, name: str) -> str | None:
    value = env.get(name)
    if value is None:
        return None
    value = value.strip()
    return value or None


def _parse_number(env: dict, name: str, default, cast, minimum):
    raw = _get(env, name)
    if raw is None:
        return default
    try:
        value = cast(raw)
    except ValueError:
        raise ConfigError(f"{name} must be a number, got {raw!r}.") from None
    if value < minimum:
        raise ConfigError(f"{name} must be >= {minimum}, got {raw!r}.")
    return value


def _parse_headers(env: dict) -> tuple[tuple[str, str], ...]:
    raw = _get(env, "LLM_EXTRA_HEADERS")
    if raw is None:
        return ()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ConfigError(f"LLM_EXTRA_HEADERS must be a JSON object: {e}") from None
    if not isinstance(data, dict) or not all(isinstance(v, str) for v in data.values()):
        raise ConfigError('LLM_EXTRA_HEADERS must be a JSON object of strings, e.g. {"X-Title": "my-app"}.')
    return tuple(sorted((str(k), v) for k, v in data.items()))


def load_config(env: dict | None = None) -> LLMConfig:
    """Build an LLMConfig from environment variables, raising ConfigError with a clear message."""
    # Imported lazily to avoid a circular import with the registry.
    from agent.providers import available_providers

    env = os.environ if env is None else env

    provider = (_get(env, "LLM_PROVIDER") or "openai").lower()
    valid = available_providers()
    if provider not in valid:
        raise ConfigError(
            f"Unknown LLM_PROVIDER={provider!r}. Supported providers: {', '.join(valid)}."
        )

    key_vars = ("LLM_API_KEY",) + _API_KEY_FALLBACKS.get(provider, ())
    api_key = next((v for v in (_get(env, k) for k in key_vars) if v), None)
    if not api_key:
        raise ConfigError(
            f"No API key configured. Set {' or '.join(key_vars)}. {ENV_HINT} "
            "(Local servers such as Ollama accept any placeholder value.)"
        )

    model = _get(env, "LLM_MODEL")
    if not model:
        what = "your Azure deployment name" if provider == "azure" else "the model name to use"
        raise ConfigError(f"LLM_MODEL is not set. Set it to {what}. {ENV_HINT}")

    base_url = _get(env, "LLM_BASE_URL")
    azure_api_version = _get(env, "AZURE_OPENAI_API_VERSION")
    if provider == "azure":
        base_url = base_url or _get(env, "AZURE_OPENAI_ENDPOINT")
        if not base_url:
            raise ConfigError(
                "LLM_PROVIDER=azure requires LLM_BASE_URL (or AZURE_OPENAI_ENDPOINT), "
                "e.g. https://<resource>.openai.azure.com"
            )
        if not azure_api_version:
            raise ConfigError(
                "LLM_PROVIDER=azure requires AZURE_OPENAI_API_VERSION, e.g. 2024-10-21."
            )

    return LLMConfig(
        provider=provider,
        api_key=api_key,
        model=model,
        model_light=_get(env, "LLM_MODEL_LIGHT"),
        base_url=base_url,
        timeout=_parse_number(env, "LLM_TIMEOUT", 600.0, float, 1),
        max_attempts=_parse_number(env, "LLM_MAX_ATTEMPTS", 3, int, 1),
        extra_headers=_parse_headers(env),
        azure_api_version=azure_api_version,
    )

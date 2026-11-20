"""Pluggable LLM provider adapters.

Select a provider with the ``LLM_PROVIDER`` environment variable. Built-in
providers:

- ``openai``: any OpenAI Chat Completions-compatible endpoint (default)
- ``azure``: Azure OpenAI Service

To add a provider, subclass :class:`agent.providers.base.Provider` and call
:func:`register_provider` before the first LLM request (for example, from your
own entry point)::

    from agent.providers import register_provider
    from agent.providers.base import Provider

    class MyProvider(Provider):
        name = "myprovider"
        def complete(self, messages, *, model, tools=None, temperature=None): ...
        def stream(self, messages, *, model, tools=None, temperature=None): ...

    register_provider("myprovider", MyProvider)
"""

from __future__ import annotations

import threading

from agent.providers.base import LLMResponse, Provider, Usage, make_message
from agent.providers.config import ConfigError, LLMConfig, load_config

_REGISTRY: dict[str, type[Provider]] = {}
_cache: dict[LLMConfig, Provider] = {}
_cache_lock = threading.Lock()


def register_provider(name: str, cls: type[Provider]) -> None:
    """Register a provider class under ``name`` (case-insensitive)."""
    if not (isinstance(cls, type) and issubclass(cls, Provider)):
        raise TypeError(f"{cls!r} is not a Provider subclass")
    _REGISTRY[name.lower()] = cls


def available_providers() -> list[str]:
    return sorted(_REGISTRY)


def get_provider(config: LLMConfig | None = None) -> Provider:
    """Return a provider instance for ``config`` (loaded from the environment by default).

    Instances are cached per configuration so HTTP clients are reused.
    """
    config = config or load_config()
    with _cache_lock:
        provider = _cache.get(config)
        if provider is None:
            provider = _REGISTRY[config.provider](config)
            _cache[config] = provider
        return provider


def clear_provider_cache() -> None:
    with _cache_lock:
        _cache.clear()


def _register_builtins() -> None:
    from agent.providers.azure_openai import AzureOpenAIProvider
    from agent.providers.openai_compatible import OpenAICompatibleProvider

    register_provider("openai", OpenAICompatibleProvider)
    register_provider("azure", AzureOpenAIProvider)


_register_builtins()

__all__ = [
    "ConfigError",
    "LLMConfig",
    "LLMResponse",
    "Provider",
    "Usage",
    "available_providers",
    "clear_provider_cache",
    "get_provider",
    "load_config",
    "make_message",
    "register_provider",
]

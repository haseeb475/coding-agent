"""Provider interface shared by all LLM backends.

The agent keeps its conversation in the OpenAI Chat Completions message format
(``role``/``content``/``tool_calls``/``tool_call_id``) and sends tools as
OpenAI function schemas. A provider adapter receives that format and must
return an ``LLMResponse`` whose ``message`` exposes:

    message.content                          -> str | None
    message.tool_calls                       -> list | None
    message.tool_calls[i].id                 -> str
    message.tool_calls[i].function.name      -> str
    message.tool_calls[i].function.arguments -> str (JSON)

Adapters for APIs with a different wire format must translate in both
directions inside ``complete``/``stream``.
"""

from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Callable, Iterator

from agent.providers.config import LLMConfig

logger = logging.getLogger(__name__)

# Replaced in tests to avoid real sleeps.
sleep: Callable[[float], None] = time.sleep

_TRANSIENT_MARKERS = (
    "429", "500", "502", "503", "504", "timeout", "timed out",
    "connection", "temporarily unavailable", "overloaded",
)


@dataclass
class Usage:
    prompt: int = 0
    completion: int = 0
    total: int = 0
    estimated: bool = False


@dataclass
class LLMResponse:
    message: SimpleNamespace
    usage: Usage | None = None


def make_message(content: str | None, tool_calls: list[dict] | None = None) -> SimpleNamespace:
    """Build a normalized assistant message.

    ``tool_calls`` items are dicts with ``id``, ``name`` and ``arguments`` keys.
    """
    calls = None
    if tool_calls:
        calls = [
            SimpleNamespace(
                id=tc.get("id") or f"call_{i}",
                function=SimpleNamespace(name=tc.get("name", ""), arguments=tc.get("arguments") or ""),
            )
            for i, tc in enumerate(tool_calls)
        ]
    return SimpleNamespace(content=content or None, tool_calls=calls)


def is_transient_error(error: Exception) -> bool:
    """True for errors worth retrying (rate limits, 5xx, timeouts, dropped connections)."""
    try:
        import openai
    except ImportError:  # pragma: no cover - openai is a core dependency
        openai = None

    if openai is not None:
        if isinstance(error, (openai.APIConnectionError, openai.RateLimitError, openai.InternalServerError)):
            return True
        if isinstance(error, openai.APIStatusError):
            return error.status_code == 429 or error.status_code >= 500
    text = str(error).lower()
    return any(marker in text for marker in _TRANSIENT_MARKERS)


def _wait_seconds(attempt: int) -> int:
    """Linear backoff: 5s, 10s, 15s, ..."""
    return (attempt + 1) * 5


def with_retries(fn: Callable[[], LLMResponse], max_attempts: int, label: str = "LLM") -> LLMResponse:
    """Call ``fn`` and retry transient errors with linear backoff."""
    for attempt in range(max_attempts):
        try:
            return fn()
        except Exception as e:
            if not is_transient_error(e) or attempt >= max_attempts - 1:
                raise
            wait = _wait_seconds(attempt)
            logger.warning(
                "[%s] retry %d/%d in %ds after %s: %s",
                label, attempt + 1, max_attempts, wait, type(e).__name__, str(e)[:200],
            )
            sleep(wait)
    raise RuntimeError("unreachable")  # pragma: no cover


def stream_with_retries(
    make_stream: Callable[[], Iterator[tuple]], max_attempts: int, label: str = "LLM stream"
) -> Iterator[tuple]:
    """Retry a streaming call on transient errors, but only before any token was yielded.

    Retrying after partial output would duplicate text in the UI, so failures
    mid-stream are raised to the caller.
    """
    for attempt in range(max_attempts):
        yielded = False
        try:
            for item in make_stream():
                yielded = True
                yield item
            return
        except Exception as e:
            if yielded or not is_transient_error(e) or attempt >= max_attempts - 1:
                raise
            wait = _wait_seconds(attempt)
            logger.warning(
                "[%s] retry %d/%d in %ds after %s: %s",
                label, attempt + 1, max_attempts, wait, type(e).__name__, str(e)[:200],
            )
            sleep(wait)


class Provider(ABC):
    """Base class for LLM provider adapters.

    Subclasses are registered with ``agent.providers.register_provider`` and
    selected through the ``LLM_PROVIDER`` environment variable.
    """

    #: Short name used in LLM_PROVIDER.
    name: str = ""

    def __init__(self, config: LLMConfig):
        self.config = config

    @abstractmethod
    def complete(
        self,
        messages: list[dict],
        *,
        model: str,
        tools: list | None = None,
        temperature: float | None = None,
    ) -> LLMResponse:
        """Blocking chat completion."""

    @abstractmethod
    def stream(
        self,
        messages: list[dict],
        *,
        model: str,
        tools: list | None = None,
        temperature: float | None = None,
    ) -> Iterator[tuple]:
        """Streaming chat completion.

        Yields ``("token", str)`` for each text chunk and finally
        ``("done", LLMResponse)``.
        """

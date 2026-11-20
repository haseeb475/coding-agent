"""Adapter for any server that implements the OpenAI Chat Completions API.

Works with OpenAI itself and with OpenAI-compatible endpoints such as
OpenRouter, Groq, Together, vLLM, Ollama (``/v1``) and LM Studio, provided the
endpoint supports ``/chat/completions``. Native tool calling is used when the
model supports it; otherwise the agent falls back to parsing JSON tool calls
from the response text.
"""

from __future__ import annotations

from typing import Iterator

from openai import OpenAI

from agent.providers.base import (
    LLMResponse,
    Provider,
    Usage,
    make_message,
    stream_with_retries,
    with_retries,
)


def _estimate_tokens(text: str) -> int:
    return len(text) // 4


class OpenAICompatibleProvider(Provider):
    name = "openai"

    def __init__(self, config):
        super().__init__(config)
        self._client = None

    # ── Client ────────────────────────────────────────────────────────────

    def _create_client(self):
        cfg = self.config
        return OpenAI(
            api_key=cfg.api_key,
            base_url=cfg.base_url,  # None -> SDK default (api.openai.com)
            timeout=cfg.timeout,
            default_headers=dict(cfg.extra_headers) or None,
            max_retries=0,  # retries are handled by with_retries()
        )

    @property
    def client(self):
        if self._client is None:
            self._client = self._create_client()
        return self._client

    # ── Requests ──────────────────────────────────────────────────────────

    @staticmethod
    def _request_kwargs(messages, model, tools, temperature) -> dict:
        kwargs: dict = {"model": model, "messages": messages}
        if temperature is not None:
            kwargs["temperature"] = temperature
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        return kwargs

    def complete(self, messages, *, model, tools=None, temperature=None) -> LLMResponse:
        kwargs = self._request_kwargs(messages, model, tools, temperature)

        def call() -> LLMResponse:
            response = self.client.chat.completions.create(**kwargs)
            msg = response.choices[0].message
            tool_calls = None
            if msg.tool_calls:
                tool_calls = [
                    {"id": tc.id, "name": tc.function.name, "arguments": tc.function.arguments}
                    for tc in msg.tool_calls
                ]
            usage = None
            if response.usage:
                usage = Usage(
                    prompt=response.usage.prompt_tokens or 0,
                    completion=response.usage.completion_tokens or 0,
                    total=response.usage.total_tokens or 0,
                )
            return LLMResponse(message=make_message(msg.content, tool_calls), usage=usage)

        return with_retries(call, self.config.max_attempts)

    def stream(self, messages, *, model, tools=None, temperature=None) -> Iterator[tuple]:
        kwargs = self._request_kwargs(messages, model, tools, temperature)
        kwargs["stream"] = True
        kwargs["stream_options"] = {"include_usage": True}

        def run() -> Iterator[tuple]:
            try:
                stream = self.client.chat.completions.create(**kwargs)
            except TypeError:
                # Older SDKs / servers without stream_options support.
                kwargs.pop("stream_options", None)
                stream = self.client.chat.completions.create(**kwargs)

            content_parts: list[str] = []
            tool_calls_acc: dict[int, dict] = {}
            usage: Usage | None = None

            for chunk in stream:
                chunk_usage = getattr(chunk, "usage", None)
                if chunk_usage and (
                    chunk_usage.total_tokens or chunk_usage.prompt_tokens or chunk_usage.completion_tokens
                ):
                    usage = Usage(
                        prompt=chunk_usage.prompt_tokens or 0,
                        completion=chunk_usage.completion_tokens or 0,
                        total=chunk_usage.total_tokens or 0,
                    )
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                if delta.content:
                    content_parts.append(delta.content)
                    yield ("token", delta.content)
                for tc in delta.tool_calls or []:
                    acc = tool_calls_acc.setdefault(tc.index, {"id": "", "name": "", "arguments": ""})
                    if tc.id:
                        acc["id"] = tc.id
                    if tc.function:
                        if tc.function.name:
                            acc["name"] = tc.function.name
                        if tc.function.arguments:
                            acc["arguments"] += tc.function.arguments

            text = "".join(content_parts)
            if usage is None:
                # Some servers never send a usage chunk; fall back to a rough estimate.
                prompt_est = sum(len(str(m.get("content", ""))) for m in messages) // 4
                completion_est = _estimate_tokens(text)
                usage = Usage(prompt_est, completion_est, prompt_est + completion_est, estimated=True)

            tool_calls = [tool_calls_acc[i] for i in sorted(tool_calls_acc)] or None
            yield ("done", LLMResponse(message=make_message(text, tool_calls), usage=usage))

        yield from stream_with_retries(run, self.config.max_attempts)

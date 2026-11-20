"""LLM access layer used by the agent.

The public functions here (``chat``, ``chat_stream``, ``smoke_test`` and the
token counter / context helpers) are provider-independent. The actual API
calls are delegated to the adapter selected by ``LLM_PROVIDER``; see
``agent/providers`` and ``.env.example`` for configuration.
"""

import json
import re
from pathlib import Path

from dotenv import find_dotenv, load_dotenv

from agent.providers import ConfigError, get_provider, load_config
from agent.providers.base import LLMResponse

# Load .env from the current directory (or a parent), then from the repository
# root. Variables already set in the environment always take precedence.
load_dotenv(find_dotenv(usecwd=True))
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

__all__ = [
    "ConfigError",
    "chat",
    "chat_stream",
    "consolidate_system_messages",
    "count_tokens",
    "get_token_usage",
    "reset_token_counter",
    "set_system_section",
    "smoke_test",
    "trim_context",
]

_SECTION_MARKERS = ("## ", "[CONTEXT TRIMMED]")


def _remove_section_by_header(content: str, header: str) -> str:
    """Remove a labeled block from system content (header through next section)."""
    if header not in content:
        return content
    idx = content.index(header)
    before = content[:idx].rstrip()
    remainder = content[idx + len(header) :]
    match = re.search(
        r"\n(?:" + "|".join(re.escape(m) for m in _SECTION_MARKERS) + ")",
        remainder,
    )
    if match:
        after = remainder[match.start() :]
        return (before + after).strip()
    return before


def consolidate_system_messages(messages: list[dict]) -> list[dict]:
    """Merge all system messages into a single message at index 0."""
    system_parts: list[str] = []
    rest: list[dict] = []
    for msg in messages:
        if msg.get("role") == "system":
            part = msg.get("content", "")
            if part:
                system_parts.append(part)
        else:
            rest.append(msg)
    if not system_parts:
        return list(messages)
    return [{"role": "system", "content": "\n\n".join(system_parts)}] + rest


def set_system_section(messages: list[dict], header: str, section: str) -> list[dict]:
    """Replace a labeled section inside the leading system message."""
    messages = consolidate_system_messages(messages)
    if not messages:
        messages = [{"role": "system", "content": ""}]
    elif messages[0].get("role") != "system":
        messages.insert(0, {"role": "system", "content": ""})

    content = _remove_section_by_header(messages[0].get("content", ""), header)
    if section:
        content = f"{content.rstrip()}\n\n{section}".strip()
    messages[0] = {"role": "system", "content": content}
    return messages

_total_tokens = {"prompt": 0, "completion": 0, "total": 0}


def reset_token_counter() -> None:
    """Reset the token counter at the start of a new task."""
    _total_tokens["prompt"] = 0
    _total_tokens["completion"] = 0
    _total_tokens["total"] = 0


def get_token_usage() -> dict:
    """Return accumulated token usage."""
    return dict(_total_tokens)


def count_tokens(messages: list[dict]) -> int:
    """Rough token estimate: 1 token ≈ 4 characters."""
    total = 0
    for m in messages:
        total += len(str(m.get("content", "")))
        if m.get("tool_calls"):
            total += len(str(m["tool_calls"]))
    return total // 4


def trim_context(
    messages: list[dict], max_tokens: int = 50000, keep_recent: int = 24
) -> list[dict]:
    """
    Trim conversation when over token budget.

    Keeps: system prompt, original task, recent messages.
    Dropped messages are summarized into a compact note so the agent
    does not lose critical context.
    """
    if count_tokens(messages) <= max_tokens:
        return messages

    if len(messages) <= 2 + keep_recent:
        return messages

    # Split into: [system, task, ...middle..., ...recent...]
    head = messages[:2]
    middle = messages[2:-keep_recent] if len(messages) > 2 + keep_recent else []
    recent = messages[-keep_recent:]

    # Summarize dropped middle messages into a compact note
    if middle:
        tools_used = []
        files_read = []
        files_edited = []
        errors = []

        for msg in middle:
            content = msg.get("content", "")
            if msg.get("role") == "tool":
                # Extract key info from tool results
                if "Error:" in content:
                    errors.append(content[:100])
            if msg.get("tool_calls"):
                for tc in msg["tool_calls"]:
                    name = tc.get("function", {}).get("name", "")
                    args_str = tc.get("function", {}).get("arguments", "")
                    tools_used.append(name)
                    if name in ("read_file", "view_file_range", "file_outline", "get_function"):
                        try:
                            a = json.loads(args_str)
                            files_read.append(a.get("filepath", ""))
                        except (ValueError, TypeError, AttributeError):
                            pass
                    elif name in ("write_file", "str_replace", "edit_and_verify"):
                        try:
                            a = json.loads(args_str)
                            files_edited.append(a.get("filepath", ""))
                        except (ValueError, TypeError, AttributeError):
                            pass

        summary = "[CONTEXT TRIMMED] Earlier in this conversation:\n"
        if tools_used:
            summary += f"- Tools used: {', '.join(dict.fromkeys(tools_used))}\n"
        if files_read:
            summary += f"- Files read: {', '.join(dict.fromkeys(files_read))}\n"
        if files_edited:
            summary += f"- Files edited: {', '.join(dict.fromkeys(files_edited))}\n"
        if errors:
            summary += f"- Errors encountered: {len(errors)}\n"
        summary += f"- {len(middle)} messages trimmed to save context space.\n"

        head = set_system_section(head, "[CONTEXT TRIMMED]", summary)

    trimmed = head + recent

    # If still over budget, drop oldest recent messages
    while count_tokens(trimmed) > max_tokens and len(trimmed) > 4:
        trimmed = trimmed[:3] + trimmed[4:]

    return trimmed


def _record_usage(response: LLMResponse) -> None:
    usage = response.usage
    if usage is None:
        return
    _total_tokens["prompt"] += usage.prompt
    _total_tokens["completion"] += usage.completion
    _total_tokens["total"] += usage.total


def _select_model(config, use_light: bool) -> str:
    if use_light and config.model_light:
        return config.model_light
    return config.model


def chat(
    messages: list[dict],
    tools: list | None = None,
    use_light: bool = False,
    temperature: float | None = None,
):
    """
    Send a blocking chat completion and return the assistant message.

    Transient errors (rate limits, 5xx, timeouts) are retried up to
    ``LLM_MAX_ATTEMPTS`` times with linear backoff (5s, 10s, ...).

    ``use_light`` routes the call to ``LLM_MODEL_LIGHT`` when it is set.
    ``temperature`` is passed through when provided; a low value (e.g. 0.0)
    reduces run-to-run variance for editing/fixing steps.

    Raises ``ConfigError`` when the configuration is missing or invalid.
    """
    config = load_config()
    provider = get_provider(config)
    messages = consolidate_system_messages(messages)
    response = provider.complete(
        messages,
        model=_select_model(config, use_light),
        tools=tools,
        temperature=temperature,
    )
    _record_usage(response)
    return response.message


def chat_stream(
    messages: list[dict],
    tools: list | None = None,
    use_light: bool = False,
    temperature: float | None = None,
):
    """
    Streaming chat used by the UI and CLI. Yields ``('token', str)`` chunks,
    then ``('done', message)``. Benchmarks use the blocking ``chat()``.
    """
    config = load_config()
    provider = get_provider(config)
    messages = consolidate_system_messages(messages)
    for kind, payload in provider.stream(
        messages,
        model=_select_model(config, use_light),
        tools=tools,
        temperature=temperature,
    ):
        if kind == "done":
            _record_usage(payload)
            yield ("done", payload.message)
        else:
            yield (kind, payload)


def smoke_test() -> str:
    """Send a simple request to verify the LLM connection."""
    message = chat(
        [{"role": "user", "content": "Reply with exactly: connection ok"}]
    )
    return message.content or ""


if __name__ == "__main__":
    print(smoke_test())

"""Provider adapters exercised through the real openai SDK against a local fake server."""

import openai
import pytest

from agent import llm
from agent.providers import available_providers, get_provider, load_config, register_provider
from agent.providers.base import LLMResponse, Provider, is_transient_error, make_message


def test_chat_against_openai_compatible_server(server):
    llm.reset_token_counter()
    message = llm.chat([{"role": "system", "content": "s"}, {"role": "user", "content": "hi"}])
    assert message.content == "connection ok"
    assert message.tool_calls is None
    req = server.requests[-1]
    assert req["body"]["model"] == "test-model"
    assert req["headers"]["authorization"] == "Bearer test-key"
    assert llm.get_token_usage() == {"prompt": 11, "completion": 5, "total": 16}


def test_smoke_test(server):
    assert llm.smoke_test() == "connection ok"


def test_tool_calls_and_temperature_passthrough(server):
    server.script.append({"content": None, "tool_calls": [{"name": "read_file", "arguments": {"filepath": "a.py"}}]})
    tools = [{"type": "function", "function": {"name": "read_file", "parameters": {"type": "object"}}}]
    message = llm.chat([{"role": "user", "content": "read"}], tools=tools, temperature=0.0)
    assert message.tool_calls[0].function.name == "read_file"
    assert message.tool_calls[0].function.arguments == '{"filepath": "a.py"}'
    body = server.requests[-1]["body"]
    assert body["temperature"] == 0.0
    assert body["tool_choice"] == "auto"


def test_stream_tokens_and_tool_call_deltas(server):
    server.script.append({"content": "Hello world", "tool_calls": [{"name": "list_files", "arguments": {"x": 1}}]})
    llm.reset_token_counter()
    events = list(llm.chat_stream([{"role": "user", "content": "go"}], tools=[]))
    tokens = "".join(payload for kind, payload in events if kind == "token")
    kind, message = events[-1]
    assert kind == "done"
    assert tokens == "Hello world" == message.content
    assert message.tool_calls[0].function.name == "list_files"
    assert message.tool_calls[0].function.arguments == '{"x": 1}'
    assert llm.get_token_usage()["total"] == 10
    assert server.requests[-1]["body"]["stream"] is True


def test_light_model_routing(server, monkeypatch):
    llm.chat([{"role": "user", "content": "x"}], use_light=True)
    assert server.requests[-1]["body"]["model"] == "test-model"  # unset -> main model
    monkeypatch.setenv("LLM_MODEL_LIGHT", "small-model")
    llm.chat([{"role": "user", "content": "x"}], use_light=True)
    assert server.requests[-1]["body"]["model"] == "small-model"
    llm.chat([{"role": "user", "content": "x"}])
    assert server.requests[-1]["body"]["model"] == "test-model"


def test_extra_headers_are_sent(server, monkeypatch):
    monkeypatch.setenv("LLM_EXTRA_HEADERS", '{"X-Title": "coding-agent"}')
    llm.chat([{"role": "user", "content": "x"}])
    assert server.requests[-1]["headers"]["x-title"] == "coding-agent"


def test_invalid_key_raises_without_retry(server, monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "wrong")
    with pytest.raises(openai.AuthenticationError):
        llm.chat([{"role": "user", "content": "x"}])
    assert len(server.requests) == 1


def test_transient_errors_are_retried(server):
    server.script.extend([503, 429, {"content": "recovered"}])
    assert llm.chat([{"role": "user", "content": "x"}]).content == "recovered"
    assert len(server.requests) == 3


def test_retries_exhausted(server, monkeypatch):
    monkeypatch.setenv("LLM_MAX_ATTEMPTS", "2")
    server.script.extend([500, 500, {"content": "never"}])
    with pytest.raises(openai.InternalServerError):
        llm.chat([{"role": "user", "content": "x"}])
    assert len(server.requests) == 2


def test_stream_retry_before_first_token(server):
    server.script.extend([502, {"content": "ok"}])
    events = list(llm.chat_stream([{"role": "user", "content": "x"}]))
    assert events[-1][1].content == "ok"
    assert len(server.requests) == 2


def test_missing_config_raises_config_error():
    with pytest.raises(llm.ConfigError):
        llm.chat([{"role": "user", "content": "x"}])


def test_azure_adapter_wire_format(fake_server, monkeypatch):
    fake_server.reset()
    monkeypatch.setenv("LLM_PROVIDER", "azure")
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("LLM_MODEL", "my-deployment")
    monkeypatch.setenv("LLM_BASE_URL", fake_server.root_url)
    monkeypatch.setenv("AZURE_OPENAI_API_VERSION", "2024-10-21")
    assert llm.chat([{"role": "user", "content": "x"}]).content == "connection ok"
    req = fake_server.requests[-1]
    assert req["flavor"] == "azure"
    assert req["deployment"] == "my-deployment"
    assert req["query"]["api-version"] == "2024-10-21"
    assert req["headers"]["api-key"] == "test-key"
    events = list(llm.chat_stream([{"role": "user", "content": "x"}]))
    assert events[-1][1].content == "connection ok"


def test_is_transient_error_classification():
    assert is_transient_error(TimeoutError("Request timed out"))
    assert is_transient_error(ConnectionError("connection reset"))
    assert not is_transient_error(ValueError("bad request"))


def test_register_custom_provider(monkeypatch):
    import agent.providers as providers

    # Keep the registration local to this test.
    monkeypatch.setattr(providers, "_REGISTRY", dict(providers._REGISTRY))
    calls = []

    class EchoProvider(Provider):
        name = "echo"

        def complete(self, messages, *, model, tools=None, temperature=None):
            calls.append(model)
            return LLMResponse(message=make_message("echo: " + messages[-1]["content"]))

        def stream(self, messages, *, model, tools=None, temperature=None):
            yield ("token", "echo")
            yield ("done", LLMResponse(message=make_message("echo")))

    register_provider("echo", EchoProvider)
    assert "echo" in available_providers()
    monkeypatch.setenv("LLM_PROVIDER", "echo")
    monkeypatch.setenv("LLM_API_KEY", "unused")
    monkeypatch.setenv("LLM_MODEL", "m")
    assert llm.chat([{"role": "user", "content": "hi"}]).content == "echo: hi"
    assert calls == ["m"]
    assert isinstance(get_provider(load_config()), EchoProvider)

    with pytest.raises(TypeError):
        register_provider("bad", object)

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.providers import base, clear_provider_cache  # noqa: E402
from tests.fake_openai_server import VALID_KEY, FakeServer  # noqa: E402

_LLM_ENV_VARS = (
    "LLM_PROVIDER", "LLM_API_KEY", "LLM_MODEL", "LLM_MODEL_LIGHT", "LLM_BASE_URL",
    "LLM_TIMEOUT", "LLM_MAX_ATTEMPTS", "LLM_EXTRA_HEADERS",
    "OPENAI_API_KEY", "AZURE_OPENAI_API_KEY", "AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_API_VERSION",
    "ALLOWED_WORKSPACE_ROOTS", "CODING_AGENT_HOST", "CODING_AGENT_ALLOWED_HOSTS",
)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """Isolate every test from the developer's shell / .env configuration."""
    for name in _LLM_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(base, "sleep", lambda seconds: None)
    clear_provider_cache()
    yield
    clear_provider_cache()


@pytest.fixture(scope="session")
def fake_server():
    server = FakeServer()
    server.start()
    yield server
    server.stop()


@pytest.fixture
def server(fake_server, monkeypatch):
    """Fake server with the environment pointing at it (OpenAI-compatible mode)."""
    fake_server.reset()
    monkeypatch.setenv("LLM_API_KEY", VALID_KEY)
    monkeypatch.setenv("LLM_MODEL", "test-model")
    monkeypatch.setenv("LLM_BASE_URL", fake_server.base_url)
    monkeypatch.setenv("LLM_TIMEOUT", "10")
    return fake_server

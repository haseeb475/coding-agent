import pytest

from agent.providers import ConfigError, load_config


def test_missing_api_key_names_the_variable():
    with pytest.raises(ConfigError, match="LLM_API_KEY"):
        load_config({"LLM_MODEL": "m"})


def test_missing_model():
    with pytest.raises(ConfigError, match="LLM_MODEL"):
        load_config({"LLM_API_KEY": "k"})


def test_unknown_provider_lists_supported():
    with pytest.raises(ConfigError, match="azure, openai"):
        load_config({"LLM_PROVIDER": "nope", "LLM_API_KEY": "k", "LLM_MODEL": "m"})


@pytest.mark.parametrize("name,value", [
    ("LLM_TIMEOUT", "abc"), ("LLM_TIMEOUT", "0"),
    ("LLM_MAX_ATTEMPTS", "1.5"), ("LLM_MAX_ATTEMPTS", "0"),
])
def test_invalid_numbers(name, value):
    with pytest.raises(ConfigError, match=name):
        load_config({"LLM_API_KEY": "k", "LLM_MODEL": "m", name: value})


def test_invalid_extra_headers():
    with pytest.raises(ConfigError, match="LLM_EXTRA_HEADERS"):
        load_config({"LLM_API_KEY": "k", "LLM_MODEL": "m", "LLM_EXTRA_HEADERS": "[1, 2]"})


def test_defaults():
    cfg = load_config({"LLM_API_KEY": "k", "LLM_MODEL": "m"})
    assert cfg.provider == "openai"
    assert cfg.base_url is None
    assert cfg.timeout == 600.0
    assert cfg.max_attempts == 3
    assert cfg.model_light is None


def test_openai_key_fallback_and_blank_values():
    cfg = load_config({"LLM_API_KEY": "  ", "OPENAI_API_KEY": "sk-fallback", "LLM_MODEL": "m",
                       "LLM_MODEL_LIGHT": ""})
    assert cfg.api_key == "sk-fallback"
    assert cfg.model_light is None


def test_azure_requires_endpoint_and_version():
    base = {"LLM_PROVIDER": "azure", "LLM_API_KEY": "k", "LLM_MODEL": "deploy"}
    with pytest.raises(ConfigError, match="LLM_BASE_URL"):
        load_config(base)
    with pytest.raises(ConfigError, match="AZURE_OPENAI_API_VERSION"):
        load_config({**base, "LLM_BASE_URL": "https://x.openai.azure.com"})
    cfg = load_config({**base, "AZURE_OPENAI_ENDPOINT": "https://x.openai.azure.com",
                       "AZURE_OPENAI_API_VERSION": "2024-10-21"})
    assert cfg.base_url == "https://x.openai.azure.com"


def test_azure_key_fallback():
    cfg = load_config({"LLM_PROVIDER": "azure", "AZURE_OPENAI_API_KEY": "az", "LLM_MODEL": "d",
                       "LLM_BASE_URL": "https://x", "AZURE_OPENAI_API_VERSION": "v"})
    assert cfg.api_key == "az"


def test_describe_never_contains_key():
    cfg = load_config({"LLM_API_KEY": "super-secret", "LLM_MODEL": "m"})
    assert "super-secret" not in cfg.describe()
    assert "super-secret" not in repr(cfg)

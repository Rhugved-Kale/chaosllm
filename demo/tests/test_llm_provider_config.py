"""Provider-configurable LLM client: env parsing, per-provider request/
response shape, and fail-fast startup when the configured provider's key
is missing.

Root cause this covers (found running the demo for real against docker
compose with an Anthropic key): the app was hardcoded to OpenAI's endpoint
and never sent any auth header at all, so it 401'd regardless of which key
was actually configured.
"""

from __future__ import annotations

import pytest

from demo.llm_client import (
    LLMConfigError,
    LLMUnavailableError,
    ProviderConfig,
    load_provider_config,
)
from demo.main import app


def test_defaults_to_openai_and_requires_its_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(LLMConfigError, match="OPENAI_API_KEY"):
        load_provider_config()


def test_openai_config_when_key_present(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("OPENAI_MODEL", raising=False)

    config = load_provider_config()

    assert config.provider == "openai"
    assert config.path == "/openai/v1/chat/completions"
    assert config.model == "gpt-4o-mini"
    assert config.request_headers() == {"authorization": "Bearer sk-test"}


def test_anthropic_config_when_key_present(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)

    config = load_provider_config()

    assert config.provider == "anthropic"
    assert config.path == "/anthropic/v1/messages"
    assert config.model == "claude-haiku-4-5"
    assert config.request_headers() == {
        "x-api-key": "sk-ant-test",
        "anthropic-version": "2023-06-01",
    }


def test_anthropic_missing_key_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(LLMConfigError, match="ANTHROPIC_API_KEY"):
        load_provider_config()


def test_unknown_provider_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "bogus")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    with pytest.raises(LLMConfigError, match="bogus"):
        load_provider_config()


def test_provider_env_var_is_case_insensitive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "OpenAI")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    assert load_provider_config().provider == "openai"


def test_openai_request_body_shape() -> None:
    config = ProviderConfig(
        provider="openai", path="/openai/v1/chat/completions", model="gpt-4o-mini", api_key="k"
    )
    body = config.request_body("what is water?", "water is wet")
    assert body["model"] == "gpt-4o-mini"
    assert body["messages"][0]["role"] == "system"
    assert body["messages"][1] == {"role": "user", "content": "what is water?"}


def test_openai_extract_text() -> None:
    config = ProviderConfig(provider="openai", path="p", model="m", api_key="k")
    text = config.extract_text({"choices": [{"message": {"content": "hello"}}]})
    assert text == "hello"


def test_anthropic_request_body_shape() -> None:
    config = ProviderConfig(
        provider="anthropic", path="/anthropic/v1/messages", model="claude-haiku-4-5", api_key="k"
    )
    body = config.request_body("what is water?", "water is wet")
    assert body["model"] == "claude-haiku-4-5"
    assert body["max_tokens"] > 0
    assert "water is wet" in body["system"]
    # Anthropic takes the system prompt as a top-level field, not a message.
    assert body["messages"] == [{"role": "user", "content": "what is water?"}]


def test_anthropic_extract_text() -> None:
    config = ProviderConfig(provider="anthropic", path="p", model="m", api_key="k")
    text = config.extract_text({"content": [{"type": "text", "text": "hello"}]})
    assert text == "hello"


def test_extract_text_raises_on_malformed_body() -> None:
    config = ProviderConfig(provider="openai", path="p", model="m", api_key="k")
    with pytest.raises(LLMUnavailableError):
        config.extract_text({"choices": []})


async def test_app_fails_to_start_without_a_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(LLMConfigError, match="OPENAI_API_KEY"):
        async with app.router.lifespan_context(app):
            pass


async def test_app_starts_with_anthropic_key_and_no_openai_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    async with app.router.lifespan_context(app):
        assert app.state.provider_config.provider == "anthropic"

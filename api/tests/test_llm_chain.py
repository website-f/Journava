"""LLM chain resolution.

The env-based chain used to pass `api_key: None`, relying on LiteLLM finding the
key in the process environment. Pydantic settings read `.env` into the Settings
object *without* exporting it, so a correctly configured key produced "missing
credentials" on every model in local dev — and worked in Docker, where compose's
`env_file` sets real env vars. That asymmetry is what made it hard to spot.
"""

from __future__ import annotations

import pytest

from app.core import llm


@pytest.fixture
def env_chain(monkeypatch: pytest.MonkeyPatch):
    """Force the env-based path by making the DB chain unavailable."""

    async def no_db_chain():
        return []

    monkeypatch.setattr("app.core.llm_providers.get_chain", no_db_chain)


async def test_env_chain_attaches_configured_keys(monkeypatch, env_chain):
    monkeypatch.setattr(llm.settings, "llm_primary_model", "dashscope/qwen-plus")
    monkeypatch.setattr(llm.settings, "llm_fallback_models", "groq/llama-3.3-70b-versatile")
    monkeypatch.setattr(llm.settings, "dashscope_api_key", "sk-dash")
    monkeypatch.setattr(llm.settings, "groq_api_key", "gsk-groq")

    chain = await llm._build_chain()

    assert [c["model"] for c in chain] == [
        "dashscope/qwen-plus",
        "groq/llama-3.3-70b-versatile",
    ]
    assert chain[0]["api_key"] == "sk-dash"
    assert chain[1]["api_key"] == "gsk-groq"


async def test_keyless_cloud_model_is_dropped_from_the_chain(monkeypatch, env_chain):
    """A cloud model with no key is not worth dialling.

    Attempting it costs a full round trip and always returns "missing
    credentials". With three unconfigured providers and a 30s timeout, that alone
    turned an unconfigured install into a ~90-second wait before it fell back —
    so a model without a usable key is filtered out rather than tried.
    """
    monkeypatch.setattr(llm.settings, "llm_primary_model", "gemini/gemini-2.0-flash")
    monkeypatch.setattr(llm.settings, "llm_fallback_models", "")
    monkeypatch.setattr(llm.settings, "gemini_api_key", "")

    assert await llm._build_chain() == []


async def test_local_models_survive_without_a_key(monkeypatch, env_chain):
    """Ollama and friends legitimately need no credential."""
    monkeypatch.setattr(llm.settings, "llm_primary_model", "ollama/llama3.2")
    monkeypatch.setattr(llm.settings, "llm_fallback_models", "")

    chain = await llm._build_chain()
    assert len(chain) == 1
    assert chain[0]["model"] == "ollama/llama3.2"
    assert chain[0]["api_key"] is None


async def test_only_the_keyed_models_are_kept(monkeypatch, env_chain):
    monkeypatch.setattr(llm.settings, "llm_primary_model", "dashscope/qwen-plus")
    monkeypatch.setattr(
        llm.settings, "llm_fallback_models", "gemini/gemini-2.0-flash,groq/llama-3.3-70b-versatile"
    )
    monkeypatch.setattr(llm.settings, "dashscope_api_key", "")
    monkeypatch.setattr(llm.settings, "gemini_api_key", "")
    monkeypatch.setattr(llm.settings, "groq_api_key", "gsk-real")

    chain = await llm._build_chain()
    assert [entry["model"] for entry in chain] == ["groq/llama-3.3-70b-versatile"]


async def test_db_chain_wins_over_env(monkeypatch):
    async def db_chain():
        return [{"id": "uuid-1", "litellm_model": "openrouter/free-model", "api_key": "or-key"}]

    monkeypatch.setattr("app.core.llm_providers.get_chain", db_chain)
    chain = await llm._build_chain()

    assert len(chain) == 1
    assert chain[0]["model"] == "openrouter/free-model"
    assert chain[0]["provider_id"] == "uuid-1"


def test_unknown_provider_prefix_has_no_key(monkeypatch):
    assert llm._settings_key_for("someprovider/some-model") is None


async def test_no_providers_configured_raises(monkeypatch, env_chain):
    monkeypatch.setattr(llm.settings, "llm_primary_model", "")
    monkeypatch.setattr(llm.settings, "llm_fallback_models", "")

    with pytest.raises(llm.LLMUnavailableError, match="No LLM providers configured"):
        await llm.complete([{"role": "user", "content": "hi"}])

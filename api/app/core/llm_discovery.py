"""Live model discovery — ask the provider what it actually offers.

A hardcoded preset list is wrong the moment a provider retires a model, and it
fails in the most confusing possible way: the key is valid, the request is
well-formed, and the provider answers `model_not_found`. That is what happened
with Groq's Llama models, decommissioned on 2026-08-16 while our presets still
offered them.

So the presets are a starting point, and this module is the source of truth: given
a provider and a key, it lists the models that provider will serve **right now**.
Almost every provider exposes an OpenAI-compatible `/v1/models`; the exceptions
(Gemini, Ollama) get their own reader.

Chat models only. A `/models` listing includes embeddings, speech and moderation
endpoints that would fail as a chat completion, so those are filtered out rather
than offered to the operator as valid choices.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

TIMEOUT = httpx.Timeout(20.0, connect=8.0)


class DiscoveryError(RuntimeError):
    """The provider could not be listed — carries a UI-safe reason."""


#: provider slug → (models URL, LiteLLM prefix). Bearer auth unless noted.
_OPENAI_COMPATIBLE: dict[str, tuple[str, str]] = {
    "groq": ("https://api.groq.com/openai/v1/models", "groq"),
    "openai": ("https://api.openai.com/v1/models", "openai"),
    "deepseek": ("https://api.deepseek.com/models", "deepseek"),
    "mistral": ("https://api.mistral.ai/v1/models", "mistral"),
    "cerebras": ("https://api.cerebras.ai/v1/models", "cerebras"),
    "openrouter": ("https://openrouter.ai/api/v1/models", "openrouter"),
    "dashscope": (
        "https://dashscope-intl.aliyuncs.com/compatible-mode/v1/models",
        "dashscope",
    ),
    "xai": ("https://api.x.ai/v1/models", "xai"),
    "together": ("https://api.together.xyz/v1/models", "together_ai"),
    "fireworks": ("https://api.fireworks.ai/inference/v1/models", "fireworks_ai"),
}

#: Substrings that mark a non-chat model. Offering these would produce a
#: confusing failure at call time rather than at selection time.
_NON_CHAT_MARKERS = (
    "whisper", "tts", "embed", "embedding", "rerank", "moderation",
    "guard", "orpheus", "stable-diffusion", "dall-e", "flux", "sora",
    "distil-whisper", "audio", "speech", "transcribe", "image",
    "prompt-guard", "safeguard", "vision-encoder",
)


def _is_chat_model(model_id: str) -> bool:
    lowered = model_id.lower()
    return not any(marker in lowered for marker in _NON_CHAT_MARKERS)


async def list_models(provider: str, api_key: str | None) -> list[dict[str, Any]]:
    """Models the provider will serve right now, newest-looking first.

    Raises `DiscoveryError` with an actionable message; never returns a partial
    list silently.
    """
    provider = provider.lower().strip()

    if provider == "gemini":
        return await _gemini(api_key)
    if provider == "ollama":
        return await _ollama()
    if provider == "anthropic":
        return await _anthropic(api_key)
    if provider in _OPENAI_COMPATIBLE:
        url, prefix = _OPENAI_COMPATIBLE[provider]
        return await _openai_compatible(provider, url, prefix, api_key)

    raise DiscoveryError(
        f"Journava does not know how to list models for '{provider}'. "
        "Enter the model name manually — any OpenAI-compatible id works."
    )


async def _get(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    params: dict[str, Any] | None = None,
) -> Any:
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            response = await client.get(url, headers=headers, params=params)
    except httpx.TimeoutException as exc:
        raise DiscoveryError("The provider took too long to answer.") from exc
    except Exception as exc:  # noqa: BLE001
        raise DiscoveryError(f"Could not reach the provider: {exc}") from exc

    if response.status_code in (401, 403):
        raise DiscoveryError("The provider rejected this key.")
    if response.status_code == 429:
        raise DiscoveryError("Rate-limited while listing models — try again shortly.")
    if response.status_code >= 400:
        raise DiscoveryError(
            f"Provider returned {response.status_code}: {response.text[:160]}"
        )
    try:
        return response.json()
    except ValueError as exc:
        raise DiscoveryError("The provider's model list was not valid JSON.") from exc


async def _openai_compatible(
    provider: str,
    url: str,
    prefix: str,
    api_key: str | None,
) -> list[dict[str, Any]]:
    # OpenRouter lists publicly; everything else needs the key.
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    if not api_key and provider != "openrouter":
        raise DiscoveryError("A key is needed to list this provider's models.")

    payload = await _get(url, headers=headers)
    entries = payload.get("data") if isinstance(payload, dict) else payload
    if not isinstance(entries, list):
        raise DiscoveryError("Unexpected model list shape from the provider.")

    models: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        model_id = str(entry.get("id") or entry.get("name") or "").strip()
        if not model_id or not _is_chat_model(model_id):
            continue
        models.append({
            "value": f"{prefix}/{model_id}",
            "label": entry.get("name") or model_id,
            "id": model_id,
            "context": (
                entry.get("context_length")
                or entry.get("context_window")
                or (entry.get("top_provider") or {}).get("context_length")
            ),
            "free": ":free" in model_id,
            "owned_by": entry.get("owned_by"),
        })
    return _sorted(models)


async def _gemini(api_key: str | None) -> list[dict[str, Any]]:
    if not api_key:
        raise DiscoveryError("A key is needed to list Gemini models.")
    payload = await _get(
        "https://generativelanguage.googleapis.com/v1beta/models",
        params={"key": api_key, "pageSize": 200},
    )
    models: list[dict[str, Any]] = []
    for entry in payload.get("models", []):
        # Only models that can actually answer a chat turn.
        if "generateContent" not in (entry.get("supportedGenerationMethods") or []):
            continue
        raw = str(entry.get("name", ""))
        model_id = raw.removeprefix("models/")
        if not model_id or not _is_chat_model(model_id):
            continue
        models.append({
            "value": f"gemini/{model_id}",
            "label": entry.get("displayName") or model_id,
            "id": model_id,
            "context": entry.get("inputTokenLimit"),
            "free": False,
            "owned_by": "google",
        })
    return _sorted(models)


async def _anthropic(api_key: str | None) -> list[dict[str, Any]]:
    if not api_key:
        raise DiscoveryError("A key is needed to list Anthropic models.")
    payload = await _get(
        "https://api.anthropic.com/v1/models",
        headers={"x-api-key": api_key, "anthropic-version": "2023-06-01"},
    )
    models = [
        {
            "value": f"anthropic/{entry['id']}",
            "label": entry.get("display_name") or entry["id"],
            "id": entry["id"],
            "context": None,
            "free": False,
            "owned_by": "anthropic",
        }
        for entry in payload.get("data", [])
        if entry.get("id")
    ]
    return _sorted(models)


async def _ollama() -> list[dict[str, Any]]:
    """Locally installed models. No key; the server must be running."""
    from app.core.settings import settings

    payload = await _get(f"http://{settings.ollama_host}:{settings.ollama_port}/api/tags")
    models = [
        {
            "value": f"ollama/{entry['name']}",
            "label": entry["name"],
            "id": entry["name"],
            "context": None,
            "free": True,
            "owned_by": "local",
        }
        for entry in payload.get("models", [])
        if entry.get("name")
    ]
    if not models:
        raise DiscoveryError(
            "Ollama is running but has no models pulled. Try `ollama pull llama3.2`."
        )
    return _sorted(models)


def _sorted(models: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Newest-looking and largest-context first, de-duplicated.

    Providers return `/models` in arbitrary order, and the operator almost always
    wants a current flagship rather than whatever happens to be alphabetically
    first.
    """
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for model in models:
        if model["value"] in seen:
            continue
        seen.add(model["value"])
        unique.append(model)

    def rank(model: dict[str, Any]) -> tuple[int, int, str]:
        model_id = str(model["id"]).lower()
        # Free variants and obvious flagships float up; dated snapshots sink.
        flagship = any(word in model_id for word in ("plus", "max", "pro", "large", "120b"))
        dated = any(char.isdigit() for char in model_id[-4:]) and "-20" in model_id
        return (
            0 if flagship and not dated else (2 if dated else 1),
            -int(model.get("context") or 0),
            model_id,
        )

    return sorted(unique, key=rank)

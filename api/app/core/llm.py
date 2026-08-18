"""LiteLLM gateway — swap models without touching agent code (spec section 6).

Phase 3: reads the failover chain from the `llm_providers` database table first.
If the DB is empty or unavailable, falls back to the env-based chain in settings.

On rate-limit errors (429), skips to the next provider automatically.
Every call is logged to `llm_usage` for the Engine stats dashboard.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from app.core.settings import settings

logger = logging.getLogger(__name__)

Message = dict[str, str]


class LLMUnavailableError(RuntimeError):
    """Raised when the primary model and every fallback failed."""


#: When the local fallback last refused a connection. A plan fans out to many
#: agents at once, and re-dialling a model that is not running for each of them
#: adds latency for no chance of success — so a failure is remembered briefly.
_ollama_down_until: float = 0.0
_OLLAMA_COOLDOWN_SECONDS = 60.0


async def _ollama_worth_trying() -> bool:
    """True when the local model server is enabled, un-cooled, and listening.

    The port check matters: calling an absent Ollama through LiteLLM costs ~9
    seconds, because it fetches model info and retries before giving up. A TCP
    connect answers the same question in milliseconds.
    """
    if not settings.ollama_fallback_enabled:
        return False
    if time.monotonic() < _ollama_down_until:
        return False
    if not await _port_open(settings.ollama_host, settings.ollama_port):
        _note_ollama_down()
        return False
    return True


async def _port_open(host: str, port: int, timeout: float = 0.4) -> bool:
    """Cheap reachability probe — never raises."""
    import asyncio
    import contextlib

    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=timeout
        )
    except Exception:  # noqa: BLE001
        return False
    writer.close()
    with contextlib.suppress(Exception):
        await writer.wait_closed()
    del reader
    return True


def _note_ollama_down() -> None:
    global _ollama_down_until  # noqa: PLW0603
    _ollama_down_until = time.monotonic() + _OLLAMA_COOLDOWN_SECONDS


async def complete(
    messages: list[Message],
    *,
    model: str | None = None,
    temperature: float | None = None,
    response_format: dict[str, Any] | None = None,
    agent: str | None = None,
) -> str:
    """Run a chat completion, walking the fallback chain on failure.

    Chain resolution order:
    1. Explicit `model` parameter (overrides everything)
    2. DB-based provider chain (llm_providers table, sorted by priority)
    3. Env-based fallback (settings.llm_primary_model + fallback_model_list)
    """
    try:
        from litellm import acompletion
    except ImportError as exc:  # pragma: no cover - dependency guard
        raise LLMUnavailableError("litellm is not installed") from exc

    # If an explicit model is passed, use it alone (for test calls, etc.)
    if model:
        return await _call_single(
            acompletion,
            model,
            None,
            messages,
            temperature,
            response_format,
            agent,
        )

    # Build the candidate chain
    candidates = await _build_chain()
    if not candidates:
        # Nothing usable. Try the local fallback once, then fail fast — this is
        # what keeps an unconfigured install responsive instead of grinding
        # through provider timeouts on every single agent.
        if await _ollama_worth_trying():
            try:
                content = await _call_single(
                    acompletion,
                    settings.ollama_fallback_model,
                    None,
                    messages,
                    temperature,
                    response_format,
                    agent,
                )
                if content:
                    return content
            except LLMUnavailableError as exc:
                _note_ollama_down()
                logger.debug("Ollama fallback unavailable: %s", exc)
        raise LLMUnavailableError(
            "No LLM providers configured. Add a model in Engine, or set a key in .env."
        )

    last_error: Exception | None = None

    for candidate in candidates:
        litellm_model = candidate["model"]
        provider_id = candidate.get("provider_id")
        api_key = candidate.get("api_key")

        # Set provider-specific env var so LiteLLM always finds the key
        _set_provider_env(litellm_model, api_key)

        start = time.monotonic()
        try:
            response = await acompletion(
                model=litellm_model,
                messages=messages,
                temperature=(settings.llm_temperature if temperature is None else temperature),
                timeout=settings.llm_timeout_seconds,
                response_format=response_format,
                api_key=api_key,
                # We own the failover, so LiteLLM must not retry underneath us —
                # its retries would multiply the wait before the next candidate.
                num_retries=0,
            )
            elapsed = int((time.monotonic() - start) * 1000)
            content = response.choices[0].message.content or ""

            usage = getattr(response, "usage", None)
            await _log_usage(
                provider_id=provider_id,
                model=litellm_model,
                agent=agent,
                tokens_in=getattr(usage, "prompt_tokens", 0) or 0,
                tokens_out=getattr(usage, "completion_tokens", 0) or 0,
                latency_ms=elapsed,
                success=True,
            )
            await _mark(provider_id, "healthy", None)
            return content

        except Exception as exc:  # noqa: BLE001
            last_error = exc
            elapsed = int((time.monotonic() - start) * 1000)
            err_msg = str(exc)[:500]

            await _log_usage(
                provider_id=provider_id,
                model=litellm_model,
                agent=agent,
                latency_ms=elapsed,
                success=False,
                error_msg=err_msg,
            )

            # Classify so the pool learns: a wrong key should stop being tried,
            # a rate-limited one should be rested, and a flaky one retried.
            status, cooldown = _classify_failure(exc)
            await _mark(provider_id, status, err_msg, cooldown=cooldown)

            if status == "rate_limited":
                logger.warning("LLM %s rate-limited — rotating", litellm_model)
            elif status == "invalid":
                logger.warning("LLM %s rejected the key — skipping it", litellm_model)
            else:
                logger.warning("LLM %s failed: %s", litellm_model, exc)

    # Cloud pool exhausted → local Ollama, which needs no key. Tried last and
    # only once, so a machine without Ollama fails fast instead of hanging.
    if await _ollama_worth_trying():
        try:
            logger.info("Cloud providers exhausted — trying local Ollama")
            content = await _call_single(
                acompletion,
                settings.ollama_fallback_model,
                None,
                messages,
                temperature,
                response_format,
                agent,
            )
            if content:
                return content
        except LLMUnavailableError as exc:
            _note_ollama_down()
            logger.info("Ollama fallback unavailable: %s", exc)
            last_error = exc

    raise LLMUnavailableError(
        f"All models failed ({len(candidates)} providers tried)"
    ) from last_error


# --------------------------------------------------------------------------- #
# Internal helpers
# --------------------------------------------------------------------------- #


async def _call_single(
    acompletion: Any,
    model: str,
    api_key: str | None,
    messages: list[Message],
    temperature: float | None,
    response_format: dict[str, Any] | None,
    agent: str | None,
) -> str:
    """Call a single model (used for test calls and explicit model overrides).

    Logs usage like the chain path does — the latency was already being measured
    here and then thrown away, so explicit-model calls were invisible in the
    Engine stats dashboard.
    """
    start = time.monotonic()
    try:
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": settings.llm_temperature if temperature is None else temperature,
            "timeout": settings.llm_timeout_seconds,
            "num_retries": 0,
        }
        if response_format:
            kwargs["response_format"] = response_format
        if api_key:
            kwargs["api_key"] = api_key

        response = await acompletion(**kwargs)
        elapsed = int((time.monotonic() - start) * 1000)
        usage = getattr(response, "usage", None)
        await _log_usage(
            provider_id=None,
            model=model,
            agent=agent,
            tokens_in=getattr(usage, "prompt_tokens", 0) or 0,
            tokens_out=getattr(usage, "completion_tokens", 0) or 0,
            latency_ms=elapsed,
            success=True,
        )
        return response.choices[0].message.content or ""
    except Exception as exc:
        await _log_usage(
            provider_id=None,
            model=model,
            agent=agent,
            latency_ms=int((time.monotonic() - start) * 1000),
            success=False,
            error_msg=str(exc)[:500],
        )
        raise LLMUnavailableError(f"Model {model} failed: {exc}") from exc


async def _build_chain() -> list[dict[str, Any]]:
    """Build the ordered list of models to try.

    Returns a list of dicts with keys: model, provider_id, api_key.
    DB providers first, then env-based fallback.
    """
    # Try DB-based chain
    try:
        from app.core.llm_providers import get_chain

        db_providers = await get_chain()
        if db_providers:
            return [
                {
                    "model": p["litellm_model"],
                    "provider_id": str(p["id"]),
                    "api_key": p.get("api_key"),
                }
                for p in db_providers
            ]
    except Exception as exc:  # noqa: BLE001
        logger.debug("DB chain unavailable (%s), falling back to env", exc)

    # Env-based fallback. The key has to be attached explicitly: settings reads
    # it out of `.env` into the Settings object, which does **not** put it in the
    # process environment — so LiteLLM's own env lookup finds nothing and every
    # model fails with "missing credentials" despite the key being configured.
    # (It happens to work under Docker, where compose `env_file` sets real env
    # vars, which is exactly what makes the local-dev failure confusing.)
    candidates = [settings.llm_primary_model, *settings.fallback_model_list]
    chain = [
        {"model": model, "provider_id": None, "api_key": _settings_key_for(model)}
        for model in candidates
        if model
    ]

    # Drop keyless cloud models rather than dialling them. Attempting a provider
    # with no credential costs a full network round trip and returns "missing
    # credentials" every time — with three unconfigured providers and a 30s
    # timeout that turned an unconfigured install into a 90-second wait before it
    # fell back. Local models are exempt: they legitimately need no key.
    usable = [entry for entry in chain if entry["api_key"] or _is_keyless_model(entry["model"])]
    if not usable and chain:
        logger.info(
            "No LLM credentials configured (%d model(s) declared, none with a key) — "
            "skipping straight to the fallback",
            len(chain),
        )
    return usable


#: Providers that run locally and need no credential.
_KEYLESS_PREFIXES = ("ollama", "lm_studio", "llamafile", "vllm", "openai_like")


def _is_keyless_model(model: str) -> bool:
    prefix = model.split("/")[0].lower() if "/" in model else model.lower()
    return prefix in _KEYLESS_PREFIXES


def _settings_key_for(model: str) -> str | None:
    """Look up the configured API key for a model's provider prefix."""
    prefix = model.split("/")[0].lower() if "/" in model else model.lower()
    key = getattr(settings, f"{prefix}_api_key", None)
    # Treat a blank value in .env as absent rather than passing "" downstream,
    # which some providers report as "invalid key" instead of "missing key".
    return key or None


async def _log_usage(
    *,
    provider_id: str | None,
    model: str,
    agent: str | None,
    tokens_in: int = 0,
    tokens_out: int = 0,
    latency_ms: int = 0,
    success: bool = True,
    error_msg: str | None = None,
) -> None:
    """Log usage to DB. Never raises."""
    try:
        from app.core.llm_providers import record_usage

        await record_usage(
            provider_id=provider_id,
            model=model,
            agent=agent,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            latency_ms=latency_ms,
            success=success,
            error_msg=error_msg,
        )
    except Exception:  # noqa: BLE001
        pass  # Usage logging must never break the call path


def _is_rate_limit_error(exc: Exception) -> bool:
    """Detect if an exception is a rate-limit (429) error."""
    status = getattr(exc, "status_code", None)
    if status == 429:
        return True
    msg = str(exc).lower()
    return "rate limit" in msg or "rate_limit" in msg or "429" in msg


#: Provider prefix → env var that LiteLLM reads for the API key.
_PROVIDER_ENV_MAP = {
    "dashscope": "DASHSCOPE_API_KEY",
    "groq": "GROQ_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "cerebras": "CEREBRAS_API_KEY",
    "openai": "OPENAI_API_KEY",
    "mistral": "MISTRAL_API_KEY",
    "cohere": "COHERE_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
}


def _set_provider_env(model: str, api_key: str | None) -> None:
    """Temporarily set the provider-specific env var so LiteLLM finds the key.

    Called before each provider attempt in the failover chain. The env var is
    overwritten on the next call, so no cleanup is needed between candidates.
    """
    if not api_key:
        return
    prefix = model.split("/")[0].lower() if "/" in model else ""
    env_var = _PROVIDER_ENV_MAP.get(prefix)
    if env_var:
        import os

        os.environ[env_var] = api_key


async def _mark(
    provider_id: str | None,
    status: str,
    detail: str | None,
    *,
    cooldown: Any = None,
) -> None:
    """Record a provider outcome. Never raises on the hot path."""
    if not provider_id:
        return
    try:
        from app.core.llm_providers import mark_status

        await mark_status(provider_id, status, detail, cooldown=cooldown)
    except Exception:  # noqa: BLE001
        pass


def _classify_failure(exc: Exception) -> tuple[str, Any]:
    """Map a provider exception onto (status, cooldown).

    The distinction matters: a 401 means never try this key again until the
    operator fixes it, while a 429 means try it again shortly.
    """
    from datetime import timedelta

    status_code = getattr(exc, "status_code", None)
    message = str(exc).lower()

    if status_code == 429 or "rate limit" in message or "rate_limit" in message or "429" in message:
        return "rate_limited", timedelta(seconds=90)
    if status_code in (401, 403) or "invalid api key" in message or "unauthorized" in message:
        return "invalid", None
    if "missing credentials" in message or "no api key" in message:
        return "invalid", None
    if "quota" in message or "insufficient_quota" in message or "credit" in message:
        return "limit_reached", timedelta(hours=1)
    return "untested", None

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
            acompletion, model, None, messages, temperature, response_format, agent,
        )

    # Build the candidate chain
    candidates = await _build_chain()
    if not candidates:
        raise LLMUnavailableError("No LLM providers configured")

    last_error: Exception | None = None

    for candidate in candidates:
        litellm_model = candidate["model"]
        provider_id = candidate.get("provider_id")
        api_key = candidate.get("api_key")

        # Set provider-specific env var so LiteLLM always finds the key
        _set_provider_env(litellm_model, api_key)

        try:
            start = time.monotonic()
            response = await acompletion(
                model=litellm_model,
                messages=messages,
                temperature=(settings.llm_temperature if temperature is None else temperature),
                timeout=settings.llm_timeout_seconds,
                response_format=response_format,
                api_key=api_key,
            )
            elapsed = int((time.monotonic() - start) * 1000)
            content = response.choices[0].message.content or ""

            # Record successful usage
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
            return content

        except Exception as exc:  # noqa: BLE001
            last_error = exc
            elapsed = int((time.monotonic() - start) * 1000)
            err_msg = str(exc)[:500]

            # Log failed usage
            await _log_usage(
                provider_id=provider_id,
                model=litellm_model,
                agent=agent,
                latency_ms=elapsed,
                success=False,
                error_msg=err_msg,
            )

            # Detect rate-limit specifically
            is_rate_limit = _is_rate_limit_error(exc)
            if is_rate_limit:
                logger.warning("LLM %s rate-limited, rotating to next provider", litellm_model)
            else:
                logger.warning("LLM %s failed: %s", litellm_model, exc)

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
    """Call a single model (used for test calls and explicit model overrides)."""
    start = time.monotonic()
    try:
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": settings.llm_temperature if temperature is None else temperature,
            "timeout": settings.llm_timeout_seconds,
        }
        if response_format:
            kwargs["response_format"] = response_format
        if api_key:
            kwargs["api_key"] = api_key

        response = await acompletion(**kwargs)
        elapsed = int((time.monotonic() - start) * 1000)
        return response.choices[0].message.content or ""
    except Exception as exc:
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

    # Env-based fallback
    candidates = [settings.llm_primary_model, *settings.fallback_model_list]
    return [{"model": m, "provider_id": None, "api_key": None} for m in candidates if m]


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

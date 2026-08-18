"""Model presets for the Engine "add provider" form.

**These are a starting point, not the truth.** Providers retire models without
warning, and a stale preset fails in the most confusing way possible: the key is
valid, the request is well-formed, and the provider answers `model_not_found`,
which reads like an authentication problem. That is exactly what happened when
Groq decommissioned `llama-3.1-8b-instant` and `llama-3.3-70b-versatile` on
2026-08-16 while this file still offered them.

So `core/llm_discovery.py` is the source of truth — it asks the provider what it
will serve right now — and the Engine form offers "Load live models" as soon as a
key is present. These presets are what the form shows *before* that, plus the
per-provider signup links and suggested quota ceilings.

Anything OpenAI-compatible works whether or not it is listed here; the form always
accepts a custom `provider/model` string.

`free_tier` marks providers with a usable no-cost tier, since that is the first
thing an operator building on free quotas needs to know.

Last reviewed: 2026-08-18.
"""

from __future__ import annotations

from typing import Any

PRESETS: list[dict[str, Any]] = [
    {
        "provider": "dashscope",
        "name": "DashScope (Alibaba Qwen)",
        "icon": "🟠",
        "env_var": "DASHSCOPE_API_KEY",
        "signup_url": "https://www.alibabacloud.com/help/en/model-studio/",
        "free_tier": True,
        "suggested": {"max_rpm": 30, "max_rpd": 1500},
        "note": (
            "Journava's hero model — it is what makes the Alibaba story real. "
            "The 3.7 series is current; the unversioned aliases track the latest."
        ),
        "models": [
            {"value": "dashscope/qwen3.7-max", "label": "Qwen3.7 Max", "tag": "strongest"},
            {"value": "dashscope/qwen3.7-plus", "label": "Qwen3.7 Plus", "tag": "recommended"},
            {"value": "dashscope/qwen-plus", "label": "Qwen Plus (latest alias)"},
            {"value": "dashscope/qwen-turbo", "label": "Qwen Turbo", "tag": "fastest"},
            {"value": "dashscope/qwen-max", "label": "Qwen Max (latest alias)"},
        ],
    },
    {
        "provider": "groq",
        "name": "Groq",
        "icon": "⚡",
        "env_var": "GROQ_API_KEY",
        "signup_url": "https://console.groq.com/keys",
        "free_tier": True,
        "suggested": {"max_rpm": 28, "max_rpd": 14000},
        "note": (
            "Very fast, generous free tier. Groq shut down every Llama model on "
            "2026-08-16 — use GPT-OSS or Qwen3.6, or press Load live models."
        ),
        "models": [
            {
                "value": "groq/openai/gpt-oss-120b",
                "label": "GPT-OSS 120B",
                "tag": "recommended",
            },
            {"value": "groq/openai/gpt-oss-20b", "label": "GPT-OSS 20B", "tag": "fastest"},
            {"value": "groq/qwen/qwen3.6-27b", "label": "Qwen3.6 27B"},
            {"value": "groq/groq/compound", "label": "Compound", "tag": "agentic"},
            {"value": "groq/groq/compound-mini", "label": "Compound Mini"},
        ],
    },
    {
        "provider": "gemini",
        "name": "Google Gemini",
        "icon": "🔷",
        "env_var": "GEMINI_API_KEY",
        "signup_url": "https://aistudio.google.com/apikey",
        "free_tier": True,
        "suggested": {"max_rpm": 15, "max_rpd": 1500},
        "models": [
            {"value": "gemini/gemini-2.0-flash", "label": "Gemini 2.0 Flash", "tag": "recommended"},
            {"value": "gemini/gemini-2.5-flash", "label": "Gemini 2.5 Flash"},
            {"value": "gemini/gemini-2.5-pro", "label": "Gemini 2.5 Pro", "tag": "strongest"},
        ],
    },
    {
        "provider": "openrouter",
        "name": "OpenRouter",
        "icon": "🌐",
        "env_var": "OPENROUTER_API_KEY",
        "signup_url": "https://openrouter.ai/keys",
        "free_tier": True,
        "suggested": {"max_rpm": 20, "max_rpd": 1000},
        "note": "One key, many models. The `:free` variants cost nothing.",
        "models": [
            {
                "value": "openrouter/deepseek/deepseek-chat-v3.1:free",
                "label": "DeepSeek V3.1",
                "tag": "free",
            },
            {
                "value": "openrouter/openai/gpt-oss-120b:free",
                "label": "GPT-OSS 120B",
                "tag": "free",
            },
            {
                "value": "openrouter/qwen/qwen3-235b-a22b:free",
                "label": "Qwen3 235B",
                "tag": "free",
            },
            {"value": "openrouter/anthropic/claude-sonnet-4.5", "label": "Claude Sonnet 4.5"},
        ],
    },
    {
        "provider": "cerebras",
        "name": "Cerebras",
        "icon": "🧠",
        "env_var": "CEREBRAS_API_KEY",
        "signup_url": "https://cloud.cerebras.ai/",
        "free_tier": True,
        "suggested": {"max_rpm": 30, "max_rpd": 14400},
        "models": [
            {"value": "cerebras/llama-3.3-70b", "label": "Llama 3.3 70B", "tag": "recommended"},
            {"value": "cerebras/qwen-3-32b", "label": "Qwen3 32B"},
        ],
    },
    {
        "provider": "deepseek",
        "name": "DeepSeek",
        "icon": "🐋",
        "env_var": "DEEPSEEK_API_KEY",
        "signup_url": "https://platform.deepseek.com/api_keys",
        "free_tier": False,
        "models": [
            {"value": "deepseek/deepseek-chat", "label": "DeepSeek Chat", "tag": "cheap"},
            {"value": "deepseek/deepseek-reasoner", "label": "DeepSeek Reasoner"},
        ],
    },
    {
        "provider": "mistral",
        "name": "Mistral",
        "icon": "🌬️",
        "env_var": "MISTRAL_API_KEY",
        "signup_url": "https://console.mistral.ai/api-keys/",
        "free_tier": True,
        "models": [
            {"value": "mistral/mistral-small-latest", "label": "Mistral Small", "tag": "free tier"},
            {"value": "mistral/mistral-large-latest", "label": "Mistral Large"},
        ],
    },
    {
        "provider": "cohere",
        "name": "Cohere",
        "icon": "🔮",
        "env_var": "COHERE_API_KEY",
        "signup_url": "https://dashboard.cohere.com/api-keys",
        "free_tier": True,
        "models": [
            {"value": "cohere/command-r-plus", "label": "Command R+"},
            {"value": "cohere/command-r", "label": "Command R", "tag": "cheap"},
        ],
    },
    {
        "provider": "openai",
        "name": "OpenAI",
        "icon": "⚫",
        "env_var": "OPENAI_API_KEY",
        "signup_url": "https://platform.openai.com/api-keys",
        "free_tier": False,
        "models": [
            {"value": "openai/gpt-4o-mini", "label": "GPT-4o mini", "tag": "cheap"},
            {"value": "openai/gpt-4o", "label": "GPT-4o"},
        ],
    },
    {
        "provider": "anthropic",
        "name": "Anthropic",
        "icon": "🅰️",
        "env_var": "ANTHROPIC_API_KEY",
        "signup_url": "https://console.anthropic.com/settings/keys",
        "free_tier": False,
        "models": [
            {"value": "anthropic/claude-sonnet-4-5", "label": "Claude Sonnet 4.5"},
            {"value": "anthropic/claude-haiku-4-5", "label": "Claude Haiku 4.5", "tag": "fast"},
        ],
    },
    {
        "provider": "ollama",
        "name": "Ollama (local)",
        "icon": "🦙",
        "env_var": None,
        "signup_url": "https://ollama.com/",
        "free_tier": True,
        "note": "No key needed. Must be running locally; used as the last resort.",
        "models": [
            {"value": "ollama/llama3.2", "label": "Llama 3.2", "tag": "no key"},
            {"value": "ollama/qwen2.5", "label": "Qwen 2.5", "tag": "no key"},
        ],
    },
]


def all_models() -> list[dict[str, Any]]:
    """Flat list of every preset model, annotated with its provider."""
    return [
        {
            **model,
            "provider": preset["provider"],
            "provider_name": preset["name"],
            "icon": preset["icon"],
            "suggested": preset.get("suggested", {}),
        }
        for preset in PRESETS
        for model in preset["models"]
    ]

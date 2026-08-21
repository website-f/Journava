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

Quick-pick roster: Groq · OpenRouter · Hugging Face · Mistral · Cohere · DeepSeek
· OpenAI. DashScope, Cerebras, Gemini, Anthropic and Ollama were removed from the
quick pick (2026-08-21) — you can still add any of them with a custom
`provider/model` string, and Load live models still works for every provider.

Free-tier notes below were researched 2026-08-21:
- OpenRouter dropped the free DeepSeek/Gemini/Mistral variants — the old
  `deepseek-*:free` / gemini `:free` slugs now 404 ("use the paid slug"). The
  reliable free ones are GPT-OSS-20B and Qwen3-Coder; the roster changes weekly,
  so Load live models is the truth.
- Groq's free tier serves ALL its models (GPT-OSS, Llama, Qwen3, Kimi) at
  30 rpm / 14.4k rpd — the earlier "Llama removed" note was wrong.
- Mistral's free "Experiment" tier covers every model (incl. Large/Codestral) at
  ~1 req/s. Cohere's free trial key = 1,000 calls/month across the Command line.

Last reviewed: 2026-08-21.
"""

from __future__ import annotations

from typing import Any

PRESETS: list[dict[str, Any]] = [
    {
        "provider": "groq",
        "name": "Groq",
        "icon": "⚡",
        "env_var": "GROQ_API_KEY",
        "signup_url": "https://console.groq.com/keys",
        "free_tier": True,
        "suggested": {"max_rpm": 28, "max_rpd": 14000},
        "note": (
            "Very fast, genuinely free (30 rpm / 14.4k rpd, no card). The whole "
            "catalogue is on the free tier — GPT-OSS, Llama, Qwen3, Kimi."
        ),
        "models": [
            {"value": "groq/openai/gpt-oss-120b", "label": "GPT-OSS 120B", "tag": "recommended"},
            {"value": "groq/openai/gpt-oss-20b", "label": "GPT-OSS 20B", "tag": "fastest"},
            {"value": "groq/llama-3.3-70b-versatile", "label": "Llama 3.3 70B"},
            {"value": "groq/qwen/qwen3-32b", "label": "Qwen3 32B"},
            {"value": "groq/moonshotai/kimi-k2-instruct", "label": "Kimi K2", "tag": "agentic"},
        ],
    },
    {
        "provider": "openrouter",
        "name": "OpenRouter",
        "icon": "🌐",
        "env_var": "OPENROUTER_API_KEY",
        "signup_url": "https://openrouter.ai/keys",
        "free_tier": True,
        "suggested": {"max_rpm": 20, "max_rpd": 200},
        "note": (
            "One key, many models; `:free` variants cost nothing (20 rpm / 200 rpd). "
            "The free roster changes weekly — press Load live models. Heads-up: the "
            "free DeepSeek/Gemini/Mistral variants were removed, so those `:free` "
            "slugs now 404."
        ),
        "models": [
            {"value": "openrouter/openai/gpt-oss-20b:free", "label": "GPT-OSS 20B", "tag": "free"},
            {"value": "openrouter/qwen/qwen3-coder:free", "label": "Qwen3 Coder", "tag": "free"},
            {"value": "openrouter/nvidia/nemotron-nano-9b-v2:free", "label": "Nemotron Nano 9B", "tag": "free"},
            {"value": "openrouter/openai/gpt-4o-mini", "label": "GPT-4o mini", "tag": "cheap"},
        ],
    },
    {
        "provider": "huggingface",
        "name": "Hugging Face",
        "icon": "🤗",
        "env_var": "HUGGINGFACE_API_KEY",
        "signup_url": "https://huggingface.co/settings/tokens",
        "free_tier": True,
        "suggested": {"max_rpm": 10, "max_rpd": 1000},
        "note": (
            "Serverless Inference Providers with a monthly free credit. Use "
            "`huggingface/<repo-id>`; availability depends on which providers host "
            "the model — Load live models to confirm."
        ),
        "models": [
            {"value": "huggingface/meta-llama/Llama-3.3-70B-Instruct", "label": "Llama 3.3 70B", "tag": "recommended"},
            {"value": "huggingface/Qwen/Qwen2.5-72B-Instruct", "label": "Qwen2.5 72B"},
            {"value": "huggingface/mistralai/Mistral-7B-Instruct-v0.3", "label": "Mistral 7B", "tag": "fast"},
        ],
    },
    {
        "provider": "mistral",
        "name": "Mistral",
        "icon": "🌬️",
        "env_var": "MISTRAL_API_KEY",
        "signup_url": "https://console.mistral.ai/api-keys/",
        "free_tier": True,
        "suggested": {"max_rpm": 1, "max_rpd": 500},
        "note": "Free 'Experiment' tier — every model at ~1 req/s, ~1B tokens/month. Evaluation only.",
        "models": [
            {"value": "mistral/mistral-small-latest", "label": "Mistral Small", "tag": "free"},
            {"value": "mistral/open-mistral-nemo", "label": "Mistral Nemo", "tag": "fast"},
            {"value": "mistral/mistral-large-latest", "label": "Mistral Large", "tag": "strongest"},
            {"value": "mistral/codestral-latest", "label": "Codestral", "tag": "coding"},
        ],
    },
    {
        "provider": "cohere",
        "name": "Cohere",
        "icon": "🔮",
        "env_var": "COHERE_API_KEY",
        "signup_url": "https://dashboard.cohere.com/api-keys",
        "free_tier": True,
        "suggested": {"max_rpm": 20, "max_rpd": 1000},
        "note": "Free trial key — 1,000 calls/month, 20 chat req/min. Not for production use.",
        "models": [
            {"value": "cohere/command-a-03-2025", "label": "Command A (111B)", "tag": "strongest"},
            {"value": "cohere/command-r-plus", "label": "Command R+", "tag": "recommended"},
            {"value": "cohere/command-r", "label": "Command R", "tag": "cheap"},
            {"value": "cohere/command-r7b-12-2024", "label": "Command R7B", "tag": "fast"},
        ],
    },
    {
        "provider": "deepseek",
        "name": "DeepSeek",
        "icon": "🐋",
        "env_var": "DEEPSEEK_API_KEY",
        "signup_url": "https://platform.deepseek.com/api_keys",
        "free_tier": False,
        "note": "No free tier, but very cheap. V3 chat + R1 reasoner.",
        "models": [
            {"value": "deepseek/deepseek-chat", "label": "DeepSeek V3 (chat)", "tag": "cheap"},
            {"value": "deepseek/deepseek-reasoner", "label": "DeepSeek R1 (reasoner)"},
        ],
    },
    {
        "provider": "openai",
        "name": "OpenAI",
        "icon": "⚫",
        "env_var": "OPENAI_API_KEY",
        "signup_url": "https://platform.openai.com/api-keys",
        "free_tier": False,
        "note": "No free tier. The mini/nano models are cheap and reliable.",
        "models": [
            {"value": "openai/gpt-4o-mini", "label": "GPT-4o mini", "tag": "cheap"},
            {"value": "openai/gpt-4.1-mini", "label": "GPT-4.1 mini", "tag": "recommended"},
            {"value": "openai/gpt-4.1-nano", "label": "GPT-4.1 nano", "tag": "cheapest"},
            {"value": "openai/o4-mini", "label": "o4-mini", "tag": "reasoning"},
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

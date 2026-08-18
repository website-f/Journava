"""Application settings — every secret comes from the environment (see ops/.env.example)."""

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- App ---
    app_name: str = "Journava API"
    environment: Literal["dev", "staging", "prod"] = "dev"
    debug: bool = True
    api_prefix: str = "/api/v1"
    port: int = 8400

    # CORS — the PWA origin(s). Comma-separated in the env var.
    cors_origins: str = "http://localhost:5173"

    # --- Data ---
    database_url: str = "postgresql://journava:journava@localhost:5432/journava"
    redis_url: str = "redis://localhost:6379/0"

    # Cache TTLs (seconds) — protect free API quotas (spec §5).
    cache_ttl_short: int = 60 * 60 * 6  # 6h
    cache_ttl_long: int = 60 * 60 * 24  # 24h

    # --- LLM (LiteLLM gateway; Qwen is the hero model) ---
    llm_primary_model: str = "dashscope/qwen-plus"
    llm_fallback_models: str = "gemini/gemini-2.0-flash,groq/llama-3.3-70b-versatile"
    llm_temperature: float = 0.3
    llm_timeout_seconds: int = 60

    dashscope_api_key: str | None = None
    gemini_api_key: str | None = None
    groq_api_key: str | None = None
    openrouter_api_key: str | None = None

    # --- Local fallback model (keyless) ---
    # Tried only after every configured cloud provider has failed, so a demo
    # never dies on an expired key when Ollama is running locally.
    ollama_fallback_enabled: bool = True
    ollama_fallback_model: str = "ollama/llama3.2"
    # Probed directly before any call: reaching an absent Ollama through LiteLLM
    # costs ~9s, a TCP connect costs milliseconds.
    ollama_host: str = "localhost"
    ollama_port: int = 11434

    # --- API Vault ---
    # Fernet key encrypting every stored provider credential. Set this in
    # production: without it a key is derived from the database URL, so rotating
    # the DB password would make the whole vault unreadable.
    vault_encryption_key: str | None = None

    # --- Brain (Gnosion) ---
    gnosion_brain_path: str = "data/journava.gnosion"
    gnosion_mcp_url: str | None = None

    # --- Services ---
    camofox_url: str = "http://camofox:9377"
    atlas_flight_cli: str = "atlas-flight"
    atlas_sandbox: bool = True

    # --- Third-party API keys (all optional; agents degrade gracefully) ---
    amadeus_client_id: str | None = None
    amadeus_client_secret: str | None = None
    youtube_api_key: str | None = None
    reddit_client_id: str | None = None
    reddit_client_secret: str | None = None
    maptiler_key: str | None = None
    foursquare_api_key: str | None = None
    halaltrip_api_key: str | None = None
    tavily_api_key: str | None = None

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def fallback_model_list(self) -> list[str]:
        return [model.strip() for model in self.llm_fallback_models.split(",") if model.strip()]


@lru_cache
def get_settings() -> Settings:
    """Cached settings instance — import this, never construct Settings directly."""
    return Settings()


settings = get_settings()

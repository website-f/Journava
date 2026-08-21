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
    #: Multimodal model used by the assistant when the user attaches an image.
    llm_vision_model: str = "gemini/gemini-2.0-flash"

    #: Public origin used to build shareable plan links sent to clients (Telegram
    #: needs an absolute URL). Override with PUBLIC_BASE_URL in production.
    public_base_url: str = "http://127.0.0.1:8401"

    #: WhatsApp Cloud API (Meta). When both are set, client deliveries can go over
    #: WhatsApp; otherwise the channel reports "not configured" and we fall back
    #: to Telegram + the share link.
    whatsapp_token: str = ""
    whatsapp_phone_id: str = ""

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

    # --- Auth ---
    # HS256 signing secret for access tokens. If unset, a key is derived from the
    # vault key / DB URL so single-operator dev works out of the box — set an
    # explicit value in production.
    jwt_secret: str | None = None
    access_token_ttl_minutes: int = 30
    refresh_token_ttl_days: int = 14
    auth_cookie_name: str = "journava_refresh"
    # Send the refresh cookie only over HTTPS. False for local http://localhost;
    # set true in production (behind the shared Caddy TLS).
    auth_cookie_secure: bool = False
    auth_cookie_samesite: Literal["lax", "strict", "none"] = "lax"
    # Login throttle: max failed attempts per (email+ip) window before lockout.
    login_max_attempts: int = 8
    login_window_seconds: int = 900
    # Seed demo users on boot (dev/hackathon). Disable in a real deployment.
    seed_demo_users: bool = True
    seed_demo_password: str = "Journava!2026"

    # --- Brain (Gnosion) ---
    gnosion_brain_path: str = "data/journava.gnosion"
    gnosion_mcp_url: str | None = None

    # --- Services ---
    camofox_url: str = "http://camofox:9377"
    #: Optional outbound proxy for the browser (e.g. a residential/rotating proxy
    #: "http://user:pass@host:port"). The real fix for IP-based rate-limits.
    camofox_proxy: str = ""
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

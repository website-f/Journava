"""API Vault — every third-party credential, encrypted at rest.

Replaces `.env` as the place keys live. `.env` still carries *infrastructure*
config (database DSN, Redis URL, the vault's own encryption key), but provider
credentials — Atlas, Amadeus, hotels, restaurants, maps, LLMs — are added through
the UI and stored here.

Design, following the Sejuk Ops pattern:

- **Fernet-encrypted at rest.** Only a masked hint (`sk-…4f2a`) is ever returned
  by the API. There is no endpoint that reveals a stored secret.
- **Test before save.** Every provider kind has a probe, so a key is verified
  against the real service before it is committed. A key that cannot be verified
  is still storable, but it is stored with `status="invalid"` and the operator is
  told why rather than discovering it during a demo.
- **Health is observed, not assumed.** `healthy · rate_limited · limit_reached ·
  invalid · untested · disabled`, updated by real call outcomes.
- **Env fallback.** `resolve()` checks the vault first, then the matching
  `Settings` field, so an existing `.env` deployment keeps working.

The encryption key comes from `VAULT_ENCRYPTION_KEY`. If it is absent, a key is
derived from the Postgres password so a single-operator deployment works out of
the box — with a warning, because a derived key means rotating the DB password
also invalidates the vault.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from app.core import db
from app.core.settings import settings

logger = logging.getLogger(__name__)

CredentialStatus = Literal[
    "untested", "healthy", "rate_limited", "limit_reached", "invalid", "disabled"
]

#: Provider categories shown as tabs in the API Vault page.
CATEGORIES: dict[str, str] = {
    "llm": "AI Models",
    "flights": "Flights",
    "hotels": "Hotels & Stays",
    "places": "Places, Food & Activities",
    "weather": "Weather & Risk",
    "maps": "Maps & Routing",
    "social": "Social & Video",
    "content": "Content & Search",
    "payments": "Payments",
    "email": "Email",
    "other": "Other",
}


class ProviderSpec:
    """What Journava needs to know to use, test and describe one provider."""

    def __init__(
        self,
        *,
        slug: str,
        label: str,
        category: str,
        settings_field: str | None = None,
        needs_secret: bool = True,
        extra_fields: tuple[str, ...] = (),
        docs_url: str | None = None,
        note: str | None = None,
        keyless: bool = False,
    ) -> None:
        self.slug = slug
        self.label = label
        self.category = category
        #: The `Settings` attribute this used to be read from, for env fallback.
        self.settings_field = settings_field
        self.needs_secret = needs_secret
        #: Additional non-secret fields (client ids, account ids, base URLs).
        self.extra_fields = extra_fields
        self.docs_url = docs_url
        self.note = note
        #: True for services that need no credential — listed so the vault can
        #: show the operator the full picture of what the agents rely on.
        self.keyless = keyless

    def as_dict(self) -> dict[str, Any]:
        return {
            "slug": self.slug,
            "label": self.label,
            "category": self.category,
            "category_label": CATEGORIES.get(self.category, self.category),
            "needs_secret": self.needs_secret and not self.keyless,
            "extra_fields": list(self.extra_fields),
            "docs_url": self.docs_url,
            "note": self.note,
            "keyless": self.keyless,
        }


#: Every provider the spec's §9 table names, plus the LLM gateways.
PROVIDERS: dict[str, ProviderSpec] = {
    spec.slug: spec
    for spec in (
        # --- Flights -------------------------------------------------------- #
        ProviderSpec(
            slug="atlas",
            label="Atlas Flight Booking",
            category="flights",
            docs_url="https://www.atriptech.com/#/login",
            note=(
                "Sandbox mode: paste your ATRIP access key + secret key. The agents "
                "then search live sandbox fares and run the full verify → book → pay "
                "flow directly over the AK/SK API — no CLI, no browser sign-in. "
                "Secret = secret key; Access key goes in the field below."
            ),
            #: `access_key` is the ATRIP access key (x-atlas-client-id); the stored
            #: secret is the secret key (x-atlas-client-secret). `environment`
            #: stays "sandbox" until production is opted into.
            extra_fields=("access_key", "environment"),
        ),
        ProviderSpec(
            slug="amadeus",
            label="Amadeus Self-Service",
            category="flights",
            settings_field="amadeus_client_secret",
            extra_fields=("client_id",),
            docs_url="https://developers.amadeus.com/register",
        ),
        ProviderSpec(
            slug="aviationstack",
            label="AviationStack (flight status)",
            category="flights",
            docs_url="https://aviationstack.com/signup/free",
        ),
        # --- Hotels --------------------------------------------------------- #
        ProviderSpec(
            slug="hotelbeds",
            label="Hotelbeds APItude",
            category="hotels",
            extra_fields=("api_key",),
            docs_url="https://developer.hotelbeds.com/",
            note="Sandbox requires partner approval. Secret is the shared secret.",
        ),
        ProviderSpec(
            slug="expedia_rapid",
            label="Expedia Rapid",
            category="hotels",
            extra_fields=("api_key",),
            docs_url="https://developers.expediagroup.com/rapid",
        ),
        ProviderSpec(
            slug="booking_com",
            label="Booking.com",
            category="hotels",
            docs_url="https://developers.booking.com/",
        ),
        # --- Places / food / activities ------------------------------------- #
        ProviderSpec(
            slug="google_places",
            label="Google Places (New)",
            category="places",
            docs_url="https://console.cloud.google.com/",
            note="Billable with a free monthly allowance — set a quota cap.",
        ),
        ProviderSpec(
            slug="foursquare",
            label="Foursquare Places",
            category="places",
            settings_field="foursquare_api_key",
            docs_url="https://foursquare.com/developers/",
        ),
        ProviderSpec(
            slug="yelp",
            label="Yelp Fusion",
            category="places",
            docs_url="https://docs.developer.yelp.com/",
        ),
        ProviderSpec(
            slug="opentripmap",
            label="OpenTripMap",
            category="places",
            docs_url="https://opentripmap.io/product",
        ),
        ProviderSpec(
            slug="geoapify",
            label="Geoapify",
            category="places",
            docs_url="https://www.geoapify.com/",
        ),
        ProviderSpec(
            slug="halaltrip",
            label="HalalTrip",
            category="places",
            settings_field="halaltrip_api_key",
            docs_url="https://www.halaltrip.com/",
            note="Halal dining directory. JAKIM/MUIS lookups are public, no key.",
        ),
        ProviderSpec(
            slug="overpass",
            label="OSM Overpass",
            category="places",
            keyless=True,
            docs_url="https://overpass-api.de/",
        ),
        ProviderSpec(
            slug="nominatim",
            label="Nominatim geocoding",
            category="places",
            keyless=True,
            docs_url="https://nominatim.org/",
        ),
        # --- Weather -------------------------------------------------------- #
        ProviderSpec(
            slug="open_meteo",
            label="Open-Meteo",
            category="weather",
            keyless=True,
            docs_url="https://open-meteo.com/",
            note="No key required and generous limits — the default forecast source.",
        ),
        ProviderSpec(
            slug="openweathermap",
            label="OpenWeatherMap",
            category="weather",
            docs_url="https://openweathermap.org/api",
        ),
        ProviderSpec(
            slug="weatherapi",
            label="WeatherAPI",
            category="weather",
            docs_url="https://www.weatherapi.com/",
        ),
        # --- Maps ----------------------------------------------------------- #
        ProviderSpec(
            slug="maptiler",
            label="MapTiler",
            category="maps",
            settings_field="maptiler_key",
            docs_url="https://www.maptiler.com/",
            note="Without this the map falls back to raw OSM raster tiles.",
        ),
        ProviderSpec(
            slug="mapbox",
            label="Mapbox",
            category="maps",
            docs_url="https://account.mapbox.com/",
        ),
        ProviderSpec(
            slug="openrouteservice",
            label="OpenRouteService",
            category="maps",
            docs_url="https://openrouteservice.org/dev/#/signup",
        ),
        # --- Social / video -------------------------------------------------- #
        ProviderSpec(
            slug="youtube",
            label="YouTube Data API",
            category="social",
            settings_field="youtube_api_key",
            docs_url="https://console.cloud.google.com/",
            note="10,000 units/day; a search costs 100.",
        ),
        ProviderSpec(
            slug="reddit",
            label="Reddit",
            category="social",
            settings_field="reddit_client_secret",
            extra_fields=("client_id",),
            docs_url="https://www.reddit.com/prefs/apps",
            note="Reddit now blocks unauthenticated datacenter traffic — OAuth needed.",
        ),
        ProviderSpec(
            slug="gdelt",
            label="GDELT",
            category="social",
            keyless=True,
            docs_url="https://www.gdeltproject.org/",
        ),
        # --- Content / search ------------------------------------------------ #
        ProviderSpec(
            slug="tavily",
            label="Tavily AI search",
            category="content",
            settings_field="tavily_api_key",
            docs_url="https://tavily.com/",
        ),
        ProviderSpec(
            slug="firecrawl",
            label="Firecrawl",
            category="content",
            docs_url="https://www.firecrawl.dev/",
        ),
        ProviderSpec(
            slug="unsplash",
            label="Unsplash imagery",
            category="content",
            docs_url="https://unsplash.com/developers",
        ),
        ProviderSpec(
            slug="pexels",
            label="Pexels imagery",
            category="content",
            docs_url="https://www.pexels.com/api/",
        ),
        ProviderSpec(
            slug="sherpa",
            label="Sherpa (entry requirements)",
            category="content",
            docs_url="https://www.joinsherpa.com/travel-restrictions-api",
        ),
        # --- Payments / email ------------------------------------------------ #
        ProviderSpec(
            slug="stripe",
            label="Stripe (test)",
            category="payments",
            docs_url="https://dashboard.stripe.com/register",
        ),
        ProviderSpec(
            slug="resend",
            label="Resend",
            category="email",
            docs_url="https://resend.com/",
        ),
        # --- Free / open-source / keyless ------------------------------------ #
        # These need no key (or a generous free tier) and are listed so the
        # operator can see the full breadth of what the agents can draw on.
        ProviderSpec(
            slug="frankfurter",
            label="Frankfurter FX",
            category="payments",
            keyless=True,
            docs_url="https://frankfurter.dev/",
            note="ECB reference rates, no key — the default currency converter.",
        ),
        ProviderSpec(
            slug="rest_countries",
            label="REST Countries",
            category="content",
            keyless=True,
            docs_url="https://restcountries.com/",
            note="Currency, languages, calling code, region — no key.",
        ),
        ProviderSpec(
            slug="wikivoyage",
            label="Wikivoyage",
            category="content",
            keyless=True,
            docs_url="https://en.wikivoyage.org/w/api.php",
            note="Community travel guides via the MediaWiki API — no key.",
        ),
        ProviderSpec(
            slug="wikimedia",
            label="Wikipedia / Wikimedia REST",
            category="content",
            keyless=True,
            docs_url="https://api.wikimedia.org/wiki/Main_Page",
            note="Place summaries and images — no key for reasonable volumes.",
        ),
        ProviderSpec(
            slug="travelbriefing",
            label="TravelBriefing",
            category="content",
            keyless=True,
            docs_url="https://travelbriefing.org/",
            note="Per-country advisories, vaccinations, water safety — no key.",
        ),
        ProviderSpec(
            slug="nager_holidays",
            label="Nager.Date public holidays",
            category="content",
            keyless=True,
            docs_url="https://date.nager.at/",
            note="Public holidays by country and year — no key.",
        ),
        ProviderSpec(
            slug="photon",
            label="Photon geocoder (Komoot)",
            category="maps",
            keyless=True,
            docs_url="https://photon.komoot.io/",
            note="Open geocoding over OSM data — no key.",
        ),
        ProviderSpec(
            slug="osrm",
            label="OSRM routing (demo)",
            category="maps",
            keyless=True,
            docs_url="https://project-osrm.org/",
            note="Driving/walking routes on the public demo server — no key.",
        ),
        ProviderSpec(
            slug="opencage",
            label="OpenCage geocoding",
            category="maps",
            docs_url="https://opencagedata.com/api",
            note="2,500 free geocodes/day on the free plan.",
        ),
        ProviderSpec(
            slug="api_ninjas",
            label="API Ninjas",
            category="content",
            docs_url="https://api-ninjas.com/",
            note="Airport, airline, city and timezone lookups on a free key.",
        ),
        ProviderSpec(
            slug="currency_beacon",
            label="CurrencyBeacon",
            category="payments",
            docs_url="https://currencybeacon.com/",
            note="5,000 free FX requests/month — a keyed alternative to Frankfurter.",
        ),
    )
}


# --------------------------------------------------------------------------- #
# Encryption
# --------------------------------------------------------------------------- #

_fernet: Any = None


def _encryption_key() -> bytes:
    """Return the Fernet key, deriving one when none is configured."""
    configured = settings.vault_encryption_key
    if configured:
        raw = configured.encode()
        # Accept either a real Fernet key or any passphrase.
        if len(raw) == 44 and raw.endswith(b"="):
            return raw
        digest = hashlib.sha256(raw).digest()
        return base64.urlsafe_b64encode(digest)

    logger.warning(
        "VAULT_ENCRYPTION_KEY is not set — deriving a key from the database "
        "password. Set an explicit key in production: rotating the DB password "
        "would otherwise make every stored credential unreadable."
    )
    seed = f"journava-vault::{settings.database_url}".encode()
    return base64.urlsafe_b64encode(hashlib.sha256(seed).digest())


def _cipher() -> Any:
    global _fernet
    if _fernet is None:
        from cryptography.fernet import Fernet

        _fernet = Fernet(_encryption_key())
    return _fernet


def encrypt(secret: str) -> str:
    return _cipher().encrypt(secret.encode()).decode()


def decrypt(token: str) -> str | None:
    """Decrypt a stored secret. None when the key no longer matches."""
    from cryptography.fernet import InvalidToken

    try:
        return _cipher().decrypt(token.encode()).decode()
    except (InvalidToken, Exception) as exc:  # noqa: BLE001
        logger.error("Could not decrypt a stored credential: %s", exc)
        return None


def mask(secret: str) -> str:
    """A hint that identifies a key without revealing it."""
    if not secret:
        return ""
    if len(secret) <= 8:
        return "•" * len(secret)
    return f"{secret[:3]}…{secret[-4:]}"


# --------------------------------------------------------------------------- #
# Storage
# --------------------------------------------------------------------------- #


def _row_to_public(row: dict[str, Any]) -> dict[str, Any]:
    """Shape a row for the API: never includes the secret."""
    spec = PROVIDERS.get(row["provider"])
    return {
        "id": str(row["id"]),
        "provider": row["provider"],
        "label": row.get("label") or (spec.label if spec else row["provider"]),
        "category": row.get("category") or (spec.category if spec else "other"),
        "masked_secret": row.get("masked_secret") or "",
        "extra": row.get("extra") or {},
        "enabled": row["enabled"],
        "status": row["status"],
        "status_detail": row.get("status_detail"),
        "last_tested_at": (
            row["last_tested_at"].isoformat() if row.get("last_tested_at") else None
        ),
        "created_at": row["created_at"].isoformat() if row.get("created_at") else None,
    }


async def list_credentials(category: str | None = None) -> list[dict[str, Any]]:
    """Every stored credential, secrets masked."""
    pool = await db.get_pool()
    if pool is None:
        return []
    query = (
        "SELECT id, provider, label, category, masked_secret, extra, enabled, "
        "status, status_detail, last_tested_at, created_at FROM api_credentials"
    )
    params: list[Any] = []
    if category:
        query += " WHERE category = $1"
        params.append(category)
    query += " ORDER BY category, provider, created_at"
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(query, *params)
        return [_row_to_public(_decode_row(dict(row))) for row in rows]
    except Exception as exc:  # noqa: BLE001
        logger.warning("vault.list_credentials failed: %s", exc)
        return []


def _decode_row(row: dict[str, Any]) -> dict[str, Any]:
    """asyncpg returns JSONB as a string; normalise it."""
    import json

    extra = row.get("extra")
    if isinstance(extra, str):
        try:
            row["extra"] = json.loads(extra)
        except (ValueError, TypeError):
            row["extra"] = {}
    return row


async def upsert_credential(
    provider: str,
    *,
    secret: str | None,
    extra: dict[str, Any] | None = None,
    label: str | None = None,
    enabled: bool = True,
    status: CredentialStatus = "untested",
    status_detail: str | None = None,
) -> dict[str, Any] | None:
    """Create or replace the credential for `provider`.

    One credential per provider, so re-adding a key rotates it rather than
    silently accumulating duplicates that rotate unpredictably.
    """
    import json

    pool = await db.get_pool()
    if pool is None:
        return None

    spec = PROVIDERS.get(provider)
    category = spec.category if spec else "other"
    resolved_label = label or (spec.label if spec else provider)

    encrypted = encrypt(secret) if secret else None
    masked = mask(secret) if secret else ""

    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """INSERT INTO api_credentials
                       (provider, label, category, secret_encrypted, masked_secret,
                        extra, enabled, status, status_detail, last_tested_at)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9,
                           CASE WHEN $8 = 'untested' THEN NULL ELSE now() END)
                   ON CONFLICT (provider) DO UPDATE SET
                       label = EXCLUDED.label,
                       category = EXCLUDED.category,
                       -- Keep the existing secret when the caller sends none, so
                       -- editing a label or quota does not wipe the key.
                       secret_encrypted = COALESCE(EXCLUDED.secret_encrypted,
                                                   api_credentials.secret_encrypted),
                       masked_secret = CASE WHEN EXCLUDED.secret_encrypted IS NULL
                                            THEN api_credentials.masked_secret
                                            ELSE EXCLUDED.masked_secret END,
                       extra = EXCLUDED.extra,
                       enabled = EXCLUDED.enabled,
                       status = EXCLUDED.status,
                       status_detail = EXCLUDED.status_detail,
                       last_tested_at = EXCLUDED.last_tested_at,
                       updated_at = now()
                   RETURNING id, provider, label, category, masked_secret, extra,
                             enabled, status, status_detail, last_tested_at, created_at""",
                provider,
                resolved_label,
                category,
                encrypted,
                masked,
                json.dumps(extra or {}),
                enabled,
                status,
                status_detail,
            )
        return _row_to_public(_decode_row(dict(row))) if row else None
    except Exception as exc:  # noqa: BLE001
        logger.error("vault.upsert_credential(%s) failed: %s", provider, exc)
        return None


async def delete_credential(provider: str) -> bool:
    pool = await db.get_pool()
    if pool is None:
        return False
    try:
        async with pool.acquire() as conn:
            result = await conn.execute("DELETE FROM api_credentials WHERE provider = $1", provider)
        _resolved_cache.pop(provider, None)
        return result.endswith("1")
    except Exception as exc:  # noqa: BLE001
        logger.error("vault.delete_credential(%s) failed: %s", provider, exc)
        return False


async def set_status(
    provider: str,
    status: CredentialStatus,
    detail: str | None = None,
) -> None:
    """Record an observed health status. Never raises."""
    pool = await db.get_pool()
    if pool is None:
        return
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE api_credentials SET status = $2, status_detail = $3, "
                "last_tested_at = now(), updated_at = now() WHERE provider = $1",
                provider,
                status,
                detail,
            )
    except Exception as exc:  # noqa: BLE001
        logger.debug("vault.set_status(%s) failed: %s", provider, exc)


# --------------------------------------------------------------------------- #
# Resolution — what the tools actually call
# --------------------------------------------------------------------------- #

#: Short-lived cache so a tool call doesn't hit Postgres for every request.
_resolved_cache: dict[str, tuple[float, dict[str, Any] | None]] = {}
_CACHE_TTL_SECONDS = 30.0


def invalidate_cache(provider: str | None = None) -> None:
    if provider is None:
        _resolved_cache.clear()
    else:
        _resolved_cache.pop(provider, None)


async def resolve(provider: str) -> dict[str, Any] | None:
    """Return `{"secret": str|None, "extra": dict}` for a provider, or None.

    Vault first, then the legacy `Settings` field, so a deployment that still
    keeps keys in `.env` keeps working while the vault is being populated.
    """
    import time

    cached = _resolved_cache.get(provider)
    now = time.monotonic()
    if cached and now - cached[0] < _CACHE_TTL_SECONDS:
        return cached[1]

    resolved = await _resolve_uncached(provider)
    _resolved_cache[provider] = (now, resolved)
    return resolved


async def _resolve_uncached(provider: str) -> dict[str, Any] | None:
    pool = await db.get_pool()
    if pool is not None:
        try:
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT secret_encrypted, extra, enabled, status FROM "
                    "api_credentials WHERE provider = $1",
                    provider,
                )
            if row and row["enabled"]:
                decoded = _decode_row(dict(row))
                secret = (
                    decrypt(decoded["secret_encrypted"]) if decoded["secret_encrypted"] else None
                )
                return {"secret": secret, "extra": decoded.get("extra") or {}}
        except Exception as exc:  # noqa: BLE001
            logger.debug("vault.resolve(%s) DB miss: %s", provider, exc)

    # Legacy env fallback.
    spec = PROVIDERS.get(provider)
    if spec and spec.settings_field:
        secret = getattr(settings, spec.settings_field, None)
        if secret:
            extra: dict[str, Any] = {}
            # Amadeus/Reddit keep their public id in a second settings field.
            for field in spec.extra_fields:
                value = getattr(settings, f"{provider}_{field}", None)
                if value:
                    extra[field] = value
            return {"secret": secret, "extra": extra}
    return None


async def secret_for(provider: str) -> str | None:
    """Just the secret, for the common single-key case."""
    resolved = await resolve(provider)
    return resolved.get("secret") if resolved else None


async def catalogue() -> list[dict[str, Any]]:
    """Every known provider, annotated with whether it is configured.

    Drives the API Vault page: the operator sees the full set of services the
    agents can use, not only the ones already filled in.
    """
    stored = {cred["provider"]: cred for cred in await list_credentials()}
    entries: list[dict[str, Any]] = []
    for spec in PROVIDERS.values():
        entry = spec.as_dict()
        credential = stored.get(spec.slug)
        env_fallback = bool(spec.settings_field and getattr(settings, spec.settings_field, None))
        entry["credential"] = credential
        entry["configured"] = bool(credential) or env_fallback or spec.keyless
        entry["source"] = "vault" if credential else ("env" if env_fallback else None)
        entries.append(entry)
    return entries


def utcnow() -> datetime:
    return datetime.now(UTC)


def new_id() -> str:
    return str(uuid.uuid4())

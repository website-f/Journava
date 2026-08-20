"""Credential probes — verify a key against the real service before saving.

The point is to fail at *configuration* time rather than mid-demo. Each probe
makes the cheapest possible authenticated call and maps the outcome onto a
`CredentialStatus`, so the operator learns immediately whether a key is good,
rate-limited, or simply wrong.

Every probe:

- returns `(status, message, latency_ms)` and never raises;
- distinguishes **invalid** (401/403 — wrong key) from **rate_limited** (429) and
  from **unreachable** (network), because those need different responses;
- uses a short timeout, since a probe is interactive.

A provider with no probe returns `untested` with an honest explanation rather
than a green tick it hasn't earned.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from app.core.vault import CredentialStatus

logger = logging.getLogger(__name__)

PROBE_TIMEOUT = httpx.Timeout(20.0, connect=8.0)

ProbeResult = tuple[CredentialStatus, str, int]


def _classify_http(status_code: int, body: str) -> ProbeResult:
    """Map an HTTP status onto a credential status."""
    snippet = body[:200].replace("\n", " ")
    if status_code in (401, 403):
        return "invalid", f"Rejected ({status_code}): {snippet}", 0
    if status_code == 429:
        return "rate_limited", "Key is valid but currently rate-limited", 0
    if status_code >= 500:
        return "untested", f"Provider error {status_code} — try again", 0
    if 200 <= status_code < 300:
        return "healthy", "Connected", 0
    return "invalid", f"Unexpected {status_code}: {snippet}", 0


async def _http_probe(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    params: dict[str, Any] | None = None,
    data: dict[str, Any] | None = None,
    json_body: dict[str, Any] | None = None,
    auth: tuple[str, str] | None = None,
    success_predicate: Callable[[httpx.Response], ProbeResult | None] | None = None,
) -> ProbeResult:
    start = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=PROBE_TIMEOUT) as client:
            response = await client.request(
                method,
                url,
                headers=headers,
                params=params,
                data=data,
                json=json_body,
                auth=auth,
            )
    except httpx.TimeoutException:
        return "untested", "Timed out reaching the provider", _ms(start)
    except Exception as exc:  # noqa: BLE001
        return "untested", f"Could not reach the provider: {exc}", _ms(start)

    elapsed = _ms(start)
    if success_predicate is not None:
        verdict = success_predicate(response)
        if verdict is not None:
            status, message, _ = verdict
            return status, message, elapsed

    status, message, _ = _classify_http(response.status_code, response.text)
    return status, message, elapsed


def _ms(start: float) -> int:
    return int((time.monotonic() - start) * 1000)


# --------------------------------------------------------------------------- #
# LLM providers
# --------------------------------------------------------------------------- #


async def probe_model(model: str, api_key: str) -> dict[str, Any]:
    """Test one model+key pair and return a verdict dict.

    The public entry point for LLM probing, mirroring `probe()` for the travel
    providers. It exists because the internal probes all return a
    `(status, message, latency)` tuple, and handing that straight to FastAPI —
    which is exactly what used to happen — fails response validation with a 500
    instead of reporting the real problem with the key.
    """
    status, message, latency = await probe_llm(model, api_key)
    return _verdict(status, message, latency)


async def probe_llm(model: str, api_key: str) -> ProbeResult:
    """Send a one-token completion through LiteLLM.

    This is the only probe that costs anything, and it is deliberately the
    smallest possible request — the operator gets a real end-to-end answer about
    whether this model works with this key.

    Returns the low-level tuple; callers facing HTTP should use `probe_model`.
    """
    start = time.monotonic()
    try:
        from litellm import acompletion
    except ImportError:
        return "untested", "litellm is not installed", 0

    import os

    from app.core.llm import _PROVIDER_ENV_MAP  # noqa: PLC2701 — shared mapping

    prefix = model.split("/")[0].lower() if "/" in model else ""
    env_var = _PROVIDER_ENV_MAP.get(prefix)
    previous = os.environ.get(env_var) if env_var else None
    if env_var and api_key:
        os.environ[env_var] = api_key

    try:
        response = await acompletion(
            model=model,
            messages=[{"role": "user", "content": "Reply with the single word: ok"}],
            temperature=0,
            max_tokens=5,
            timeout=25,
            api_key=api_key or None,
        )
        reply = (response.choices[0].message.content or "").strip()
        return "healthy", f"Connected — replied “{reply[:40]}”", _ms(start)
    except Exception as exc:  # noqa: BLE001
        return _classify_llm_error(exc), explain_llm_error(exc), _ms(start)
    finally:
        if env_var:
            if previous is not None:
                os.environ[env_var] = previous
            else:
                os.environ.pop(env_var, None)


def _classify_llm_error(exc: Exception) -> CredentialStatus:
    """Map a provider exception onto a credential status.

    `model_not_found` is deliberately `invalid` rather than `untested`: the key
    may be perfectly good, but the configuration cannot work as written and the
    operator has to change something. Reporting it as "untested" would imply
    "try again later", which would be false.
    """
    status_code = getattr(exc, "status_code", None)
    message = str(exc).lower()

    if "model_not_found" in message or "does not exist" in message:
        return "invalid"
    if "decommission" in message or "deprecated" in message:
        return "invalid"
    if status_code in (401, 403) or "invalid api key" in message or "unauthor" in message:
        return "invalid"
    if status_code == 429 or "rate limit" in message or "429" in message:
        return "rate_limited"
    if "quota" in message or "insufficient" in message or "credit" in message:
        return "limit_reached"
    if "missing credentials" in message or "api_key" in message:
        return "invalid"
    return "untested"


def explain_llm_error(exc: Exception) -> str:
    """A message that tells the operator what to actually do about it.

    LiteLLM's raw text is accurate but buried in provider JSON; a wrong model
    name and a wrong key produce similar-looking walls of text, and the fix is
    completely different.
    """
    raw = str(exc)
    lowered = raw.lower()

    if "model_not_found" in lowered or "does not exist" in lowered:
        return (
            "That model name is not available on this provider — the key may be "
            "fine. Pick a different model from Quick Pick, or check the "
            "provider's current model list. "
            f"({_trim(raw)})"
        )
    if "invalid api key" in lowered or "unauthor" in lowered:
        return f"The provider rejected this key. Check it was copied in full. ({_trim(raw)})"
    if "rate limit" in lowered or "429" in lowered:
        return f"The key works but is rate-limited right now. ({_trim(raw)})"
    if "quota" in lowered or "insufficient" in lowered or "credit" in lowered:
        return f"The key works but its quota or credit is exhausted. ({_trim(raw)})"
    if "missing credentials" in lowered:
        return "No key reached the provider — paste the key and try again."
    if "connection" in lowered or "timeout" in lowered:
        return f"Could not reach the provider. ({_trim(raw)})"
    return _trim(raw)


def _trim(text: str, limit: int = 220) -> str:
    collapsed = " ".join(text.split())
    return collapsed if len(collapsed) <= limit else collapsed[: limit - 1] + "…"


# --------------------------------------------------------------------------- #
# Travel providers
# --------------------------------------------------------------------------- #


async def probe_atlas(secret: str | None, extra: dict[str, Any]) -> ProbeResult:
    """Verify the Atlas credentials.

    Preferred path — **sandbox AK/SK**: an access key (in `extra["access_key"]`)
    plus the secret key. We make the cheapest authenticated call to the sandbox
    and confirm the keys are accepted (401 → wrong keys). This is the headless
    mode the demo uses — no CLI, no browser sign-in.

    Fallback — a keychain-authorised CLI install: run `atlas-flight doctor`.
    """
    start = time.monotonic()
    access_key = extra.get("access_key") or extra.get("client_id")
    environment = extra.get("environment") or "sandbox"
    suffix = f" (environment: {environment})" if environment else ""

    if access_key and secret:
        from app.tools import atlas_sandbox

        ok, message = await atlas_sandbox.check_credentials(str(access_key), str(secret))
        status: CredentialStatus = "healthy" if ok else "invalid"
        return status, f"{message}{suffix}", _ms(start)

    if access_key and not secret:
        return "invalid", "Add the secret key as well as the access key", _ms(start)
    if secret and not access_key:
        return "invalid", "Add the access key (x-atlas-client-id) in the field below", _ms(start)

    # No AK/SK — fall back to the CLI's own self-check.
    from app.tools import atlas_skill

    try:
        result = await atlas_skill.doctor(api_key=secret)
    except atlas_skill.AtlasSkillError as exc:
        return "invalid", str(exc)[:300], _ms(start)

    code = result.get("code", "")
    message = result.get("message", "")
    env = (result.get("data") or {}).get("environment") or environment
    csuffix = f" (environment: {env})" if env else ""
    if code == "DOCTOR_OK":
        return "healthy", f"Atlas ready{csuffix}", _ms(start)
    if code in ("AUTHORIZATION_REQUIRED", "AUTH_EXPIRED", "AUTH_SESSION_MISSING"):
        return "invalid", f"Add your sandbox access key + secret key above{csuffix}", _ms(start)
    return "untested", f"{code}: {message}"[:300] + csuffix, _ms(start)


async def probe_amadeus(secret: str, extra: dict[str, Any]) -> ProbeResult:
    """OAuth2 client-credentials against the Amadeus test environment."""
    client_id = extra.get("client_id", "")
    if not client_id:
        return "invalid", "Amadeus needs a client_id as well as the secret", 0
    return await _http_probe(
        "POST",
        "https://test.api.amadeus.com/v1/security/oauth2/token",
        data={
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": secret,
        },
    )


async def probe_reddit(secret: str, extra: dict[str, Any]) -> ProbeResult:
    client_id = extra.get("client_id", "")
    if not client_id:
        return "invalid", "Reddit needs a client_id as well as the secret", 0
    return await _http_probe(
        "POST",
        "https://www.reddit.com/api/v1/access_token",
        data={"grant_type": "client_credentials"},
        auth=(client_id, secret),
        headers={"User-Agent": "web:journava:1.0 (vault probe)"},
    )


async def probe_youtube(secret: str, _extra: dict[str, Any]) -> ProbeResult:
    def predicate(response: httpx.Response) -> ProbeResult | None:
        # YouTube answers 403 for both a bad key and an exhausted quota; the
        # reason string is the only way to tell them apart.
        if response.status_code == 403 and "quotaExceeded" in response.text:
            return "limit_reached", "Daily quota exhausted (key is valid)", 0
        return None

    return await _http_probe(
        "GET",
        "https://www.googleapis.com/youtube/v3/search",
        params={"part": "snippet", "q": "travel", "maxResults": 1, "key": secret},
        success_predicate=predicate,
    )


async def probe_google_places(secret: str, _extra: dict[str, Any]) -> ProbeResult:
    def predicate(response: httpx.Response) -> ProbeResult | None:
        if response.status_code == 200 and "error" in response.text.lower():
            return "invalid", response.text[:200], 0
        return None

    return await _http_probe(
        "POST",
        "https://places.googleapis.com/v1/places:searchText",
        headers={
            "X-Goog-Api-Key": secret,
            "X-Goog-FieldMask": "places.displayName",
            "Content-Type": "application/json",
        },
        json_body={"textQuery": "restaurant", "maxResultCount": 1},
        success_predicate=predicate,
    )


async def probe_foursquare(secret: str, _extra: dict[str, Any]) -> ProbeResult:
    return await _http_probe(
        "GET",
        "https://api.foursquare.com/v3/places/search",
        headers={"Authorization": secret, "Accept": "application/json"},
        params={"query": "cafe", "limit": 1},
    )


async def probe_yelp(secret: str, _extra: dict[str, Any]) -> ProbeResult:
    return await _http_probe(
        "GET",
        "https://api.yelp.com/v3/businesses/search",
        headers={"Authorization": f"Bearer {secret}"},
        params={"location": "Kuala Lumpur", "limit": 1},
    )


async def probe_maptiler(secret: str, _extra: dict[str, Any]) -> ProbeResult:
    return await _http_probe(
        "GET", f"https://api.maptiler.com/maps/streets-v2/style.json?key={secret}"
    )


async def probe_mapbox(secret: str, _extra: dict[str, Any]) -> ProbeResult:
    return await _http_probe(
        "GET",
        "https://api.mapbox.com/geocoding/v5/mapbox.places/venice.json",
        params={"access_token": secret, "limit": 1},
    )


async def probe_openrouteservice(secret: str, _extra: dict[str, Any]) -> ProbeResult:
    return await _http_probe(
        "GET",
        "https://api.openrouteservice.org/geocode/search",
        params={"api_key": secret, "text": "Venice", "size": 1},
    )


async def probe_openweathermap(secret: str, _extra: dict[str, Any]) -> ProbeResult:
    return await _http_probe(
        "GET",
        "https://api.openweathermap.org/data/2.5/weather",
        params={"q": "Venice", "appid": secret},
    )


async def probe_weatherapi(secret: str, _extra: dict[str, Any]) -> ProbeResult:
    return await _http_probe(
        "GET",
        "https://api.weatherapi.com/v1/current.json",
        params={"key": secret, "q": "Venice"},
    )


async def probe_geoapify(secret: str, _extra: dict[str, Any]) -> ProbeResult:
    return await _http_probe(
        "GET",
        "https://api.geoapify.com/v1/geocode/search",
        params={"text": "Venice", "limit": 1, "apiKey": secret},
    )


async def probe_opentripmap(secret: str, _extra: dict[str, Any]) -> ProbeResult:
    return await _http_probe(
        "GET",
        "https://api.opentripmap.com/0.1/en/places/geoname",
        params={"name": "Venice", "apikey": secret},
    )


async def probe_tavily(secret: str, _extra: dict[str, Any]) -> ProbeResult:
    return await _http_probe(
        "POST",
        "https://api.tavily.com/search",
        json_body={"api_key": secret, "query": "travel", "max_results": 1},
    )


async def probe_firecrawl(secret: str, _extra: dict[str, Any]) -> ProbeResult:
    return await _http_probe(
        "POST",
        "https://api.firecrawl.dev/v1/scrape",
        headers={"Authorization": f"Bearer {secret}"},
        json_body={"url": "https://example.com", "formats": ["markdown"]},
    )


async def probe_unsplash(secret: str, _extra: dict[str, Any]) -> ProbeResult:
    return await _http_probe(
        "GET",
        "https://api.unsplash.com/search/photos",
        headers={"Authorization": f"Client-ID {secret}"},
        params={"query": "venice", "per_page": 1},
    )


async def probe_pexels(secret: str, _extra: dict[str, Any]) -> ProbeResult:
    return await _http_probe(
        "GET",
        "https://api.pexels.com/v1/search",
        headers={"Authorization": secret},
        params={"query": "venice", "per_page": 1},
    )


async def probe_stripe(secret: str, _extra: dict[str, Any]) -> ProbeResult:
    return await _http_probe(
        "GET",
        "https://api.stripe.com/v1/balance",
        headers={"Authorization": f"Bearer {secret}"},
    )


async def probe_resend(secret: str, _extra: dict[str, Any]) -> ProbeResult:
    return await _http_probe(
        "GET",
        "https://api.resend.com/domains",
        headers={"Authorization": f"Bearer {secret}"},
    )


async def probe_halaltrip(secret: str, _extra: dict[str, Any]) -> ProbeResult:
    return await _http_probe(
        "GET",
        "https://www.halaltrip.com/api/search",
        params={"q": "restaurant", "api_key": secret},
    )


async def probe_aviationstack(secret: str, _extra: dict[str, Any]) -> ProbeResult:
    def predicate(response: httpx.Response) -> ProbeResult | None:
        # AviationStack returns 200 with an error object for a bad key.
        if response.status_code == 200 and '"error"' in response.text:
            return "invalid", response.text[:200], 0
        return None

    return await _http_probe(
        "GET",
        "https://api.aviationstack.com/v1/flights",
        params={"access_key": secret, "limit": 1},
        success_predicate=predicate,
    )


async def probe_opencage(secret: str, _extra: dict[str, Any]) -> ProbeResult:
    return await _http_probe(
        "GET",
        "https://api.opencagedata.com/geocode/v1/json",
        params={"q": "Kuala Lumpur", "key": secret, "limit": 1},
    )


async def probe_api_ninjas(secret: str, _extra: dict[str, Any]) -> ProbeResult:
    return await _http_probe(
        "GET",
        "https://api.api-ninjas.com/v1/airports",
        headers={"X-Api-Key": secret},
        params={"iata": "KUL"},
    )


async def probe_currency_beacon(secret: str, _extra: dict[str, Any]) -> ProbeResult:
    return await _http_probe(
        "GET",
        "https://api.currencybeacon.com/v1/latest",
        params={"api_key": secret, "base": "MYR", "symbols": "USD"},
    )


#: provider slug → probe. Providers absent from this map report `untested`.
PROBES: dict[str, Callable[[str, dict[str, Any]], Awaitable[ProbeResult]]] = {
    "opencage": probe_opencage,
    "api_ninjas": probe_api_ninjas,
    "currency_beacon": probe_currency_beacon,
    "amadeus": probe_amadeus,
    "aviationstack": probe_aviationstack,
    "reddit": probe_reddit,
    "youtube": probe_youtube,
    "google_places": probe_google_places,
    "foursquare": probe_foursquare,
    "yelp": probe_yelp,
    "maptiler": probe_maptiler,
    "mapbox": probe_mapbox,
    "openrouteservice": probe_openrouteservice,
    "openweathermap": probe_openweathermap,
    "weatherapi": probe_weatherapi,
    "geoapify": probe_geoapify,
    "opentripmap": probe_opentripmap,
    "tavily": probe_tavily,
    "firecrawl": probe_firecrawl,
    "unsplash": probe_unsplash,
    "pexels": probe_pexels,
    "stripe": probe_stripe,
    "resend": probe_resend,
    "halaltrip": probe_halaltrip,
}


async def probe(
    provider: str,
    secret: str | None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Test one credential. Always returns a verdict, never raises."""
    extra = extra or {}

    # Atlas is special: the CLI owns auth, so the probe runs `doctor`.
    if provider == "atlas":
        status, message, latency = await probe_atlas(secret, extra)
        return _verdict(status, message, latency)

    probe_fn = PROBES.get(provider)
    if probe_fn is None:
        return _verdict(
            "untested",
            "No automated check exists for this provider — it will be verified on first use.",
            0,
        )
    if not secret:
        return _verdict("invalid", "No key provided", 0)

    try:
        status, message, latency = await probe_fn(secret, extra)
    except Exception as exc:  # noqa: BLE001 — a probe must never break the request
        logger.warning("Probe for %s raised: %s", provider, exc)
        return _verdict("untested", f"Probe failed: {exc}"[:300], 0)
    return _verdict(status, message, latency)


def _verdict(status: CredentialStatus, message: str, latency_ms: int) -> dict[str, Any]:
    return {
        "status": status,
        "ok": status == "healthy",
        "message": message,
        "latency_ms": latency_ms,
    }

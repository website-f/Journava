"""API Vault — encryption, masking, and the test-before-save contract.

The properties that matter here are security properties, so they are asserted
rather than assumed: a stored secret must be unreadable without the key, must
never be returned by the API, and a key that fails its probe must not be quietly
recorded as healthy.
"""

from __future__ import annotations

import pytest

from app.core import vault, vault_probes

# --------------------------------------------------------------------------- #
# Encryption + masking
# --------------------------------------------------------------------------- #


def test_encryption_round_trip():
    secret = "sk-live-abcdefghijklmnop1234"
    token = vault.encrypt(secret)
    assert token != secret
    assert secret not in token
    assert vault.decrypt(token) == secret


def test_ciphertext_differs_between_calls():
    """Fernet includes a nonce, so identical secrets don't produce identical rows."""
    assert vault.encrypt("same-secret") != vault.encrypt("same-secret")


def test_decrypt_rejects_a_foreign_token(monkeypatch):
    """A token from another key must fail closed, not return garbage."""
    from cryptography.fernet import Fernet

    other = Fernet(Fernet.generate_key()).encrypt(b"secret").decode()
    assert vault.decrypt(other) is None


@pytest.mark.parametrize(
    ("secret", "expected"),
    [
        ("sk-1234567890abcd", "sk-…abcd"),
        ("short", "•••••"),
        ("", ""),
    ],
)
def test_masking_identifies_without_revealing(secret, expected):
    assert vault.mask(secret) == expected


def test_mask_never_leaks_the_middle():
    secret = "sk-supersecretvalue-9999"
    masked = vault.mask(secret)
    assert "supersecret" not in masked
    assert masked.startswith("sk-")
    assert masked.endswith("9999")


# --------------------------------------------------------------------------- #
# Catalogue
# --------------------------------------------------------------------------- #


def test_every_provider_has_a_known_category():
    for spec in vault.PROVIDERS.values():
        assert spec.category in vault.CATEGORIES, spec.slug


def test_keyless_providers_are_marked_configured():
    """Open-Meteo and friends need no key — the vault should say so, not nag."""
    for slug in ("open_meteo", "overpass", "nominatim", "gdelt"):
        assert vault.PROVIDERS[slug].keyless is True


def test_spec_serialises_for_the_ui():
    entry = vault.PROVIDERS["atlas"].as_dict()
    assert entry["slug"] == "atlas"
    assert entry["category_label"] == "Flights"
    assert "environment" in entry["extra_fields"]


def test_travel_providers_from_the_spec_are_present():
    """§9 names these; the vault is where their keys now live."""
    for slug in (
        "atlas",
        "amadeus",
        "hotelbeds",
        "expedia_rapid",
        "booking_com",
        "google_places",
        "foursquare",
        "yelp",
        "halaltrip",
        "maptiler",
        "youtube",
        "reddit",
        "stripe",
        "resend",
    ):
        assert slug in vault.PROVIDERS, slug


# --------------------------------------------------------------------------- #
# Probes
# --------------------------------------------------------------------------- #


async def test_probe_without_a_key_is_invalid_not_healthy():
    verdict = await vault_probes.probe("youtube", None, {})
    assert verdict["ok"] is False
    assert verdict["status"] == "invalid"


async def test_probe_for_unknown_provider_is_untested_not_ok():
    """No probe must never be reported as a pass."""
    verdict = await vault_probes.probe("expedia_rapid", "some-key", {})
    assert verdict["ok"] is False
    assert verdict["status"] == "untested"
    assert "No automated check" in verdict["message"]


async def test_amadeus_probe_requires_a_client_id():
    verdict = await vault_probes.probe("amadeus", "secret-only", {})
    assert verdict["status"] == "invalid"
    assert "client_id" in verdict["message"]


async def test_reddit_probe_requires_a_client_id():
    verdict = await vault_probes.probe("reddit", "secret-only", {})
    assert verdict["status"] == "invalid"


async def test_atlas_probe_reports_missing_cli(monkeypatch):
    """A missing CLI is a configuration problem, reported as such."""
    from app.tools import atlas_skill

    async def missing(*_args, **_kwargs):
        raise atlas_skill.AtlasSkillError("atlas-flight not found")

    monkeypatch.setattr(atlas_skill, "doctor", missing)
    verdict = await vault_probes.probe("atlas", None, {})
    assert verdict["ok"] is False
    assert "not found" in verdict["message"]


async def test_atlas_probe_distinguishes_unauthorised_from_broken(monkeypatch):
    from app.tools import atlas_skill
    from app.tools.atlas_skill import AtlasEnvelope

    async def unauthorised(*_args, **_kwargs):
        return AtlasEnvelope(
            {
                "status": "action_required",
                "code": "AUTHORIZATION_REQUIRED",
                "message": "authorise in the browser",
                "data": {"environment": "sandbox"},
            }
        )

    monkeypatch.setattr(atlas_skill, "doctor", unauthorised)
    verdict = await vault_probes.probe("atlas", None, {})
    assert verdict["status"] == "invalid"
    assert "auth login" in verdict["message"]
    assert "sandbox" in verdict["message"]


async def test_atlas_probe_healthy(monkeypatch):
    from app.tools import atlas_skill
    from app.tools.atlas_skill import AtlasEnvelope

    async def healthy(*_args, **_kwargs):
        return AtlasEnvelope(
            {
                "status": "success",
                "code": "DOCTOR_OK",
                "message": "ok",
                "data": {"environment": "sandbox"},
            }
        )

    monkeypatch.setattr(atlas_skill, "doctor", healthy)
    verdict = await vault_probes.probe("atlas", "token", {})
    assert verdict["ok"] is True
    assert "sandbox" in verdict["message"]


def test_http_status_classification():
    classify = vault_probes._classify_http  # noqa: SLF001 — unit under test

    assert classify(200, "")[0] == "healthy"
    assert classify(401, "bad key")[0] == "invalid"
    assert classify(403, "forbidden")[0] == "invalid"
    assert classify(429, "slow down")[0] == "rate_limited"
    # A provider outage is not the operator's key being wrong.
    assert classify(503, "unavailable")[0] == "untested"


def test_llm_error_classification():
    classify = vault_probes._classify_llm_error  # noqa: SLF001

    assert classify(Exception("Invalid API Key")) == "invalid"
    assert classify(Exception("rate limit exceeded")) == "rate_limited"
    assert classify(Exception("insufficient quota")) == "limit_reached"
    assert classify(Exception("Missing credentials")) == "invalid"
    assert classify(Exception("connection reset")) == "untested"


# --------------------------------------------------------------------------- #
# Resolution
# --------------------------------------------------------------------------- #


async def test_resolve_falls_back_to_env(monkeypatch):
    """An existing .env deployment keeps working while the vault fills up."""
    vault.invalidate_cache()
    monkeypatch.setattr(vault.settings, "youtube_api_key", "env-youtube-key")

    resolved = await vault.resolve("youtube")
    assert resolved is not None
    assert resolved["secret"] == "env-youtube-key"
    vault.invalidate_cache()


async def test_resolve_returns_none_when_nothing_configured(monkeypatch):
    vault.invalidate_cache()
    monkeypatch.setattr(vault.settings, "youtube_api_key", None)
    assert await vault.resolve("youtube") is None
    vault.invalidate_cache()


async def test_catalogue_marks_env_sourced_credentials(monkeypatch):
    vault.invalidate_cache()
    monkeypatch.setattr(vault.settings, "maptiler_key", "env-maptiler")

    entries = {entry["slug"]: entry for entry in await vault.catalogue()}
    assert entries["maptiler"]["configured"] is True
    assert entries["maptiler"]["source"] == "env"
    # Keyless services are configured without any credential at all.
    assert entries["open_meteo"]["configured"] is True
    assert entries["open_meteo"]["source"] is None
    vault.invalidate_cache()

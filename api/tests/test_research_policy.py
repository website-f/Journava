"""Research access policy and currency normalisation.

Two things are asserted here because both are easy to erode silently:

1. **Access boundaries.** §8 commits us to honouring `robots.txt`, and §15 to
   never bypassing a captcha. Camoufox's fingerprint resistance makes an ordinary
   browser hard to *misclassify* — it is not a licence to walk through a door a
   site has closed. A disallowed site must stay link-only, and a challenge page
   must be reported, not worked around.

2. **One currency.** Comparing a USD fare against an MYR fare and calling one
   "cheapest" is meaningless, so anything off-target is converted — and says so.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.agents.flight import FlightAgent
from app.tools import camofox, flight_sites

DEPART = date(2026, 11, 6)


# --------------------------------------------------------------------------- #
# Access policy
# --------------------------------------------------------------------------- #


def test_robots_disallowed_sites_are_never_crawl_targets():
    """Google Flights, Kayak and Expedia disallow their results paths."""
    targets = flight_sites.build_targets("KUL", "BKI", DEPART, limit=10)
    slugs = {target["slug"] for target in targets}
    assert "google_flights" not in slugs
    assert "kayak" not in slugs
    assert "expedia" not in slugs


def test_disallowed_sites_are_still_offered_as_links():
    """Linking is not crawling — omitting them would only hurt the traveller."""
    link_only = {site.slug for site in flight_sites.link_only_sites("KUL", "BKI")}
    assert {"google_flights", "kayak", "expedia"} <= link_only


def test_every_link_only_site_is_marked_uncrawlable():
    for site in flight_sites.link_only_sites("KUL", "BKI"):
        assert site.crawlable is False


def test_link_only_options_say_why_they_were_not_read():
    """A gap the traveller can see is better than a silent omission."""
    options = FlightAgent._link_only_options("KUL", "BKI", "2026-11-06")  # noqa: SLF001
    assert options
    for option in options:
        assert option["raw"]["kind"] == "link_only"
        assert option["price_amount"] is None
        assert option["bookable"] is False
        assert "robots.txt" in option["reasoning"]
        assert option["source_url"]


@pytest.mark.parametrize(
    "snapshot",
    [
        "Are you a person or a robot? Please don't take this personally",
        "Performing security verification",
        "Access denied",
        "Checking your browser before accessing",
        "Please complete the CAPTCHA to continue",
    ],
)
def test_bot_challenges_are_detected(snapshot):
    assert camofox.detect_challenge(snapshot) is not None


def test_a_real_fare_page_is_not_mistaken_for_a_challenge():
    snapshot = "AirAsia AK5104\n20:15 KUL - 22:55 BKI\n2h 40m nonstop\nRM 214"
    assert camofox.detect_challenge(snapshot) is None


def test_challenge_prone_sites_are_demoted_not_removed():
    """They sometimes let a plain visit through, so they are tried — last."""
    ranked = flight_sites.crawlable_sites("KUL", "BKI", limit=len(flight_sites.SITES))
    slugs = [site.slug for site in ranked]
    assert "skyscanner" in slugs
    # Sites that reliably answer must be attempted before ones that usually refuse.
    assert slugs.index("trip_com") < slugs.index("skyscanner")


# --------------------------------------------------------------------------- #
# Currency
# --------------------------------------------------------------------------- #


def test_currency_reaches_the_site_urls():
    """A site that honours a currency parameter must actually receive it."""
    targets = flight_sites.build_targets("KUL", "BKI", DEPART, currency="MYR", limit=8)
    by_slug = {target["slug"]: target["url"] for target in targets}
    assert "curr=MYR" in by_slug["trip_com"]
    assert "currency=MYR" in by_slug["momondo"]


def test_a_different_currency_is_honoured():
    targets = flight_sites.build_targets("KUL", "BKI", DEPART, currency="SGD", limit=8)
    by_slug = {target["slug"]: target["url"] for target in targets}
    assert "curr=SGD" in by_slug["trip_com"]


async def test_foreign_fares_are_converted_and_labelled(monkeypatch):
    """A converted fare must carry its original, not quietly become MYR."""
    from app.agents import flight as flight_module

    async def fake_rates(base):
        assert base == "MYR"
        return {"USD": 0.22}  # 1 MYR ≈ 0.22 USD

    monkeypatch.setattr(flight_module, "fx_rates", fake_rates)

    fares = [
        {"price_amount": 96.0, "price_currency": "USD", "site": "Skiplagged"},
        {"price_amount": 237.0, "price_currency": "MYR", "site": "Trip.com"},
    ]
    converted_fares, count = await FlightAgent()._normalise_currency(fares, "MYR")  # noqa: SLF001

    assert count == 1
    usd_origin = next(f for f in converted_fares if f["site"] == "Skiplagged")
    assert usd_origin["price_currency"] == "MYR"
    assert usd_origin["price_amount"] == pytest.approx(436.36, abs=0.1)
    assert usd_origin["converted_from"] == {"currency": "USD", "amount": 96.0}

    # An already-correct fare is left completely alone.
    myr = next(f for f in converted_fares if f["site"] == "Trip.com")
    assert myr["price_amount"] == 237.0
    assert "converted_from" not in myr


async def test_unconvertible_fares_keep_their_own_currency(monkeypatch):
    """Relabelling without converting would be a wrong number, not a gap."""
    from app.agents import flight as flight_module

    async def no_rates(_base):
        return None

    monkeypatch.setattr(flight_module, "fx_rates", no_rates)

    fares = [{"price_amount": 96.0, "price_currency": "USD", "site": "Skiplagged"}]
    result, count = await FlightAgent()._normalise_currency(fares, "MYR")  # noqa: SLF001

    assert count == 0
    assert result[0]["price_currency"] == "USD"
    assert result[0]["price_amount"] == 96.0


async def test_conversion_is_a_no_op_when_everything_matches(monkeypatch):
    from app.agents import flight as flight_module

    async def unexpected(_base):  # pragma: no cover - must not be called
        raise AssertionError("FX should not be fetched when nothing needs converting")

    monkeypatch.setattr(flight_module, "fx_rates", unexpected)

    fares = [{"price_amount": 237.0, "price_currency": "MYR", "site": "Trip.com"}]
    result, count = await FlightAgent()._normalise_currency(fares, "MYR")  # noqa: SLF001
    assert count == 0
    assert result[0]["price_amount"] == 237.0

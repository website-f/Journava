"""Flight source tagging, airport resolution and Atlas envelope handling.

The rule being protected: a fare an agent read on a web page is a different kind
of claim from a fare the booking API will hold. They must never be presented
identically, and the crawled one must always carry the page it came from.
"""

from __future__ import annotations

import pytest

from app.agents.flight import FlightAgent, _airport_code, _is_red_eye, _stops_label
from app.tools import atlas_skill, fare_extract
from app.tools.atlas_skill import AtlasEnvelope

# --------------------------------------------------------------------------- #
# Airport resolution
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("klia", "KUL"),
        ("KLIA", "KUL"),
        ("Kuala Lumpur", "KUL"),
        ("bki", "BKI"),
        ("Kota Kinabalu", "BKI"),
        ("kk", "BKI"),
        ("Venice", "VCE"),
        ("SIN", "SIN"),
        ("Kuala Lumpur (KUL)", "KUL"),
        (None, None),
    ],
)
def test_airport_code_resolution(text, expected):
    """Atlas needs IATA codes; travellers type place names."""
    assert _airport_code(text) == expected


def test_unknown_place_passes_through():
    """An unrecognised place is not mangled — the LLM's value still gets a turn."""
    assert _airport_code("Somewhereville") == "Somewhereville"


@pytest.mark.parametrize(
    ("time", "expected"),
    [("23:40", True), ("02:15", True), ("05:59", True), ("06:00", False), ("20:15", False)],
)
def test_red_eye_detection(time, expected):
    assert _is_red_eye(time) is expected


def test_red_eye_without_a_time_is_not_assumed():
    assert _is_red_eye(None) is False
    assert _is_red_eye("evening") is False


@pytest.mark.parametrize(
    ("stops", "label"), [(0, "direct"), (1, "1 stop"), (2, "2 stops"), (None, "direct")]
)
def test_stops_label(stops, label):
    assert _stops_label(stops) == label


# --------------------------------------------------------------------------- #
# Atlas envelope
# --------------------------------------------------------------------------- #


def test_envelope_classification():
    auth = AtlasEnvelope({"status": "action_required", "code": "AUTHORIZATION_REQUIRED"})
    assert auth.is_auth_problem is True
    assert auth.needs_action is True
    assert auth.ok is False

    empty = AtlasEnvelope({"status": "success", "code": "SEARCH_NO_RESULTS"})
    assert empty.is_empty_result is True

    good = AtlasEnvelope({"status": "success", "code": "FLIGHT_SEARCHED", "data": {"offers": []}})
    assert good.ok is True
    assert good.is_auth_problem is False


def test_envelope_parsing_tolerates_installer_noise():
    """Some hosts print setup chatter before the JSON; the envelope still wins."""
    noisy = (
        'Installing atlas-flight...\nResolved 1 package\n{"status":"success","code":"DOCTOR_OK"}'
    )
    parsed = atlas_skill._parse_envelope(noisy)  # noqa: SLF001 — unit under test
    assert parsed is not None
    assert parsed.code == "DOCTOR_OK"


def test_envelope_parsing_returns_none_for_garbage():
    assert atlas_skill._parse_envelope("not json at all") is None  # noqa: SLF001


# --------------------------------------------------------------------------- #
# Offer normalisation
# --------------------------------------------------------------------------- #


def _search_envelope(price_status: str = "verified") -> AtlasEnvelope:
    return AtlasEnvelope(
        {
            "status": "success",
            "code": "FLIGHT_SEARCHED",
            "data": {
                "search_id": "srch_abc",
                "offers": [
                    {
                        "offer_id": "off_123",
                        "currency": "MYR",
                        "total_price": 214.0,
                        "transaction_fee_total": 4.0,
                        "price_status": price_status,
                        "bookable": True,
                        "ancillary_supported": ["baggage"],
                        "segments": [
                            {
                                "departure_airport": "KUL",
                                "arrival_airport": "BKI",
                                "departure_time": "2026-11-06T20:15",
                                "arrival_time": "2026-11-06T22:55",
                                "carrier": "AK",
                                "flight_number": "5104",
                                "duration_minutes": 160,
                                "direction": "outbound",
                            }
                        ],
                    }
                ],
            },
        }
    )


def test_normalized_offer_is_tagged_atlas():
    options = atlas_skill.normalize_offers(_search_envelope())
    assert len(options) == 1
    option = options[0]
    assert option["source"] == "atlas"
    assert option["id"] == "off_123"
    assert option["raw"]["offer_id"] == "off_123"
    assert option["raw"]["search_id"] == "srch_abc"
    assert option["raw"]["stops"] == 0
    assert option["raw"]["duration_hours"] == pytest.approx(2.7, abs=0.05)
    assert option["raw"]["baggage_included"] is True


def test_only_verified_price_status_earns_the_badge():
    """A reference fare is not a confirmed one."""
    assert atlas_skill.normalize_offers(_search_envelope("verified"))[0]["verified"] is True
    assert atlas_skill.normalize_offers(_search_envelope("current"))[0]["verified"] is False
    assert atlas_skill.normalize_offers(_search_envelope("reference"))[0]["verified"] is False


def test_reference_fare_says_so_in_its_reasoning():
    option = atlas_skill.normalize_offers(_search_envelope("reference"))[0]
    assert "verify before booking" in option["reasoning"]


def test_offer_without_segments_is_skipped():
    envelope = AtlasEnvelope(
        {
            "status": "success",
            "code": "FLIGHT_SEARCHED",
            "data": {
                "offers": [{"offer_id": "x", "currency": "MYR", "total_price": 1, "segments": []}]
            },
        }
    )
    assert atlas_skill.normalize_offers(envelope) == []


# --------------------------------------------------------------------------- #
# Camofox research fares
# --------------------------------------------------------------------------- #


SNAPSHOT = """
Cheapest flights KUL to BKI
AirAsia from RM 214 one way
Malaysia Airlines MYR 389
Batik Air RM 275 return available
Terms apply. Save RM 5 with the app.
"""


SNAPSHOT_BLOCKS = """
AirAsia
20:15 KUL - 22:55 BKI
2h 40m  nonstop
RM 214
Batik Air Malaysia
07:30 KUL - 10:15 BKI
2h 45m  nonstop
RM 289
Terms apply. Save RM 5 with the app.
"""


def test_research_fares_carry_their_source_url():
    """A crawled price the traveller cannot check is barely better than a guess."""
    fares = fare_extract.extract_fares(
        SNAPSHOT_BLOCKS,
        source_url="https://www.cheapflights.com/flights/KUL-BKI/2026-11-06",
        site_name="Cheapflights",
    )
    assert fares
    for fare in fares:
        assert fare["source_url"] == "https://www.cheapflights.com/flights/KUL-BKI/2026-11-06"
        assert fare["site"] == "Cheapflights"


def test_research_fares_reject_implausible_numbers():
    """ "Save RM 5 with the app" is page furniture, not a fare."""
    fares = fare_extract.extract_fares(
        SNAPSHOT_BLOCKS, source_url="https://example.com", site_name="X"
    )
    amounts = [fare["price_amount"] for fare in fares]
    assert 5 not in amounts
    assert all(30 <= amount <= 40_000 for amount in amounts)


def test_a_promo_line_does_not_kill_the_whole_block():
    """A banner sits beside results, not instead of them."""
    fares = fare_extract.extract_fares(
        SNAPSHOT_BLOCKS, source_url="https://example.com", site_name="X"
    )
    assert {fare["price_amount"] for fare in fares} == {214.0, 289.0}


def test_airline_is_attributed_by_position_not_dict_order():
    """The carrier heading a block wins over one mentioned later."""
    fares = fare_extract.extract_fares(
        SNAPSHOT_BLOCKS, source_url="https://example.com", site_name="X"
    )
    by_price = {fare["price_amount"]: fare["airline"] for fare in fares}
    assert by_price[214.0] == "AirAsia"
    assert by_price[289.0] == "Batik Air"


def test_a_lone_number_is_not_a_fare():
    """A price needs corroborating flight detail, or it is a coincidence.

    This exact text appeared on a DuckDuckGo results page and was previously
    reported as a KLM fare for a Kuala Lumpur–Kota Kinabalu search.
    """
    snapshot = "KLM Royal Dutch Airlines\nBook flights from USD 56\nExplore destinations"
    assert fare_extract.extract_fares(snapshot, site_name="DuckDuckGo") == []


def test_research_fares_are_deduplicated_by_price():
    repeated = "AirAsia 20:15 nonstop RM 214\n" * 20
    fares = fare_extract.extract_fares(repeated, source_url="https://example.com", site_name="X")
    assert len(fares) == 1


def test_summarise_names_the_cheapest_site():
    """The point of comparing sites is being able to say which one won."""
    fares = [
        {
            "price_amount": 289.0,
            "price_currency": "MYR",
            "site": "Skyscanner",
            "source_url": "https://s",
        },
        {
            "price_amount": 214.0,
            "price_currency": "MYR",
            "site": "Cheapflights",
            "source_url": "https://c",
        },
    ]
    summary = fare_extract.summarise_sites(fares)
    assert summary["cheapest_site"] == "Cheapflights"
    assert summary["cheapest_amount"] == 214.0
    assert summary["sites_with_fares"] == 2


# --------------------------------------------------------------------------- #
# Source URL extraction
# --------------------------------------------------------------------------- #


def test_extract_sources_drops_navigation_noise():
    from app.tools.camofox import extract_sources

    snapshot = (
        "Results\n"
        "https://www.google.com/search?q=flights\n"
        "https://accounts.google.com/signin\n"
        "https://www.skyscanner.net/routes/kul/bki\n"
        "https://www.kayak.com/flights/KUL-BKI\n"
        "https://www.skyscanner.net/routes/kul/bki\n"
    )
    sources = extract_sources(snapshot)
    assert sources == [
        "https://www.skyscanner.net/routes/kul/bki",
        "https://www.kayak.com/flights/KUL-BKI",
    ]


def test_extract_sources_handles_empty_input():
    from app.tools.camofox import extract_sources

    assert extract_sources("") == []
    assert extract_sources(None) == []  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# End-to-end shaping
# --------------------------------------------------------------------------- #


@pytest.mark.usefixtures("stub_llm", "no_network", "no_cache", "memory_brain")
async def test_agent_labels_llm_options_and_warns():
    """With no live source, options are tagged `llm` and the warning says so."""
    from app.agents.schemas import TravelerProfile, TripRequest

    result = await FlightAgent()(
        TripRequest(goal="flights", origin="KUL", destination="BKI"),
        TravelerProfile(),
    )
    assert result.options
    assert {o.source for o in result.options} <= {"llm", "mock"}
    assert all(o.bookable is False for o in result.options)
    assert any("not held fares" in w or "placeholder" in w for w in result.warnings)


@pytest.mark.usefixtures("stub_llm", "no_network", "no_cache", "memory_brain")
async def test_halal_never_filters_flights():
    """§7.5: dietary preference adds MOML, it does not remove inventory."""
    from app.agents.schemas import TravelerProfile, TripRequest

    plain = await FlightAgent()(
        TripRequest(goal="flights", origin="KUL", destination="BKI"),
        TravelerProfile(),
    )
    halal = await FlightAgent()(
        TripRequest(goal="flights", origin="KUL", destination="BKI"),
        TravelerProfile(halal_required=True),
    )
    assert len(halal.options) == len(plain.options)
    assert halal.applied_preferences["halal_required"] == "not_applicable"
    assert halal.data["special_requests"]["meal_code"] == "MOML"

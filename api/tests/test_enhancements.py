"""Regression tests for the enhancements shipped this cycle.

Every bug that slipped through recently was in a PURE function with no test:
the flight-agent crash on empty Atlas, the ranking dedup/cap, the goal parser's
bare-city fallback, the critic re-rank, the demo-trip guard, the itinerary day
base. These lock that behaviour in. All offline — no network, no DB.
"""

from __future__ import annotations

from datetime import date

from app.agents.schemas import Option, TripRequest


# --------------------------------------------------------------------------- #
# Goal parser — duration + bare-city fallback
# --------------------------------------------------------------------------- #
def test_duration_days_parsing():
    from app.agents.goal_parser import _duration_days

    assert _duration_days("3 days in osaka") == 3
    assert _duration_days("5 nights in bali") == 6  # 5 nights on the ground = 6 days
    assert _duration_days("2 weeks in europe") == 14
    assert _duration_days("trip to tokyo") is None


def test_bare_city_fallback_resolves_chengdu():
    # "3 days chengdu China 2 pax" has no "to/in" — must still resolve the city,
    # not fall through to a country guess (which planned Shanghai).
    from app.agents.goal_parser import parse_goal

    assert parse_goal("3 days chengdu China 2 pax").get("destination") == "CTU"


def test_bare_city_fallback_skips_origin():
    from app.agents.goal_parser import parse_goal

    # "from KLIA to Tokyo" — origin must not be mistaken for the destination.
    parsed = parse_goal("4 days from KLIA to Tokyo")
    assert parsed.get("destination") in ("TYO", "NRT", "HND")  # a Tokyo gateway
    assert parsed.get("origin") == "KUL"


def test_effective_days():
    assert TripRequest(goal="x", duration_days=3).effective_days == 3
    assert (
        TripRequest(goal="x", duration_days=3, start_date=date(2026, 9, 20), end_date=date(2026, 9, 23)).effective_days
        == 4  # explicit dates win
    )
    assert TripRequest(goal="x").effective_days == 7  # default


# --------------------------------------------------------------------------- #
# Flight ranking — dedup, cap, date-flex
# --------------------------------------------------------------------------- #
def _flight(id_, price, *, carrier="AK6114", dep="202611150740", stops=0, source="atlas", bookable=True):
    return Option(
        id=id_, kind="flight", title=f"{carrier} KUL-NRT", price_amount=price,
        price_currency="MYR", source=source, bookable=bookable,
        raw={"flight_numbers": [carrier], "departure_time": dep, "stops": stops, "duration_hours": 7},
    )


def test_dedupe_cross_source_merges_same_flight():
    from app.agents.flight import FlightAgent

    opts = [
        _flight("a", 300, source="atlas", bookable=True),
        _flight("b", 280, source="camofox", bookable=False),  # same carrier+dep+stops, cheaper OTA
        _flight("c", 500, carrier="MH370", dep="202611151200"),  # genuinely different flight
    ]
    out = FlightAgent._dedupe_cross_source(opts)
    assert len(out) == 2  # the AK pair collapsed, MH kept
    kept = next(o for o in out if o.raw.get("flight_numbers") == ["AK6114"])
    assert kept.bookable is True  # kept the bookable (Atlas) card
    assert kept.raw.get("also_on")  # recorded the cheaper OTA price


def test_cap_options_keeps_bucket_winners():
    from app.agents.flight import FlightAgent

    opts = [_flight(str(i), 200 + i, dep=f"20261115{i:02d}00") for i in range(25)]
    ranking = {"cheapest": "24", "best_value": "0", "best_time": "0", "cheapest_with_baggage": "0"}
    out = FlightAgent._cap_options(opts, ranking, limit=18)
    ids = {o.id for o in out}
    assert len(out) <= 19  # capped near the limit
    assert "24" in ids  # the out-of-slice bucket winner was kept


def test_flex_trip_dates_skips_past_and_keeps_span():
    from app.agents.flight import _flex_trip_dates

    future = (date.today().replace(year=date.today().year + 1)).isoformat()
    ret = (date.fromisoformat(future).replace(day=min(28, date.fromisoformat(future).day))).isoformat()
    pairs = _flex_trip_dates(future, ret)
    assert pairs  # produced nearby dates
    assert all(d >= date.today().isoformat() for d, _ in pairs)  # never the past


# --------------------------------------------------------------------------- #
# Critic — deterministic re-rank by priority
# --------------------------------------------------------------------------- #
def test_critic_rerank_by_priority():
    from app.graph.supervisor import _rerank_by_priority

    opts = [
        {"id": "x", "price_amount": 900, "halal_confidence": "certified", "raw": {"stops": 0, "rating": 4.8}},
        {"id": "y", "price_amount": 300, "halal_confidence": "unverified", "raw": {"stops": 1, "rating": 3.9}},
    ]
    assert _rerank_by_priority(opts, "budget")[0]["id"] == "y"   # cheapest first
    assert _rerank_by_priority(opts, "halal")[0]["id"] == "x"    # certified first
    assert _rerank_by_priority(opts, "nonstop")[0]["id"] == "x"  # fewest stops first
    assert _rerank_by_priority(opts, "rating")[0]["id"] == "x"   # highest rated first
    assert _rerank_by_priority(opts, "none") == opts             # no-op


# --------------------------------------------------------------------------- #
# Itinerary base + demo-trip guard
# --------------------------------------------------------------------------- #
def test_naive_schedule_is_one_based():
    from app.brain.trip_store import _naive_schedule

    items = _naive_schedule([{"title": "A", "kind": "activity"}, {"title": "B", "kind": "restaurant"}], days=3)
    days = {i["day_index"] for i in items}
    assert min(days) == 1 and 0 not in days  # never "Day 0"


def test_is_demo_trip_guard():
    from app.main import _is_demo_trip

    assert _is_demo_trip({"_demo": True}) is True
    assert _is_demo_trip(
        {"chief": {"summary": "7-day Venice trip for 2 — food", "data": {"destination": "Venice, Italy", "origin": "Kuala Lumpur (KUL)"}}}
    ) is True
    assert _is_demo_trip({"chief": {"data": {"destination": "Osaka, Japan"}}}) is False
    assert _is_demo_trip(None) is False


# --------------------------------------------------------------------------- #
# Proactive trip-countdown notifications (pure helpers — dedupe-safe scheduler)
# --------------------------------------------------------------------------- #
def test_trip_start_date_parsing():
    from app.bookings import _trip_start_date

    assert _trip_start_date({"chief": {"data": {"start_date": "2026-09-10"}}}).isoformat() == "2026-09-10"
    assert _trip_start_date({"chief": {"data": {"start_date": "2026-09-10T00:00:00"}}}).isoformat() == "2026-09-10"
    assert _trip_start_date({"chief": {"data": {"start_date": None}}}) is None  # no dates → skip, don't mark
    assert _trip_start_date({"chief": {"data": {"start_date": "soon"}}}) is None  # unparseable → skip
    assert _trip_start_date({}) is None


def test_countdown_phrase():
    from app.bookings import _countdown_phrase

    assert "today" in _countdown_phrase(0)
    assert "tomorrow" in _countdown_phrase(1)
    assert "3 days" in _countdown_phrase(3)


def test_day_one_highlight():
    from app.bookings import _day_one_highlight

    assert _day_one_highlight({"itinerary": {"items": [{"title": "Senso-ji Temple"}]}}) == "Senso-ji Temple"
    assert _day_one_highlight({"itinerary": {"items": [{"title": "  "}, {"name": "Ramen crawl"}]}}) == "Ramen crawl"
    assert _day_one_highlight({"itinerary": {"items": []}}) is None
    assert _day_one_highlight({}) is None

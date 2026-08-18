"""Deterministic goal parsing.

This exists because the LLM parse is not always available, and *"cheap flights
from KLIA to BKI on 6 November night"* is a sentence that does not need a model.
When the parse failed, every specialist planned for `destination=None` and the
traveller got a placeholder for "KUL → unknown".

The tests lean hard on the ambiguous cases, because that is where a naive parser
does damage: "6 november" is a date not six travellers, "7-day" is a duration not
seven people, and "a 7-day trip" is not one traveller.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.agents.goal_parser import parse_goal

TODAY = date(2026, 8, 18)


def parse(goal: str) -> dict:
    return parse_goal(goal, today=TODAY)


# --------------------------------------------------------------------------- #
# The query that motivated this module
# --------------------------------------------------------------------------- #


def test_the_motivating_query():
    result = parse("get me cheap flights from klia to bki on 6th november night")
    assert result["origin"] == "KUL"
    assert result["destination"] == "BKI"
    assert result["start_date"] == "2026-11-06"
    assert result["preferred_departure_window"]["label"] == "night"
    # Crucially: "6th november" is a date, not a party of six.
    assert "travellers" not in result


# --------------------------------------------------------------------------- #
# Route
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("goal", "origin", "destination"),
    [
        ("flights from klia to bki", "KUL", "BKI"),
        ("KUL to BKI", "KUL", "BKI"),
        ("KUL-BKI", "KUL", "BKI"),
        ("kuala lumpur to kota kinabalu", "KUL", "BKI"),
        # Mixed code + city name — the case a city-only pattern misses.
        ("flights KUL to Tokyo", "KUL", "NRT"),
        ("from Singapore to Bali", "SIN", "DPS"),
    ],
)
def test_route_extraction(goal, origin, destination):
    result = parse(goal)
    assert result.get("origin") == origin
    assert result.get("destination") == destination


@pytest.mark.parametrize(
    ("goal", "destination"),
    [
        ("hotel in kota kinabalu", "BKI"),
        ("7-day Venice trip", "VCE"),
        ("things to do in Bali", "DPS"),
        ("visiting Tokyo in spring", "NRT"),
    ],
)
def test_destination_only(goal, destination):
    assert parse(goal).get("destination") == destination


def test_same_place_is_not_a_route():
    """ "KUL to KUL" is a typo, not a journey."""
    result = parse("flights from KUL to KUL")
    assert "origin" not in result or result.get("destination") != result.get("origin")


def test_filler_words_are_not_airport_codes():
    """ "get me to bki" must not read "get" as the origin."""
    result = parse("get me to bki")
    assert result.get("destination") == "BKI"
    assert result.get("origin") is None


# --------------------------------------------------------------------------- #
# Dates
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("goal", "expected"),
    [
        ("flights on 6th november", "2026-11-06"),
        ("flights on november 6", "2026-11-06"),
        ("flights on 6 nov", "2026-11-06"),
        ("depart 2026-12-20", "2026-12-20"),
        ("leaving 20/12", "2026-12-20"),
        ("tomorrow", "2026-08-19"),
    ],
)
def test_date_extraction(goal, expected):
    assert parse(goal).get("start_date") == expected


def test_a_past_date_rolls_to_next_year():
    """ "6 january" in August means next January, not eight months ago."""
    assert parse("flights on 6 january")["start_date"] == "2027-01-06"


def test_impossible_date_is_ignored():
    assert "start_date" not in parse("flights on 45 november")


def test_duration_sets_the_end_date():
    result = parse("7-day trip to Venice from 1 september")
    assert result["start_date"] == "2026-09-01"
    # A 7-day trip spans 7 days: the 1st through the 7th.
    assert result["end_date"] == "2026-09-07"


def test_nights_count_differently_from_days():
    result = parse("3 nights in kota kinabalu from 1 september")
    assert result["end_date"] == "2026-09-04"


# --------------------------------------------------------------------------- #
# Party size — the most ambiguous field
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("goal", "expected"),
    [
        ("trip for 2", 2),
        ("flights for 4 people", 4),
        ("for two adults", 2),
        ("3 pax to bali", 3),
        ("solo trip to bali", 1),
        ("a couple going to venice", 2),
    ],
)
def test_traveller_count(goal, expected):
    assert parse(goal).get("travellers") == expected


@pytest.mark.parametrize(
    "goal",
    [
        "flights on 6 november",  # a date
        "a 7-day trip to venice",  # a duration, and "a" is not a headcount
        "budget RM8000",  # money
        "max 1 connection",  # a constraint
        "3 nights in bali",  # nights, not people
    ],
)
def test_numbers_that_are_not_party_sizes(goal):
    assert "travellers" not in parse(goal)


def test_a_seven_day_trip_for_two_reads_both():
    result = parse("Plan a 7-day Venice trip for 2, budget RM8,000")
    assert result["travellers"] == 2
    assert result["budget_amount"] == 8000.0


# --------------------------------------------------------------------------- #
# Budget
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("goal", "amount", "currency"),
    [
        ("budget RM8,000", 8000.0, "MYR"),
        ("budget of RM 250", 250.0, "MYR"),
        ("under $500", 500.0, "USD"),
        ("max 1200 EUR", 1200.0, "EUR"),
        ("budget 8k", 8000.0, None),
        ("around SGD 400", 400.0, "SGD"),
    ],
)
def test_budget_extraction(goal, amount, currency):
    result = parse(goal)
    assert result.get("budget_amount") == amount
    if currency:
        assert result.get("budget_currency") == currency


@pytest.mark.parametrize(
    "goal",
    [
        "flights on 6 november",  # a date is not a budget
        "for 2 people",  # a headcount is not a budget
        "max 1 connection",  # small numbers are not money
    ],
)
def test_things_that_are_not_budgets(goal):
    assert "budget_amount" not in parse(goal)


# --------------------------------------------------------------------------- #
# Preferences
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("goal", "label"),
    [
        ("night flight to bki", "night"),
        ("evening departure", "evening"),
        ("early morning flight", "early morning"),
        ("avoid red eye", "red eye"),
    ],
)
def test_time_window(goal, label):
    assert parse(goal)["preferred_departure_window"]["label"] == label


@pytest.mark.parametrize(
    ("goal", "stops"),
    [
        ("direct flights to bali", 0),
        ("non-stop to tokyo", 0),
        ("max 1 connection", 1),
        ("maximum 2 stops", 2),
    ],
)
def test_max_connections(goal, stops):
    assert parse(goal)["max_connections"] == stops


@pytest.mark.parametrize(
    ("goal", "pace"),
    [
        ("relaxed 4 days in KK", "relaxed"),
        ("packed itinerary, see everything", "packed"),
        ("balanced pace please", "balanced"),
    ],
)
def test_pace(goal, pace):
    assert parse(goal)["pace"] == pace


def test_interests():
    result = parse("we love food and culture, plus some hiking")
    assert set(result["interests_detected"]) >= {"food", "culture", "nature"}


# --------------------------------------------------------------------------- #
# Robustness
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("goal", ["", "   ", "asdfghjkl", "???"])
def test_unparseable_input_returns_empty_not_garbage(goal):
    """A confident wrong guess is worse than an honest blank."""
    assert parse(goal) == {} or "destination" not in parse(goal)


def test_parser_never_raises_on_odd_input():
    for goal in ["🛫🛬", "a" * 5000, "1/1/1", "to to to", "RM RM RM", "-- --"]:
        parse(goal)  # must not raise

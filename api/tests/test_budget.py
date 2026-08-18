"""Currency conversion direction.

`frankfurter.rates(base=X)` returns "1 X buys N of this currency", so converting
*into* X divides by the rate. The original code multiplied, which turned 100 EUR
into 20 MYR instead of 500 — a 25× understatement that quietly made every
non-MYR trip look affordable.
"""

from __future__ import annotations

import pytest

from app.agents.budget import BudgetAgent, _convert

# 1 MYR ≈ 0.20 EUR ≈ 0.22 USD
FX_BASE_MYR = {"EUR": 0.20, "USD": 0.22, "SGD": 0.30}


def test_converts_into_the_base_currency():
    assert _convert(100, "EUR", FX_BASE_MYR, "MYR") == pytest.approx(500.0)
    assert _convert(100, "USD", FX_BASE_MYR, "MYR") == pytest.approx(454.55, abs=0.01)


def test_same_currency_is_identity():
    assert _convert(100, "MYR", FX_BASE_MYR, "MYR") == 100.0
    assert _convert(100, "myr", FX_BASE_MYR, "MYR") == 100.0


def test_round_trip_is_stable():
    """Converting out and back must land where it started."""
    myr = _convert(100, "EUR", FX_BASE_MYR, "MYR")
    back = myr * FX_BASE_MYR["EUR"]
    assert back == pytest.approx(100.0, abs=0.01)


@pytest.mark.parametrize(
    ("value", "currency", "fx"),
    [
        (None, "EUR", FX_BASE_MYR),  # nothing to convert
        (100, None, FX_BASE_MYR),  # unknown source currency
        (100, "EUR", None),  # rates unavailable
        (100, "XYZ", FX_BASE_MYR),  # currency not in the table
        (100, "EUR", {"EUR": 0.0}),  # zero rate must not divide
    ],
)
def test_degrades_without_dividing_by_zero(value, currency, fx):
    """A missing or zero rate returns the value unchanged, never raises."""
    result = _convert(value, currency, fx, "MYR")
    assert result == (0.0 if value is None else float(value))


def test_aggregate_uses_explicit_night_count():
    """Trip dates are more reliable than counting itinerary day indices."""
    results = {
        "flight": {"options": [{"price_amount": 2400, "price_currency": "MYR"}]},
        "hotel": {"options": [{"price_amount": 300, "price_currency": "MYR"}]},
        "itinerary": {"items": [{"cost_amount": 100, "cost_currency": "MYR"}]},
    }
    breakdown = BudgetAgent._aggregate_costs(  # noqa: SLF001 — static helper
        results, FX_BASE_MYR, "MYR", nights=5
    )
    assert breakdown["nights"] == 5
    assert breakdown["hotels_total"] == pytest.approx(1500.0)
    assert breakdown["total_estimate"] == pytest.approx(2400 + 1500 + 100)


def test_aggregate_converts_foreign_priced_options():
    """A EUR-priced hotel must be inflated into MYR, not deflated."""
    results = {
        "flight": {"options": []},
        "hotel": {"options": [{"price_amount": 100, "price_currency": "EUR"}]},
        "itinerary": {"items": []},
    }
    breakdown = BudgetAgent._aggregate_costs(  # noqa: SLF001
        results, FX_BASE_MYR, "MYR", nights=1
    )
    assert breakdown["hotels_per_night"] == pytest.approx(500.0)

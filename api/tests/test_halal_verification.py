"""Halal confidence must be evidence-based (spec §7.5).

The rule is narrow and worth pinning: an LLM asserting "certified" is a
hypothesis, not evidence. Only a certification body (JAKIM / MUIS / MUI) can
justify that label, so an uncorroborated claim gets downgraded — never passed
through, and never upgraded.
"""

from __future__ import annotations

import pytest

from app.agents.research import ResearchAgent


async def verify(dining, checks, *, halal_required=True):
    """Run the verification pass with a stubbed directory response."""
    agent = ResearchAgent()

    async def fake_batch(restaurants):
        return checks[: len(restaurants)]

    from app.tools import halal

    original = halal.verify_batch
    halal.verify_batch = fake_batch
    try:
        return await agent._verify_halal(  # noqa: SLF001 — unit under test
            dining, "Venice", halal_required=halal_required
        )
    finally:
        halal.verify_batch = original


CERTIFIED_CHECK = {
    "confidence": "certified",
    "source": "halal.gov.my",
    "cert_body": "JAKIM",
    "notes": "Listed in JAKIM e-Halal directory",
}
NOTHING_FOUND = {
    "confidence": "unverified",
    "source": None,
    "cert_body": None,
    "notes": "No certification found in public directories",
}
FRIENDLY_CHECK = {
    "confidence": "muslim_friendly",
    "source": "halaltrip.com",
    "cert_body": None,
    "notes": "Found on HalalTrip directory",
}


async def test_uncorroborated_certified_claim_is_downgraded():
    dining, warnings = await verify(
        [{"title": "Some Place", "halal_confidence": "certified"}], [NOTHING_FOUND]
    )
    assert dining[0]["halal_confidence"] == "unverified"
    assert dining[0]["halal_evidence"]["claimed"] == "certified"
    assert any("downgraded" in w for w in warnings)


async def test_certification_body_confirms_the_claim():
    dining, _ = await verify(
        [{"title": "Restoran Halal", "halal_confidence": "certified"}], [CERTIFIED_CHECK]
    )
    assert dining[0]["halal_confidence"] == "certified"
    assert dining[0]["halal_evidence"]["cert_body"] == "JAKIM"


async def test_directory_evidence_caps_but_does_not_upgrade():
    """A modest claim with stronger evidence is left alone, not inflated."""
    dining, _ = await verify(
        [{"title": "Warung", "halal_confidence": "unverified"}], [FRIENDLY_CHECK]
    )
    # Claimed rank (0) <= evidence rank (1), so the conservative claim stands.
    assert dining[0]["halal_confidence"] == "unverified"


async def test_certified_claim_capped_to_muslim_friendly():
    dining, warnings = await verify(
        [{"title": "Kedai", "halal_confidence": "certified"}], [FRIENDLY_CHECK]
    )
    assert dining[0]["halal_confidence"] == "muslim_friendly"
    assert any("downgraded" in w for w in warnings)


async def test_warns_when_nothing_can_be_confirmed_for_a_halal_traveller():
    _, warnings = await verify(
        [{"title": "A"}, {"title": "B"}],
        [NOTHING_FOUND, NOTHING_FOUND],
        halal_required=True,
    )
    assert any("confirm locally" in w for w in warnings)


async def test_no_dining_is_a_no_op():
    dining, warnings = await verify([], [])
    assert dining == []
    assert warnings == []


@pytest.mark.usefixtures("stub_llm", "no_network", "no_cache", "memory_brain")
async def test_verified_flag_tracks_certification_only():
    """`Option.verified` on a restaurant means a cert body named it."""
    options = ResearchAgent._build_options(  # noqa: SLF001
        {
            "attractions": [],
            "dining": [
                {
                    "title": "Certified",
                    "halal_confidence": "certified",
                    "halal_evidence": {"cert_body": "JAKIM"},
                },
                {
                    "title": "Guessed",
                    "halal_confidence": "muslim_friendly",
                    "halal_evidence": {"cert_body": None},
                },
            ],
        },
        "MYR",
        "Kuala Lumpur",
        sourced=False,
    )
    assert options[0].verified is True
    assert options[1].verified is False

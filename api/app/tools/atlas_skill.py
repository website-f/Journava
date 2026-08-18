"""Atlas Flight Booking Skill wrapper (spec §9, §4.2).

Shells out to the `atlas-flight` CLI and branches on its stable JSON response
codes. Runs in **sandbox** mode. Auth is browser OAuth stored in the OS keychain,
so the credential must be pre-provisioned on any headless host (§15).
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from app.core.settings import settings

logger = logging.getLogger(__name__)

CLI_TIMEOUT_SECONDS = 90


class AtlasSkillError(RuntimeError):
    """The CLI is missing, timed out, or returned a non-JSON payload."""


async def _run(*args: str) -> dict[str, Any]:
    """Invoke the atlas-flight CLI and parse its JSON output."""
    argv = [settings.atlas_flight_cli, *args]
    if settings.atlas_sandbox:
        argv.append("--sandbox")

    try:
        process = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        raise AtlasSkillError(
            f"{settings.atlas_flight_cli} not found — install the skill first "
            "(see skills/atlas-flight-booking/README.md)"
        ) from exc

    try:
        stdout, stderr = await asyncio.wait_for(
            process.communicate(), timeout=CLI_TIMEOUT_SECONDS
        )
    except TimeoutError as exc:
        process.kill()
        raise AtlasSkillError("atlas-flight timed out") from exc

    if process.returncode != 0:
        raise AtlasSkillError(stderr.decode(errors="replace").strip() or "atlas-flight failed")

    try:
        return json.loads(stdout.decode(errors="replace"))
    except json.JSONDecodeError as exc:
        raise AtlasSkillError("atlas-flight returned non-JSON output") from exc


async def search(
    origin: str,
    destination: str,
    depart_date: str,
    *,
    return_date: str | None = None,
    adults: int = 1,
) -> dict[str, Any]:
    """Live flight search against the **global** inventory (never pre-filtered)."""
    args = ["search", "--from", origin, "--to", destination, "--depart", depart_date]
    if return_date:
        args += ["--return", return_date]
    args += ["--adults", str(adults), "--json"]
    return await _run(*args)


async def verify_price(offer_id: str) -> dict[str, Any]:
    """Re-price an offer. Never surface a price that hasn't passed through here."""
    return await _run("verify", "--offer", offer_id, "--json")


async def available() -> bool:
    """True when the CLI is installed and authenticated."""
    try:
        await _run("--version")
        return True
    except AtlasSkillError as exc:
        logger.info("Atlas skill unavailable: %s", exc)
        return False

# Atlas Flight Booking Skill (vendored)

The official **Atlas Flight Booking Skill** — Journava's real flight
search → book → ticket path. It is installed here as a vendored skill exposing
the `atlas-flight` CLI, which [`api/app/tools/atlas_skill.py`](../../api/app/tools/atlas_skill.py)
wraps.

## Install (do this once, interactively)

```bash
npx skills add <atlas-flight-booking-skill>    # → produces the atlas-flight CLI
```

> Not run during scaffold. `npx skills add` fetches and installs a third-party
> skill; run it yourself so you can review what it pulls.

## Auth — the important caveat (spec §15)

The skill authenticates with **browser OAuth + the OS keychain**. That is
headless-unfriendly:

- Authenticate **once, interactively**, on the dev/demo machine, in **sandbox**
  mode (`ATLAS_SANDBOX=true`).
- A bare headless VPS needs the credential **pre-provisioned** before the demo —
  it cannot complete the OAuth flow on its own.

## The flight rule Journava enforces (spec §7.5)

Flights stay **global**. A `halal_required` preference is **never a filter** on
flights — it becomes an `MOML` special-meal code at booking time and only nudges
ranking. This is encoded in
[`api/app/agents/flight.py`](../../api/app/agents/flight.py); keep it that way.

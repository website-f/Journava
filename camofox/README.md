# Camofox — browser research service

Camofox is a hardened Firefox (anti-detection, human-like) used by the Research
Agent for **discovery + verification** where no official API exists.

## The one rule (spec §8, §15)

> **Official API first → permitted public pages second → never bypass access
> controls.**

Camofox is presented as *research*, not *bypass*. It must never defeat a login,
paywall, or captcha. The API is the source of truth for structure; the crawl is
for discovery and cross-checking (e.g. confirming a halal certification against
a JAKIM/MUIS-class public source, always with a confidence label).

## Status: Phase 2 placeholder

This directory is a placeholder. The service only starts under the `full`
compose profile:

```bash
cd ../ops && docker compose --profile full up camofox
```

The `api` reaches it at `CAMOFOX_URL` (`http://camofox:3000`). The tool wrapper
will land at `api/app/tools/camofox.py`, following the same shape as
[`open_meteo.py`](../api/app/tools/open_meteo.py): async httpx + Redis cache +
graceful failure (a failing crawl degrades a result, it never breaks the run).

## Notes

- `shm_size: 1gb` is set in compose — Firefox crashes on heavy pages without it.
- To vendor the real service, build from the Camofox project referenced in the
  spec (https://github.com/website-f/Gnosion → Camofox) and replace the
  placeholder `Dockerfile`, keeping port 3000 and the HTTP contract stable.

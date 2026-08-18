# Gnosion — Journava's memory brain

Gnosion is Journava's own memory/intelligence layer (MIT, our IP). It runs in
**two modes**, both pointed at the same brain file:

| Mode        | Where it runs                     | Used for                          |
| ----------- | --------------------------------- | --------------------------------- |
| **library** | in-process inside `api`           | the hot path — every agent read/write |
| **MCP**     | this service (`gns mcp`)          | tool-style access, the d3 brain graph in the Agent Control Center |

The library-mode client lives in the API at
[`api/app/brain/gnosion_client.py`](../api/app/brain/gnosion_client.py). In
Phase 0 it falls back to an in-process dict when the real Gnosion package is not
installed, so nothing here is required to boot.

## Status: Phase 2 placeholder

This directory is a placeholder. The MCP service only starts under the `full`
compose profile:

```bash
cd ../ops && docker compose --profile full up gnosion
```

## Wiring in

- Brain file: `data/journava.gnosion`, mounted from the shared `api_data` volume
  so the library and the MCP service see the same store. **Back it up** (§13).
- `GNOSION_MCP_URL` in `.env` — leave empty for library-only (Phase 0/1); set it
  to `http://gnosion:8765` to route through the MCP service.

## To vendor the real brain

Clone/build Gnosion from source (https://github.com/website-f/Gnosion), then
replace the placeholder `Dockerfile` here with its real build. Keep the MCP port
and the brain-file path identical to what `docker-compose.yml` expects.

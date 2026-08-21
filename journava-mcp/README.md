# Journava MCP server

Exposes Journava's autonomous travel agent mesh as **MCP tools**, so Claude (or
any MCP client, e.g. an agency's own agent) can drive it directly. This is the
B2B "agentic travel infrastructure" surface.

## Tools
- `plan_trip(goal, origin?, destination?, scope?)` — runs the agents and returns each agent's summary.
- `get_active_trip()` — the traveller's current saved trip.
- `agency_overview()` — managed trips + OTA commission avoided by booking direct.

## Add to Claude Desktop
Edit `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "journava": {
      "command": "uv",
      "args": ["run", "--directory", "/absolute/path/to/journava/journava-mcp", "python", "server.py"],
      "env": {
        "JOURNAVA_API": "http://127.0.0.1:8401/api/v1",
        "JOURNAVA_EMAIL": "admin@journava.test",
        "JOURNAVA_PASSWORD": "Journava!2026"
      }
    }
  }
}
```

Point `JOURNAVA_API` at your deployment (e.g. `https://<your-domain>/api/v1`).
Restart Claude Desktop, then ask: *"plan me a full trip from KL to Chengdu on 5 Nov"* — Journava's agents run and Claude reports the result.

## Run standalone (stdio)
```bash
uv run --directory journava-mcp python server.py
```

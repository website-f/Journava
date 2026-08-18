# ops/ — deploy assets

| File                        | What it is                                                        |
| --------------------------- | ----------------------------------------------------------------- |
| `deploy.sh`                 | Build + up + health-check on the VPS. Drives the **root** `docker-compose.yml`. |
| `Caddyfile.journava.snippet`| vhost block to append to the shared `/opt/reverse-proxy/Caddyfile`. |
| `.env.example`              | Template for the repo-root `.env`.                                 |

## There is one compose file

It lives at the repo root, not here. A second copy under `ops/` drifted out of
sync with it — different service lists, mismatched host ports, and only one of
the two joined the external `proxy` network, so whichever file you happened to
run decided whether Caddy could reach the stack at all. Root is the single
source of truth; `deploy.sh` points at it.

## Deploy

```bash
cp ops/.env.example .env     # then fill in POSTGRES_PASSWORD + the ⭐ keys
./ops/deploy.sh              # build, start, wait for /health
```

Then register the domain once:

```bash
cat ops/Caddyfile.journava.snippet >> /opt/reverse-proxy/Caddyfile
# replace journava.example.com with the real host, then:
docker compose -f /opt/reverse-proxy/docker-compose.yml \
  exec caddy caddy reload --config /etc/caddy/Caddyfile
```

`web` and `api` join the external `proxy` network, which is how Caddy resolves
them by name. Never terminate TLS in this stack (§13).

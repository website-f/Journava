# ops/ — deploy assets

| File                          | What it is                                                              |
| ----------------------------- | ----------------------------------------------------------------------- |
| `deploy.sh`                   | Build + up + health-check on the VPS. Drives the **root** `docker-compose.yml`. |
| `Caddyfile.journava.snippet`  | Reverse-proxy vhost — forwards the domain to the single app port.        |
| `.env.example`                | Template for the repo-root `.env` (ports + domain live here).            |

## One stack, one public port

The root `docker-compose.yml` is the single source of truth. `web` (nginx) serves
the PWA **and** reverse-proxies `/api/*` + the SSE stream to `api` internally — so
the whole app is reachable on **one** loopback port (`JOURNAVA_WEB_PORT`, default
`8401`). Every published port binds to `127.0.0.1` only; nothing is exposed on the
public interface. There is **no shared docker network and no per-app TLS** — your
box's reverse proxy (proxy-go / Caddy / nginx) is the only thing that reaches the
port, and it terminates TLS.

Port allocation: Journava owns **8400–8409** (8000/8100/8200/8300 are other
stacks). `8400` api · `8401` web (the domain target) · `8402` postgres · `8403`
redis. Override any in `.env` if the range clashes.

## Deploy

```bash
cp ops/.env.example .env     # set POSTGRES_PASSWORD, the LLM keys, JOURNAVA_DOMAIN
./ops/deploy.sh              # build, start, wait for /health
```

Then point the domain at the one port (once):

- **proxy-go / nginx:** add a vhost forwarding `JOURNAVA_DOMAIN` →
  `http://127.0.0.1:8401` (keep `proxy_buffering off` so SSE streams). See the
  server-block example in `Caddyfile.journava.snippet`.
- **Caddy** (`/opt/reverse-proxy/Caddyfile`): append the block from
  `Caddyfile.journava.snippet`, set the real host, then reload:
  ```bash
  docker compose -f /opt/reverse-proxy/docker-compose.yml \
    exec caddy caddy reload --config /etc/caddy/Caddyfile
  ```

Finally point DNS (`JOURNAVA_DOMAIN`) at the VPS and let the shared proxy issue
the certificate. Never terminate TLS inside this stack (§13).

# Camofox research service — Phase 2 placeholder (spec §8, §11)
#
# Hardened Firefox for permitted public-page research (never bypass). Vendored
# later from the Camofox project. This placeholder keeps the container buildable
# so `docker compose --profile full config` validates; it only starts under the
# `full` profile, so Phase 0/1 never build it.

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1

WORKDIR /srv

# TODO(camofox): replace with the real hardened-Firefox build exposing an HTTP
# research API on :3000. Rule — official API first, permitted public pages
# second, never bypass a login/paywall/captcha.
EXPOSE 3000
CMD ["python", "-c", "import time,sys; sys.stderr.write('camofox placeholder — vendor the real service (see README.md)\\n'); [time.sleep(3600) for _ in iter(int, 1)]"]

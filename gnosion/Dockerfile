# Gnosion MCP service — Phase 2 placeholder (spec §7, §11)
#
# The real brain is vendored from https://github.com/website-f/Gnosion and
# exposes `gns mcp`. Until then this placeholder keeps the container buildable so
# `docker compose --profile full config` validates. It only starts under the
# `full` profile, so Phase 0/1 never build it.

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    GNOSION_BRAIN_PATH=/srv/data/journava.gnosion

WORKDIR /srv
RUN mkdir -p /srv/data

# TODO(gnosion): replace with the real install, e.g.
#   RUN pip install --no-cache-dir gnosion
#   CMD ["gns", "mcp", "--host", "0.0.0.0", "--port", "8765"]
EXPOSE 8765
CMD ["python", "-c", "import time,sys; sys.stderr.write('gnosion placeholder — vendor the real brain (see README.md)\\n'); [time.sleep(3600) for _ in iter(int, 1)]"]

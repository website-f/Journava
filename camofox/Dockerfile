# Camofox Browser — stealth headless browser for AI agents (spec §8, §11)
#
# Based on Camoufox (Firefox fork with C++ anti-detection). Exposes a REST API
# on port 9377 for tab management, accessibility snapshots, search macros, and
# YouTube transcript extraction.
#
# Source: https://github.com/jo-inc/camofox-browser
#
# Usage in docker-compose:
#   camofox:
#     build: ./camofox
#     shm_size: "1gb"   # Firefox needs real shared memory

FROM node:22-slim

WORKDIR /srv

# System deps, installed BEFORE the npm install:
#  - python3 + make + g++ : node-gyp compiles camofox-browser's native module
#    (better-sqlite3) from source when no prebuilt binary exists for this
#    node/arch. Without them the install dies with "Could not find any Python".
#  - the Firefox runtime libs Camoufox needs on the slim image.
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 make g++ ca-certificates \
    libgtk-3-0 libdbus-glib-1-2 libxt6 libasound2 libx11-xcb1 \
    fonts-liberation fonts-noto-color-emoji \
    && rm -rf /var/lib/apt/lists/*

# Install camofox-browser globally (auto-downloads Camoufox ~300MB binary)
RUN npm install -g @askjo/camofox-browser@latest

ENV CAMOFOX_PORT=9377
ENV CAMOFOX_CRASH_REPORT_ENABLED=false

EXPOSE 9377

CMD ["camofox-browser"]

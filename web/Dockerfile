# Journava Web — multi-stage Node (pnpm) + Nginx
# Stage 1: install deps + build the Vite PWA
# Stage 2: serve static output via Nginx (also proxies /api to the API service)

# --------------------------------------------------------------------------- #
# Stage 1 — build
# --------------------------------------------------------------------------- #
FROM node:22-alpine AS build

RUN corepack enable && corepack prepare pnpm@latest --activate

WORKDIR /app

# Copy package metadata + lockfile first (layer cache for node_modules)
COPY package.json pnpm-lock.yaml ./

# Install dependencies (frozen lockfile, production + dev for the build step)
RUN pnpm install --frozen-lockfile

# Copy source and build
COPY . .
RUN pnpm run build

# --------------------------------------------------------------------------- #
# Stage 2 — serve
# --------------------------------------------------------------------------- #
FROM nginx:1.27-alpine AS runtime

# Remove default config
RUN rm /etc/nginx/conf.d/default.conf

# Copy our custom nginx config
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Copy the Vite build output from the build stage
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD wget -qO- http://localhost/ || exit 1

CMD ["nginx", "-g", "daemon off;"]

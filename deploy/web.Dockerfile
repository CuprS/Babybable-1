# Babybabel website: build the Expo web app to static files, then serve them with Caddy
# (which also proxies /api to the API container and handles HTTPS).
# Build context is the repository root (see docker-compose.yml).

FROM node:22-bookworm-slim AS build
WORKDIR /src/frontend
COPY frontend/package.json frontend/yarn.lock ./
# The postinstall step copies Leaflet (the web map library) into public/vendor.
COPY frontend/scripts ./scripts
RUN corepack enable \
    && COREPACK_ENABLE_DOWNLOAD_PROMPT=0 yarn install --frozen-lockfile --non-interactive --network-timeout 600000
COPY frontend/ ./
# The site and the API share one address, e.g. https://babybabel.com and https://babybabel.com/api
ARG PUBLIC_URL
ENV EXPO_PUBLIC_BACKEND_URL=${PUBLIC_URL} \
    EXPO_PUBLIC_WEB_URL=${PUBLIC_URL} \
    NODE_ENV=production \
    EXPO_NO_TELEMETRY=1
RUN npx expo export --platform web --output-dir dist

FROM caddy:2.8-alpine
COPY --from=build /src/frontend/dist /srv/web
COPY deploy/Caddyfile /etc/caddy/Caddyfile

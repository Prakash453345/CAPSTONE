# The whole backend in one image: api-service (which also serves the built web
# app, so one port is the entire site) and sim-service. Build from itms/:
#     docker compose -f deploy/docker-compose.yml build      (or see deploy/README.md)

# ---- 1. the web app ----------------------------------------------------------
FROM node:22-bookworm-slim AS web
WORKDIR /src/itms/web-app
COPY web-app/package.json web-app/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web-app/ ./
# The map's road networks live with the simulation's scenarios.
COPY scenarios/networks/vijayawada/vijayawada_corridor.geojson /src/itms/scenarios/networks/vijayawada/
COPY scenarios/generated/amaravati_capital/amaravati_capital.geojson /src/itms/scenarios/generated/amaravati_capital/
# Which cities the console shows / which one is live ("" = defaults).
ARG VITE_CITY=""
ARG VITE_LIVE_CITY=""
ENV VITE_CITY=${VITE_CITY} VITE_LIVE_CITY=${VITE_LIVE_CITY}
RUN npx vite build

# ---- 2. the backend ------------------------------------------------------------
FROM python:3.11-slim-bookworm
# SUMO's binaries (from the eclipse-sumo wheel) link against these X/GL libraries
# even when no window is ever opened.
RUN apt-get update \
 && apt-get install -y --no-install-recommends libx11-6 libxext6 libxrender1 libgl1 libatomic1 libexpat1 \
 && rm -rf /var/lib/apt/lists/*
COPY deploy/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt
WORKDIR /app/itms
COPY contracts ./contracts
COPY packages/common ./packages/common
COPY packages/domain ./packages/domain
COPY services/api-service ./services/api-service
COPY services/sim-service ./services/sim-service
COPY scenarios ./scenarios
COPY --from=web /src/itms/web-app/dist /app/web
COPY deploy/entrypoint.sh /usr/local/bin/itms
RUN chmod 755 /usr/local/bin/itms
ENV PYTHONPATH=/app/itms/packages/common:/app/itms/packages/domain:/app/itms/services/api-service:/app/itms/services/sim-service \
    PYTHONUNBUFFERED=1 \
    WEB_DIST=/app/web
EXPOSE 8000
ENTRYPOINT ["itms"]
CMD ["api"]

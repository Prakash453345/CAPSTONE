# The whole backend in one image: api-gateway (which also serves the built web
# app, so one port is the entire site) and the simulation service. Build from
# the repository root:
#     docker compose -f backend/deploy/docker-compose.yml build   (or see backend/deploy/README.md)

# ---- 1. the web app ----------------------------------------------------------
FROM node:22-bookworm-slim AS web
WORKDIR /src/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
# The map's road networks live with the simulation's scenarios.
COPY backend/data/scenarios/networks/vijayawada/vijayawada_corridor.geojson backend/data/scenarios/networks/vijayawada/vijayawada_district.geojson /src/backend/data/scenarios/networks/vijayawada/
COPY backend/data/scenarios/generated/amaravati_capital/amaravati_capital.geojson /src/backend/data/scenarios/generated/amaravati_capital/
COPY backend/data/scenarios/generated/amaravati_v2/amaravati_v2.geojson /src/backend/data/scenarios/generated/amaravati_v2/
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
COPY backend/deploy/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt
WORKDIR /app/backend
COPY backend/contracts ./contracts
COPY backend/libs/common ./libs/common
COPY backend/libs/domain ./libs/domain
COPY backend/services/api-gateway ./services/api-gateway
COPY backend/services/simulation-service ./services/simulation-service
COPY backend/data/scenarios ./data/scenarios
COPY --from=web /src/frontend/dist /app/web
COPY backend/deploy/entrypoint.sh /usr/local/bin/itms
RUN chmod 755 /usr/local/bin/itms
ENV PYTHONPATH=/app/backend/libs/common:/app/backend/libs/domain:/app/backend/services/api-gateway:/app/backend/services/simulation-service \
    PYTHONUNBUFFERED=1 \
    WEB_DIST=/app/web
EXPOSE 8000
ENTRYPOINT ["itms"]
CMD ["api"]

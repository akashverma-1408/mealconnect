# syntax=docker/dockerfile:1
# ---------------------------------------------------------------------------
# MealConnect web image: React build served by Nginx (+ /api reverse proxy)
#   docker build -f frontend/Dockerfile -t mealconnect-web .     (context = repo root)
# ---------------------------------------------------------------------------

# ---- Stage 1: build the static bundle with Node -----------------------------
FROM node:24-alpine AS build
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
# npm ci: exact versions from the lock file; skip optional native installs not needed to build
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---- Stage 2: Nginx serves only the compiled files (no Node, no source) ----
FROM nginx:1.29-alpine AS runtime
COPY nginx/default.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
HEALTHCHECK --interval=15s --timeout=3s --retries=3 CMD wget -q -O /dev/null http://127.0.0.1/nginx-health || exit 1

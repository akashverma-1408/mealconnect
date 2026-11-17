# Phase 10 — Docker, Docker Compose and CI

The whole stack runs as six containers with one command, and passes the same smoke test, Postman collection (39 requests / 62 assertions) and Playwright E2E (desktop + mobile) as the local setup. A GitHub Actions workflow runs everything on every push.

```
browser ──:8080──► web  (Nginx: React build + /api reverse proxy, gzip, cache + security headers)
                    │
                    └──► api ×2 Uvicorn workers (FastAPI) ──► postgres (volume pgdata)
                           │                              └─► redis    (volume redisdata, AOF)
                    worker (same image, python -m app.worker) ◄──┘
                    migrate (one-off: alembic upgrade head, then exits)
```

---

## 1. Run it

```bash
cd ~/Desktop/mealconnect
cp .env.docker.example .env            # then replace each CHANGE_ME (see below)
docker compose up -d --build           # build images, start everything
docker compose ps                      # all "healthy"; migrate "Exited (0)"
docker compose run --rm -e ENVIRONMENT=development api python -m app.seed --reset   # demo data
open http://localhost:8080             # app
open http://localhost:8080/docs        # API docs (API_DOCS_ENABLED=true)
```

Generate secrets: `python3 -c "import secrets; print(secrets.token_hex(32))"`. The `.env` file is git-ignored and never copied into an image (`.dockerignore`).

Everyday commands:

| Task | Command |
|---|---|
| Logs (follow) | `docker compose logs -f api worker` |
| Shell in the API container | `docker compose exec api bash` *(slim image: use `sh`)* |
| psql into the DB | `docker compose exec postgres psql -U mealconnect` |
| Rebuild after code changes | `docker compose up -d --build api worker web` |
| Run migrations again | `docker compose run --rm migrate` |
| Stop (keep data) | `docker compose down` |
| Stop and **delete data** | `docker compose down -v` |
| Test the containers | `./scripts/smoke-test.sh http://localhost:8080` · `E2E_BASE_URL=http://localhost:8080 npm --prefix frontend run e2e` |

Host ports: web **8080**; Postgres **5433** and Redis **6380** bound to `127.0.0.1` only (debugging) — the Homebrew services keep 5432/6379, so both setups can run side by side.

---

## 2. The images

### `backend/Dockerfile` (API + worker, 357 MB)
| Choice | Why |
|---|---|
| `python:3.13-slim` | Small Debian base with the same Python as local |
| **Multi-stage**: builder installs into `/opt/venv`, runtime copies only the venv | No pip cache or build tools in the final image |
| `COPY requirements.txt` before the code | Dependency layer is cached; code edits rebuild in seconds |
| Non-root user `app` | A compromised process can't modify the image or root-owned files (verified: `docker compose exec api id -un` → `app`) |
| `HEALTHCHECK` on `/api/v1/health` | Compose waits for a healthy API before starting Nginx; unhealthy containers are visible |
| `uvicorn --workers 2 --proxy-headers` | Two processes per container; trusts `X-Forwarded-Proto` from Nginx |
| One image, two roles | `worker` reuses the image with `command: python -m app.worker` |

### `frontend/Dockerfile` (web, 93 MB)
Stage 1 `node:24-alpine` runs `npm ci && npm run build`; stage 2 `nginx:1.29-alpine` contains **only** `dist/` and `nginx/default.conf` — no Node, no source code.

### `nginx/default.conf`
- `/api/` → `http://api:8000` with keep-alive, `X-Forwarded-For`, `X-Forwarded-Proto` and **`X-Request-ID $request_id`** (the same ID appears in Nginx and API logs — verified).
- `/assets/*` (content-hashed file names) → `Cache-Control: public, max-age=31536000, immutable`; HTML → `no-cache` so a new release is picked up immediately.
- SPA fallback: unknown paths → `index.html` (React Router handles them).
- gzip for text, JSON, JS, CSS, SVG; `client_max_body_size 1m`; `server_tokens off`.
- Content-Security-Policy for the web app allows only our own scripts plus Razorpay Checkout. Playwright passing against this stack proves the policy doesn't break the UI.

---

## 3. `docker-compose.yml` explained

| Service | Notes |
|---|---|
| `postgres` | Named volume `pgdata`; healthcheck `pg_isready` |
| `redis` | `--appendonly yes` (queued jobs survive restarts); `--maxmemory 128mb --maxmemory-policy volatile-lru`: only keys **with a TTL** (cache, rate-limit counters) are evicted — queued jobs never are |
| `migrate` | Runs `alembic upgrade head` once and exits. `api` and `worker` start only after it `service_completed_successfully`. Migrations never race between replicas |
| `api` | `expose` only (not published): reachable only through Nginx. `TRUSTED_PROXY_COUNT=1` so rate limits use the real client IP |
| `worker` | No HTTP healthcheck; `stop_grace_period: 20s` lets the current job finish on `SIGTERM` |
| `web` | Starts after `api` is **healthy**; publishes 8080 |

- `x-backend-env: &backend-env` — one YAML anchor for the shared environment (no copy-paste between api/worker/migrate).
- `${POSTGRES_PASSWORD:?set in .env}` — Compose refuses to start if a secret is missing.
- Containers run with `ENVIRONMENT=production`: docs and the sandbox payment endpoint are controlled by the explicit `API_DOCS_ENABLED` / `SANDBOX_PAYMENTS_ENABLED` switches (on for this demo; the sandbox can never be on when a real gateway is configured — tested). The seed script refuses production mode unless overridden on that one command.

---

## 4. Verified in containers

| Check | Result |
|---|---|
| All services healthy, migrations applied | ✔ (`migrate` exited 0) |
| Smoke test through Nginx | customer → owner → admin flow OK; 403 / 400 / 409 security checks |
| Postman via Newman (`--env-var baseUrl=http://localhost:8080/api/v1`) | 39 requests, 62 assertions, 0 failures |
| Playwright (`E2E_BASE_URL=http://localhost:8080`) | 4/4 desktop + mobile |
| Worker in its container | 17 order e-mails sent during the runs |
| Headers | SPA: CSP + no-cache; assets: immutable 1-year cache + gzip; API: its own single CSP |
| Non-root | API process user `app` |
| Request tracing | Nginx request ID found in API logs |

Bugs fixed here: Nginx `add_header` inheritance (API responses got two CSPs → API locations now isolate their headers); duplicate `Cache-Control` on assets (`expires` + `add_header` → only `add_header`).

---

## 5. CI — `.github/workflows/ci.yml`

| Job | Steps |
|---|---|
| `backend` | Postgres 16 + Redis 8 **service containers** → `ruff` → `pytest --cov` (fails < 90 %) → `alembic upgrade head && alembic check` → coverage artifact |
| `frontend` | `npm ci` → ESLint → Vitest with coverage floor → production build |
| `docker-e2e` (after both) | throwaway secrets → `docker compose up --build --wait` → seed → Newman → Playwright (`E2E_BASE_URL`) → container logs + Playwright report on failure |

`concurrency` cancels outdated runs; `permissions: contents: read` follows least privilege. The backend job's assumption — **no `.env` file, configuration only from environment variables** — was verified locally (suite passes at 92.4 %). The workflow itself runs once the repository is on GitHub (Phase 12).

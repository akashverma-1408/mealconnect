#!/usr/bin/env bash
# Run every test layer, fastest first. Stops at the first failing layer.
#   ./scripts/test-all.sh          lint + unit/integration tests (no servers needed)
#   ./scripts/test-all.sh --full   + Postman/Newman API flow + Playwright browser E2E
#                                  (needs PostgreSQL + Redis; resets the DEV demo data)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
step() { printf '\n\033[1;34m==> %s\033[0m\n' "$1"; }

step "Backend: lint + format check"
cd "$ROOT/backend" && source .venv/bin/activate
ruff check app tests && ruff format --check app tests

step "Backend: unit tests only (no DB)"
python -m pytest -m unit -q

step "Backend: all tests + coverage gate (>= 90%)"
python -m pytest --cov --cov-report=term --cov-report=html

step "Backend: migrations match models"
alembic check

step "Frontend: lint + unit/component tests + coverage floor"
cd "$ROOT/frontend"
npx eslint .
npx vitest run --coverage

step "Frontend: production build"
npx vite build >/dev/null && echo "build ok"

if [[ "${1:-}" == "--full" ]]; then
  step "End-to-end: Playwright (desktop + mobile Chrome)"
  npx playwright test   # starts API/web servers if needed, reseeds demo data

  step "API flow: Postman collection via Newman (needs the API on :8000)"
  cd "$ROOT/backend" && python -m app.seed --reset >/dev/null
  if curl -sf http://localhost:8000/api/v1/health >/dev/null; then
    cd "$ROOT" && npx --yes newman@6.2.3 run postman/MealConnect.postman_collection.json \
      -e postman/local.postman_environment.json --color off
  else
    echo "API not running on :8000 — start it with: cd backend && uvicorn app.main:app"; exit 1
  fi
fi

printf '\n\033[1;32mAll checks passed.\033[0m\n'

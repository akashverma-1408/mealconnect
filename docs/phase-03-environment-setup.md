# Phase 3 — Environment Setup (macOS, Apple Silicon)

Every command below was run on this machine on 2026-11-17; the "Expected output" blocks are the real results.
To re-check everything at any time:

```bash
./scripts/check-env.sh
```

---

## 0. Homebrew (package manager)

**Why:** one command to install, upgrade and start developer tools; avoids manual downloads.

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"   # only if brew is missing
brew --version
```
Expected: `Homebrew 7.x`. On Apple Silicon Homebrew lives in `/opt/homebrew`.

---

## 1. Git

**Why:** version control — every change is recorded, you can branch, revert and push to GitHub.

```bash
git --version
git config --global user.name  "Your Name"
git config --global user.email "you@example.com"
git config --global init.defaultBranch main
```
Expected: `git version 2.47.0`.

---

## 2. PostgreSQL 16

**Why:** the main database (ACID transactions, constraints, JSONB, full-text/trigram search). Version 16 matches what we will use in Docker and AWS RDS.

```bash
brew install postgresql@16
```

`postgresql@16` is **keg-only**: Homebrew does not put `psql` on your PATH (so multiple versions can coexist). Add it:

```bash
echo '\n# MealConnect: PostgreSQL 16 client tools\nexport PATH="/opt/homebrew/opt/postgresql@16/bin:$PATH"' >> ~/.zshrc
source ~/.zshrc
```

Start it as a background service (also starts at login):

```bash
brew services start postgresql@16
psql --version
pg_isready
```
Expected:
```
==> Successfully started `postgresql@16` (label: sh.brew.postgresql@16)
psql (PostgreSQL) 16.16 (Homebrew)
/tmp:5432 - accepting connections
```

### 2.1 Create the app role and databases

**Why a separate role:** the app should not connect as the superuser. If the app is ever compromised, the damage is limited to its own databases.
**Why two databases:** tests create and delete data freely; they must never touch your development data.

```bash
psql -d postgres
```
```sql
CREATE ROLE mealconnect WITH LOGIN PASSWORD 'choose-a-strong-password';
CREATE DATABASE mealconnect      OWNER mealconnect;
CREATE DATABASE mealconnect_test OWNER mealconnect;
\c mealconnect
CREATE EXTENSION IF NOT EXISTS pg_trgm;   -- fast partial-text search (Phase 2 design)
\c mealconnect_test
CREATE EXTENSION IF NOT EXISTS pg_trgm;
\q
```

Verify the app role can log in:
```bash
psql "postgresql://mealconnect:<password>@localhost:5432/mealconnect" -c "select current_user, current_database();"
```
Expected:
```
 current_user | current_database
--------------+------------------
 mealconnect  | mealconnect
```

Useful `psql` commands: `\l` list databases · `\dt` list tables · `\d table` describe · `\du` roles · `\x` expanded display · `\q` quit.

---

## 3. Redis

**Why:** in-memory key-value store for caching, rate-limit counters and the background-job queue.

```bash
brew install redis
brew services start redis
redis-cli ping
```
Expected: `PONG`.

Try it:
```bash
redis-cli SET greeting "hello" EX 30   # expires in 30 seconds
redis-cli GET greeting                 # "hello"
redis-cli TTL greeting                 # seconds left
```

---

## 4. Node.js 24 LTS

**Why:** runs the React tooling (Vite, npm, ESLint). Use an **LTS** (even-numbered) release: it gets security fixes for ~3 years. Odd versions (like 23) are short-lived and are already end-of-life.

```bash
brew install node@24
brew unlink node 2>/dev/null           # unlink any older "node" formula
brew link --force --overwrite node@24
node -v && npm -v
```
Expected: `v24.22.3` and `11.19.1`. The project also has a `.nvmrc` containing `24` for tools like nvm/fnm.

To go back later: `brew unlink node@24 && brew install node`.

---

## 5. VS Code

**Why:** editor with first-class Python, React, Docker and SQL support.

Install from https://code.visualstudio.com if missing, then add the `code` terminal command:

```bash
ln -sf "/Applications/Visual Studio Code.app/Contents/Resources/app/bin/code" /opt/homebrew/bin/code
code --version
```

Extensions used in this project (also recommended automatically via `.vscode/extensions.json`):

```bash
for e in ms-python.python ms-python.vscode-pylance charliermarsh.ruff \
         dbaeumer.vscode-eslint esbenp.prettier-vscode bierner.markdown-mermaid \
         ms-azuretools.vscode-docker mtxr.sqltools mtxr.sqltools-driver-pg; do
  code --install-extension "$e"
done
```

| Extension | Purpose |
|---|---|
| Python + Pylance | IntelliSense, debugging, type checking |
| Ruff | Python linting + formatting (format on save) |
| ESLint + Prettier | JavaScript/React linting + formatting |
| Markdown Mermaid | Preview the design diagrams |
| Docker | Manage containers/images from VS Code |
| SQLTools + PG driver | Run SQL against Postgres inside VS Code |

`.vscode/settings.json` points VS Code at `backend/.venv` and turns on format-on-save.

Open the project: `code ~/Desktop/mealconnect`

---

## 6. Docker Desktop

**Why:** runs Postgres, Redis, the API and Nginx in identical containers locally, in CI and on AWS (Phase 10).

```bash
brew install --cask docker-desktop
open -a Docker        # first launch: accept the license, allow the privileged helper (asks for your Mac password)
docker --version
docker compose version
docker run --rm hello-world
```
Expected: `Docker version 29.9.3`, `Docker Compose version v5.7.0`, and `Hello from Docker!`.

> If `docker compose` says "unknown command", Docker Desktop has not finished its first launch yet — open it, wait for the whale icon to settle, then retry.

> Until Phase 10 we use the Homebrew Postgres/Redis directly. When Docker's Postgres runs later, it will use a different host port (5433) so both can coexist.

---

## 7. Project skeleton, Git and Python virtual environment

```bash
cd ~/Desktop/mealconnect
git init
```

Files created in this phase:

| Path | Purpose |
|---|---|
| `.gitignore` | Keeps secrets (`.env`), virtualenvs, `node_modules`, caches out of Git |
| `.nvmrc` | Node version for the project (`24`) |
| `.vscode/settings.json`, `extensions.json` | Shared editor setup |
| `backend/.env` | **Your real local secrets** (DB password, JWT secret) — git-ignored, permissions `600` |
| `backend/.env.example` | Template committed to Git; shows which variables exist without real values |
| `scripts/check-env.sh` | One-command environment health check |

### 7.1 Virtual environment

**Why:** each project gets its own isolated set of Python packages, so versions never clash with other projects or the system Python.

```bash
cd backend
python3 -m venv .venv          # create
source .venv/bin/activate      # activate (prompt shows "(.venv)")
which python                   # → .../mealconnect/backend/.venv/bin/python
python -m pip install --upgrade pip
deactivate                     # leave the venv when done
```

Always activate the venv before running backend commands. VS Code does it automatically in its terminal.

### 7.2 Smoke test: Python → Postgres and Redis

```bash
pip install "psycopg[binary]" redis python-dotenv
python - <<'EOF'
import os, psycopg, redis
from dotenv import load_dotenv
load_dotenv(".env")
url = os.environ["DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://")
with psycopg.connect(url) as conn:
    print("Postgres:", conn.execute("select current_user, current_database()").fetchone())
r = redis.Redis.from_url(os.environ["REDIS_URL"])
r.set("mealconnect:smoke", "ok", ex=10)
print("Redis:", r.ping(), r.get("mealconnect:smoke").decode())
EOF
```
Expected:
```
Postgres: ('mealconnect', 'mealconnect')
Redis: True ok
```

---

## 8. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `zsh: command not found: psql` | Keg-only PATH not loaded | `source ~/.zshrc` or open a new terminal |
| `connection refused ... port 5432` | Postgres not running | `brew services restart postgresql@16`; logs: `tail /opt/homebrew/var/log/postgresql@16.log` |
| `role "mealconnect" does not exist` | Role not created | Redo step 2.1 |
| `password authentication failed` | Wrong password in `.env` | `psql -d postgres -c "ALTER ROLE mealconnect PASSWORD '...'"` and update `.env` |
| `Address already in use` on 5432/6379 | Another Postgres/Redis (e.g. Postgres.app, Docker) | `lsof -nP -iTCP:5432 -sTCP:LISTEN` → stop the other one |
| `Cannot connect to the Docker daemon` | Docker Desktop not started | `open -a Docker`, wait for the whale icon to stop animating |
| `ModuleNotFoundError` in Python | venv not activated | `source backend/.venv/bin/activate` |
| `node -v` still shows old version | Shell cached path | `hash -r` or open a new terminal |

## 9. Daily start / stop

```bash
brew services list                          # what is running
brew services stop postgresql@16 redis      # free resources
brew services start postgresql@16 redis
```

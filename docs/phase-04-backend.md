# Phase 4 — Backend Foundation (FastAPI)

Phase 4 builds the backend **foundation** and the first complete vertical slice — authentication and user accounts — end to end: model → migration → schema → service → route → tests.
The remaining domains (restaurants, menu, cart, orders, payments, reviews, complaints, admin) are added on this foundation in Phase 5 together with their tables.

Status: **13 endpoints, 49 automated tests passing, 90 % coverage**, verified manually with curl and Swagger.

---

## 1. Run it

```bash
cd ~/Desktop/mealconnect/backend
source .venv/bin/activate
pip install -r requirements-dev.txt     # first time / after pulling changes
alembic upgrade head                    # create/update tables
uvicorn app.main:app --reload           # http://localhost:8000
```

- Swagger UI (try every endpoint): http://localhost:8000/docs
- ReDoc (readable reference): http://localhost:8000/redoc
- Raw OpenAPI spec: http://localhost:8000/openapi.json

Expected startup log (JSON, one object per line):
```json
{"ts": "...", "level": "INFO", "logger": "app", "message": "starting MealConnect API", "request_id": null, "environment": "development"}
```

Run the tests:
```bash
python -m pytest                         # 49 passed
python -m pytest --cov=app --cov-report=term-missing
ruff check app tests && ruff format app tests
```

Create the first admin (admins cannot self-register):
```bash
python -m app.cli create-admin --email admin@example.com --name "Platform Admin"
```

---

## 2. Folder structure — what lives where and why

```
backend/
├── app/
│   ├── main.py               App factory: logging, middleware, error handlers, routers
│   ├── cli.py                Terminal commands (create-admin)
│   ├── core/                 Cross-cutting infrastructure, no business rules
│   │   ├── config.py         Typed settings from env vars / .env (pydantic-settings)
│   │   ├── logging.py        JSON log formatter + request-id context variable
│   │   ├── middleware.py     Request ID + one access-log line per request
│   │   ├── exceptions.py     Domain exceptions + global handlers → uniform error JSON
│   │   └── security.py       bcrypt hashing, JWT create/decode
│   ├── db/
│   │   ├── base.py           DeclarativeBase, naming convention, Id/Timestamp mixins
│   │   └── session.py        Engine (connection pool) + get_db() per-request session
│   ├── models/               SQLAlchemy ORM classes = database tables
│   │   └── user.py           User, Address, RefreshToken (+ UserRole/UserStatus enums)
│   ├── schemas/              Pydantic models = API contract (validation + output shape)
│   │   ├── common.py         ErrorResponse, errors() helper for OpenAPI
│   │   ├── auth.py           Register/Login/Refresh requests, TokenPair, LoginResponse
│   │   └── user.py           UserRead/Update, PasswordChange, Address*, validators
│   ├── services/             Business rules + database work (no HTTP knowledge)
│   │   ├── auth_service.py   register, authenticate, issue/rotate/revoke tokens
│   │   └── user_service.py   profile, password change, address rules
│   └── api/
│       ├── deps.py           get_db, get_current_user, require_roles, typed aliases
│       └── v1/               Thin HTTP layer: one router per resource
│           ├── __init__.py   Combines routers under /api/v1
│           ├── health.py     /health, /health/ready
│           ├── auth.py       /auth/*
│           └── users.py      /users/me, /users/me/addresses
├── alembic/                  Database migrations (versions/ = ordered change scripts)
├── alembic.ini               Alembic config (no password in it — URL comes from .env)
├── tests/                    pytest suite (conftest.py = shared fixtures)
├── requirements.txt          Pinned runtime packages
├── requirements-dev.txt      + test & lint tools
├── pyproject.toml            pytest + ruff configuration
├── .env                      Local secrets (git-ignored)
└── .env.example              Template of required variables (committed)
```

**The dependency rule:** `api → services → models`. Routers never run SQL; services never build HTTP responses; `core` imports nothing from the layers above it. That is what makes each piece testable on its own.

---

## 3. Dependencies (requirements.txt)

| Package | Why |
|---|---|
| fastapi | Web framework: routing, validation, dependency injection, OpenAPI docs |
| uvicorn[standard] | ASGI server that runs the app (uvloop + httptools for speed, `--reload` for dev) |
| SQLAlchemy 2.1 | ORM: Python classes ↔ tables, sessions, transactions, connection pool |
| psycopg[binary] 3 | PostgreSQL driver used by SQLAlchemy (`postgresql+psycopg://`) |
| alembic | Versioned schema migrations |
| pydantic-settings | Reads `.env` / environment into a typed `Settings` object |
| email-validator | Powers `EmailStr` (syntax + domain rules) |
| PyJWT | Encode/decode/verify JSON Web Tokens |
| bcrypt | Slow, salted password hashing |
| redis | Redis client (readiness check now; cache/rate-limit/queue in Phase 8) |
| pytest, pytest-cov, httpx | Tests, coverage, HTTP client behind FastAPI's TestClient |
| ruff | Linter + formatter (replaces flake8 + isort + black) |

**Why sync SQLAlchemy (not async)?** FastAPI runs plain `def` endpoints in a thread pool, so blocking DB calls don't block the event loop. Sync code is simpler to write, debug and test, and is production-grade at this scale. Async becomes worthwhile with thousands of concurrent slow I/O calls.

---

## 4. Key files explained

### core/config.py — `Settings`
A Pydantic model whose fields are filled from environment variables, falling back to `backend/.env`. Types are enforced (`ACCESS_TOKEN_EXPIRE_MINUTES: int`), required fields without defaults (`DATABASE_URL`, `JWT_SECRET_KEY`) make the app **fail at startup** if missing — better than failing on the first request. `get_settings()` is cached so `.env` is read once.

### core/security.py
- `hash_password()` — `bcrypt.hashpw` with a random salt; cost = `BCRYPT_ROUNDS` (12 in dev/prod ≈ 0.2 s, 4 in tests).
- `verify_password()` — constant-time check; returns `False` for malformed hashes instead of crashing.
- `DUMMY_PASSWORD_HASH` — used when the email doesn't exist so login takes the same time either way (prevents discovering registered emails by timing).
- `create_access_token()` / `create_refresh_token()` — JWT with `sub` (user id), `type`, `jti` (unique id), `iat`, `exp`; access tokens also carry `role`.
- `decode_token(token, expected_type)` — verifies signature, expiry, required claims, pins the algorithm (`algorithms=[HS256]` — a token can't pick its own algorithm), and rejects a refresh token used as an access token.

### core/exceptions.py
Services raise `NotFoundError`, `ConflictError`, `UnauthorizedError`, `ForbiddenError`, `BadRequestError`. Four handlers convert *everything* — our errors, Pydantic validation (422), unknown routes (404/405), and unexpected crashes (500, logged with stack trace) — into one format:
```json
{"error": {"code": "EMAIL_TAKEN", "message": "...", "details": null, "request_id": "8f2c..."}}
```
The frontend can therefore handle errors in one place, and a user can quote the `request_id` to support, which finds the exact log lines.

### core/middleware.py — `RequestContextMiddleware`
Pure ASGI middleware: takes `X-Request-ID` from the caller (e.g. Nginx) or generates one, stores it in a `ContextVar` (so every log line in that request includes it), adds it to the response headers, and writes one access log line with method, path, status and duration.

### db/base.py
- `NAMING_CONVENTION` → constraint names like `uq_users_email`, `fk_addresses_user_id_users`: predictable names make migrations reliable.
- `IdMixin` → `BIGINT GENERATED ALWAYS AS IDENTITY` primary key.
- `TimestampMixin` → `created_at` / `updated_at` set by the database.

### db/session.py
- `engine` — one per process; holds a **connection pool** (10 + 20 overflow, `pool_pre_ping` survives DB restarts, all sessions in **UTC**).
- `get_db()` — a `yield` dependency: opens a `Session` per request and always closes it; uncommitted work is rolled back automatically.

### models/user.py
| Model | Notes |
|---|---|
| `User` | `email` UNIQUE, `role` and `status` are native Postgres ENUMs (`user_role`, `user_status`), index on `(role, status)` for admin filtering |
| `Address` | FK → users `ON DELETE CASCADE`; **partial unique index** `uq_addresses_one_default_per_user ON (user_id) WHERE is_default` — Postgres itself guarantees at most one default |
| `RefreshToken` | One row per issued refresh token (`jti` UNIQUE) → enables logout, rotation and theft detection |

### api/deps.py — dependency injection
```python
DbSession    = Annotated[Session, Depends(get_db)]
CurrentUser  = Annotated[User, Depends(get_current_user)]
CustomerUser = Annotated[User, Depends(require_roles(UserRole.CUSTOMER))]
```
An endpoint just declares `user: CustomerUser` and FastAPI runs: read `Authorization: Bearer …` → decode JWT → load user → reject if suspended → check role. Written once, reused by every endpoint. Because the user is loaded from the DB on every request, **suspending an account takes effect immediately**, even before the token expires.

---

## 5. Endpoints (Phase 4)

| Method | Path | Auth | Success | Main errors |
|---|---|---|---|---|
| GET | `/api/v1/health` | – | 200 `{"status":"ok"}` | – |
| GET | `/api/v1/health/ready` | – | 200 with DB + Redis checks | 503 if either is down |
| POST | `/api/v1/auth/register` | – | 201 `UserRead` | 409 `EMAIL_TAKEN`, 422 |
| POST | `/api/v1/auth/login` | – | 200 tokens + user | 401 `INVALID_CREDENTIALS`, 403 `ACCOUNT_SUSPENDED` |
| POST | `/api/v1/auth/refresh` | – | 200 new token pair | 401 `INVALID_TOKEN` / `TOKEN_REVOKED` |
| POST | `/api/v1/auth/logout` | user | 204 | 401 |
| GET | `/api/v1/users/me` | user | 200 `UserRead` | 401 `NOT_AUTHENTICATED` / `TOKEN_EXPIRED` |
| PATCH | `/api/v1/users/me` | user | 200 | 422 |
| POST | `/api/v1/users/me/change-password` | user | 204 (other sessions signed out) | 400 `WRONG_PASSWORD` |
| GET | `/api/v1/users/me/addresses` | customer | 200 list | 403 `ROLE_FORBIDDEN` |
| POST | `/api/v1/users/me/addresses` | customer | 201 (first = default) | 400 `ADDRESS_LIMIT`, 422 |
| PATCH | `/api/v1/users/me/addresses/{id}` | customer | 200 | 404 (also for other users' addresses), 400 |
| DELETE | `/api/v1/users/me/addresses/{id}` | customer | 204 (next address promoted to default) | 404 |

### How refresh-token rotation works
1. Login stores the refresh token's `jti` in `refresh_tokens`.
2. `/auth/refresh` marks that row revoked and issues a brand-new pair — each refresh token works **once**.
3. If a revoked token is presented again, someone else has a copy (stolen) → **all** the user's refresh tokens are revoked and a `refresh token reuse detected` warning is logged.

---

## 6. Try it with curl

```bash
B=http://localhost:8000/api/v1
curl -s -X POST $B/auth/register -H 'Content-Type: application/json' \
  -d '{"email":"demo.customer@example.com","password":"DemoPass123","full_name":"Demo Customer"}'
```
Expected (`201`):
```json
{"id":1,"email":"demo.customer@example.com","full_name":"Demo Customer","phone":null,"role":"customer","status":"active","created_at":"2026-11-17T10:07:58.242184Z"}
```

```bash
TOKEN=$(curl -s -X POST $B/auth/login -H 'Content-Type: application/json' \
  -d '{"email":"demo.customer@example.com","password":"DemoPass123"}' | python3 -c 'import json,sys;print(json.load(sys.stdin)["access_token"])')
curl -s $B/users/me -H "Authorization: Bearer $TOKEN"
```

**In Swagger:** run `POST /auth/login` → copy `access_token` → click **Authorize** (top right) → paste → every lock-icon endpoint now sends the token.

Real results from the manual run on 2026-11-17:

| Step | Result |
|---|---|
| register | 201 |
| register same email | 409 `EMAIL_TAKEN` |
| login wrong password | 401 `INVALID_CREDENTIALS` |
| login | 200, `expires_in: 900` |
| `/users/me` with token | 200 |
| add address | 201, `is_default: true` |
| refresh | 200 |
| replay old refresh token | 401 `TOKEN_REVOKED` + warning log |

---

## 7. Tests

| File | What it proves |
|---|---|
| `test_security.py` | Hashing is salted and verifiable; token round-trip; wrong type and tampered tokens rejected |
| `test_health.py` | Liveness/readiness; `X-Request-ID` generated or propagated; 404/405 use the standard error format |
| `test_auth.py` | Register (normalisation, duplicates, admin blocked, weak password), login (identical errors for wrong password vs unknown email, suspended), protected routes (missing, garbage, forged, expired, wrong-type tokens), suspension blocks live tokens, rotation, reuse detection, logout idempotency, UTC timestamps |
| `test_users.py` | Profile edits can't change role/email, password change signs out other sessions, default-address rules, validation, **ownership** (other user's address → 404), **role** (owner → 403) |

How isolation works (`tests/conftest.py`): the suite switches to `mealconnect_test` (it refuses to run against a DB not ending in `_test`), rebuilds the schema by running **all Alembic migrations** once, then wraps every test in a transaction that is rolled back — each test sees empty tables.

---

## 8. Bugs caught while building (and the fixes)

| Problem | Found by | Fix |
|---|---|---|
| Alembic `downgrade` leaves Postgres ENUM types behind → next `upgrade` fails | Reviewing the autogenerated migration | Explicit `sa.Enum(name=...).drop()` in `downgrade()`; round-trip tested |
| IDs created as `serial`, not the designed `IDENTITY` | `\d users` after migrating | `Identity(always=True)` in `IdMixin` |
| Request ID would be cleared before the 500 handler runs | Code review of middleware order | Don't reset the ContextVar (each request has its own task) |
| `admin@mealconnect.local` rejected (`.local` is a reserved domain) | Manual curl run | Use `example.com` in docs/CLI |
| Timestamps returned as `+05:30` (laptop timezone) | Manual curl run | Force `timezone=UTC` on every DB connection + regression test |

## 9. Troubleshooting

| Symptom | Fix |
|---|---|
| `ValidationError: DATABASE_URL Field required` at startup | `backend/.env` missing → `cp .env.example .env` and fill it in |
| `ModuleNotFoundError: No module named 'app'` | Run commands from `backend/` with the venv active |
| `relation "users" does not exist` | `alembic upgrade head` |
| `Address already in use` (port 8000) | `lsof -nP -iTCP:8000 -sTCP:LISTEN` → stop it, or `--port 8001` |
| 401 `TOKEN_EXPIRED` in Swagger | Access tokens last 15 min → call `/auth/refresh` or log in again |
| Pytest: `TEST_DATABASE_URL must be set...` | Add `TEST_DATABASE_URL` (…`/mealconnect_test`) to `backend/.env` |

**Known harmless warning:** pytest prints a Starlette deprecation warning recommending a newer HTTP client for `TestClient`. Tests are unaffected; we'll switch once the replacement package has been checked.

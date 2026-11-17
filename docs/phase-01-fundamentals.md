# Phase 1 — Fundamentals

## 1. What MealConnect is

A platform that connects three kinds of users:

| Role | Goal | Example actions |
|---|---|---|
| Customer | Order food | Browse, search, cart, pay, track, review |
| Restaurant | Sell food | Manage menu, accept/reject orders, update status, see sales |
| Admin | Keep the platform healthy | Manage users/restaurants, complaints, suspend accounts, analytics |

## 2. Architecture (3-tier)

```
 Browser (React SPA)
      │  HTTPS  (JSON over REST, JWT in Authorization header)
      ▼
 Nginx  ── serves built React files, reverse-proxies /api → FastAPI
      ▼
 FastAPI (Uvicorn workers)
   routers → services → repositories/models
      │                │
      ▼                ▼
 PostgreSQL         Redis ── cache, rate-limit counters, task queue
 (source of truth)    │
                      ▼
                Background worker (notifications, emails, webhooks)

 Payment gateway (Stripe/Razorpay test mode) ──webhook──► FastAPI
```

**Why each piece exists**

- **React** — builds an interactive UI from reusable components; runs entirely in the browser.
- **FastAPI** — fast async Python web framework; automatic validation (Pydantic) and automatic API docs (Swagger at `/docs`).
- **PostgreSQL** — relational database with ACID transactions. Orders and payments must never be half-saved.
- **SQLAlchemy** — ORM: work with Python classes instead of raw SQL strings, while keeping SQL available.
- **Alembic** — version control for the database schema (migrations).
- **Redis** — in-memory store: caching hot reads (restaurant lists), rate-limit counters, background job queue.
- **JWT** — stateless login token; the server verifies its signature instead of looking up a session.
- **Docker / Compose** — the same environment on your Mac, in CI and on AWS.
- **Nginx** — HTTPS termination, static files, reverse proxy, basic protection.
- **GitHub Actions** — runs tests and builds on every push (CI/CD).
- **AWS** — hosting (EC2/ECS, RDS for Postgres, ElastiCache for Redis, S3 + CloudFront for static files).

## 3. Backend layering (how we'll organize FastAPI)

| Layer | Responsibility | Never does |
|---|---|---|
| Router (`api/`) | HTTP: path, status codes, dependencies (auth) | Business rules, SQL |
| Schema (`schemas/`) | Pydantic request/response shapes + validation | DB access |
| Service (`services/`) | Business rules ("can this order be cancelled?") | Know about HTTP |
| Model (`models/`) | SQLAlchemy tables & relationships | Validation of user input |
| Core (`core/`) | Config, security, logging, DB session | — |

This separation makes code testable: services can be tested without an HTTP server.

## 4. Request lifecycle (example: place an order)

1. React sends `POST /api/v1/orders` with `Authorization: Bearer <jwt>` and cart JSON.
2. Nginx forwards to FastAPI.
3. Middleware: request ID, logging, rate limit check (Redis).
4. Dependency `get_current_user` decodes JWT → loads user → checks role = customer.
5. Pydantic validates the body (types, quantities > 0).
6. Service opens a **DB transaction**: verify items available & prices, create `order` + `order_items`, create pending `payment`. Commit or roll back everything.
7. Response `201 Created` with order ID and payment session.
8. Customer pays at the gateway → gateway calls our **webhook** → signature verified → order marked `PAID` → background job notifies the restaurant.
9. Restaurant accepts → status updates → customer sees progress (polling or WebSocket).

## 5. REST fundamentals

- Resources are nouns: `/restaurants`, `/restaurants/{id}/menu-items`, `/orders/{id}`.
- Methods: `GET` read, `POST` create, `PUT/PATCH` update, `DELETE` remove.
- Status codes: `200` OK, `201` Created, `204` No Content, `400` bad input, `401` not logged in, `403` logged in but not allowed, `404` not found, `409` conflict, `422` validation error, `429` rate limited, `500` server bug.
- Stateless: every request carries what it needs (the JWT).
- Versioning: `/api/v1/...` so we can change things later without breaking clients.
- Pagination: `?page=1&size=20` (or cursor-based for large tables).

## 6. Authentication vs authorization

- **Authentication** = who are you? → login with email + password; password stored as a **bcrypt/argon2 hash**, never plain text. Server issues a short-lived **access token** (JWT, ~15 min) and a longer **refresh token**.
- **Authorization** = what may you do? → **RBAC**: `role` ∈ {customer, restaurant_owner, admin}. FastAPI dependencies like `require_role("admin")` guard endpoints. Also ownership checks: a restaurant owner may only edit *their* restaurant.

A JWT has three base64 parts: header.payload.signature. Payload is readable by anyone, so never put secrets in it — only `sub` (user id), `role`, `exp`.

## 7. Database fundamentals we will use

- **Tables, rows, columns**; **primary key** (unique id), **foreign key** (link to another table).
- **Relationships**: user 1—N orders; restaurant 1—N menu items; order N—N menu items via `order_items`.
- **Normalization**: store each fact once (restaurant name lives only in `restaurants`).
  Exception: `order_items.unit_price` is copied at order time on purpose — menu prices change later, history must not.
- **Constraints**: `NOT NULL`, `UNIQUE(email)`, `CHECK (quantity > 0)`, FK `ON DELETE` rules.
- **Indexes**: speed up lookups (`orders(customer_id, created_at)`); cost: slower writes, more disk.
- **Transactions & ACID**: Atomicity, Consistency, Isolation, Durability.
- **Enums / state machines**: order status `PENDING → PAID → ACCEPTED → PREPARING → OUT_FOR_DELIVERY → DELIVERED`, or `REJECTED/CANCELLED`. Only allowed transitions are permitted.

## 8. Frontend fundamentals we will use

- **SPA**: the browser loads one HTML page; React Router swaps views without full reloads.
- **Components**: `RestaurantCard`, `MenuItem`, `CartDrawer`, reused everywhere.
- **State**: local (`useState`), shared (Context / Redux Toolkit for auth + cart), server state (React Query for caching API results).
- **API layer**: a single Axios instance that attaches the JWT and refreshes it on `401`.
- **Protected routes**: redirect if not logged in or wrong role.
- **Responsive CSS**: mobile-first, Flexbox/Grid, media queries.

## 9. Project workflow

1. Requirements → 2. Design (SRS, ER, APIs) → 3. Environment → 4–5. Backend + DB → 6. Frontend → 7. Integration → 8. Advanced features → 9. Testing → 10. Docker → 11. AWS → 12. Docs → 13. Interview prep.

Git workflow: `main` always deployable; work on feature branches (`feature/auth`), small commits, pull requests, CI must pass before merge.

## 10. Planned repository layout

```
mealconnect/
├── backend/          FastAPI app, Alembic, tests
├── frontend/         React app (Vite)
├── nginx/            Nginx config
├── docs/             Phase notes, diagrams, SRS
├── docker-compose.yml
├── .github/workflows/
└── README.md
```

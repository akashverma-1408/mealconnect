# Phase 13 — Interview Preparation

Fifty questions drawn from MealConnect. Each answer is short and points to where the code lives, so you can open it and show it. Practise answering out loud in 60–90 seconds, then add a trade-off or a bug you hit.

---

## A. Project overview and system design (1–8)

**1. Describe MealConnect in one minute.**
A food ordering platform with three roles: customers order and pay, restaurant owners manage menus and orders, admins moderate. React frontend, FastAPI backend, PostgreSQL for data, Redis for cache/rate limits/job queue, Docker for packaging, Terraform for AWS. I built the full lifecycle: design, API, tests, CI, containers and infrastructure code.

**2. Walk me through what happens when a customer places an order.**
`POST /orders` → JWT decoded → role checked → address ownership checked → cart rows locked (`FOR UPDATE`) → restaurant and items validated → prices re-read from the DB (never trusted from the client) → totals computed → order, items, status history inserted and cart emptied in **one transaction** → customer pays → gateway webhook is signature-verified → order becomes `PLACED` → worker emails, owner notified. (`services/order_service.py::place_order`)

**3. Why layers (router → service → model)?**
Routers only handle HTTP, services hold business rules and transactions, models map tables. Services raise domain exceptions with no HTTP knowledge, so rules are unit-testable without a server.

**4. How would you scale it to 10× traffic?**
API is stateless → more Fargate tasks (autoscaling on CPU is already in the Terraform). Reads hit the Redis cache first. Next: RDS read replica for analytics, PgBouncer for connection pooling, CDN already fronts static files, move notifications to push/WebSockets. Measure first — my benchmark showed the cache cut p95 from 61 to 30 ms.

**5. What are the single points of failure and how are they handled?**
Database (Multi-AZ option, backups, deletion protection), Redis (treated as optional: circuit breaker, fail-open), worker (queue persists in Redis AOF; crashed jobs are recovered on restart), API (≥2 tasks behind a load balancer with health checks and automatic rollback).

**6. Monolith or microservices, and why?**
Modular monolith. One team, one database, strong transactional needs (orders+payments). Clear module boundaries (catalogue, orders, payments, admin) would let me split later; microservices now would add network failure modes for no benefit.

**7. How do you keep the frontend and backend contracts in sync?**
Pydantic schemas generate the OpenAPI spec (exported to `docs/api/openapi.json`); the Postman collection asserts response shapes; Playwright tests exercise the real UI against the real API.

**8. What would you do differently with more time?**
WebSockets/SSE instead of polling, a real e-mail provider (SES), refund reconciliation job, httpOnly-cookie refresh tokens, search with a dedicated engine, per-restaurant opening-hours logic, and load testing at realistic data volumes.

---

## B. Python and FastAPI (9–18)

**9. Why FastAPI?**
Type-hint-driven validation (Pydantic), automatic OpenAPI docs, dependency injection, good performance, easy testing with `TestClient`.

**10. Explain dependency injection in FastAPI with an example.**
`Depends(get_db)` opens a session per request and closes it afterwards; `CustomerUser = Annotated[User, Depends(require_roles(UserRole.CUSTOMER))]` runs JWT decoding, user loading and role check before the endpoint body. Written once in `api/deps.py`, reused by every endpoint.

**11. `def` vs `async def` endpoints — what did you choose and why?**
Plain `def`: FastAPI runs them in a threadpool, so blocking SQLAlchemy calls don't block the event loop. Sync code is simpler to write and debug. The webhook is `async` only to read the raw request body, then hands work to a threadpool.

**12. How does Pydantic validation work and where do you use it?**
Request models validate types and constraints before the endpoint runs (422 on failure): password strength, phone format, `quantity 1–50`, money as `Decimal` with 2 places. Response models control what leaves the server (`UserRead` has no `password_hash`).

**13. How do you handle errors consistently?**
Domain exceptions (`NotFoundError`, `ConflictError`…) plus four global handlers (our errors, validation, HTTP errors, unhandled 500s) all produce `{"error": {code, message, details, request_id}}`. The frontend handles errors in one function.

**14. What is middleware? Which did you write?**
Code that wraps every request. Mine: request context (ID + access log), security headers, rate limiting — written as plain ASGI classes rather than `BaseHTTPMiddleware` for lower overhead and so the request ID is still available to the 500 handler.

**15. Explain `ContextVar` and why logging uses it.**
A value scoped to the current async task/request. The request ID is stored in one so every log line emitted anywhere during that request includes it, without passing it through function arguments.

**16. How do you configure the app for different environments?**
`pydantic-settings` reads environment variables (and `.env` locally) into a typed `Settings`. Missing required secrets fail at startup. Same image runs everywhere; only the environment differs (12-factor).

**17. Python gotcha you hit in this project.**
`money(0)` crashed because `int` has no `quantize` — sums must start at `Decimal("0")`. Also: floats for money give rounding errors, so everything is `Decimal`/`NUMERIC`.

**18. How do you test a FastAPI app?**
`TestClient` calls the app in-process; `dependency_overrides` swaps the DB session for a rolled-back test transaction; fixtures build a small marketplace; tests assert both success and failure paths. 151 tests run in ~12 s at 92 % coverage.

---

## C. React and frontend (19–26)

**19. Where does state live in your app?**
Server data in TanStack Query's cache, auth in a React Context, toasts in a Context, filters and tabs in the **URL** (shareable, survive reload), form fields in local `useState`. No Redux needed.

**20. Why TanStack Query instead of `useEffect` + `fetch`?**
It gives caching, loading/error states, retries, polling (`refetchInterval`), request de-duplication and cache invalidation after mutations — all things I'd otherwise hand-write and get subtly wrong.

**21. How does a protected route work?**
`<RequireAuth roles={['admin']}>` is a layout route: it renders `<Outlet/>` for allowed users, redirects anonymous users to login (remembering where they were) and other roles to their home. It is UX only — the API enforces the same rules.

**22. How do you handle access-token expiry in the browser?**
Axios interceptor: on 401 refresh once and retry. Refresh tokens are single-use server-side, so concurrent refreshes would look like theft; callers share **one in-flight promise**, and a **Web Locks** lock serialises refreshes across tabs.

**23. Where do you store tokens and what are the risks?**
Access token in memory (gone on close), refresh token in `localStorage` (so reloads keep you logged in). Risk: XSS can read `localStorage`. Mitigations: React escapes output, no `dangerouslySetInnerHTML`, strict CSP; the stronger option is an httpOnly cookie.

**24. What did you do for performance on the frontend?**
Route-level code splitting (`React.lazy`), debounced search, `keepPreviousData` for pagination, cached queries, immutable hashed assets cached for a year behind a CDN.

**25. How is the UI made accessible and responsive?**
Labels tied to inputs via `useId`, `aria-invalid`, roles on dialogs, skip link, keyboard-reachable controls; mobile-first CSS with a hamburger menu; tested at 375 px with no horizontal scroll.

**26. A real frontend bug you found by integration testing.**
Two tabs reloading together both sent the same refresh token; the server's reuse detection logged the user out everywhere. Unit tests passed — only a real browser showed it. Fix: Web Locks + reading the token inside the lock.

---

## D. SQL and DBMS (27–34)

**27. Explain your schema's key relationships.**
User 1–N restaurants/orders/addresses; restaurant 1–N menu items; order N–N menu items via `order_items`; order 1–0..1 payment and review. `cart_items` has a composite primary key `(user_id, menu_item_id)`.

**28. What constraints protect data integrity at the DB level?**
`CHECK (total = subtotal + delivery_fee + tax)`, `price > 0`, `rating BETWEEN 1 AND 5`, `UNIQUE(order_id)` on reviews and payments, `UNIQUE(provider_event_id)` for webhook idempotency, a **partial unique index** allowing one default address per user.

**29. What is normalisation and where did you deliberately denormalise?**
Storing each fact once. I copy item name/price into `order_items` and the address into `orders` so history survives edits, and keep `avg_rating` on restaurants for fast sorting (recomputed from reviews in the same transaction).

**30. Explain ACID with an example from the project.**
Placing an order inserts order, items, history and clears the cart atomically: all or nothing (**A**), constraints hold (**C**), concurrent checkouts don't see each other's half-written data (**I**), committed data survives a crash (**D**).

**31. How do you prevent two requests from changing the same order?**
`SELECT … FOR UPDATE` locks the order row for the duration of the transaction (used in status changes, payments, reviews' rating update). Concurrent requests wait their turn and then see the new state, so invalid double transitions are refused.

**32. Which indexes did you add and why?**
`orders(customer_id, created_at)` for "my orders", `orders(restaurant_id, status, created_at)` for the owner board, GIN trigram indexes for `ILIKE '%text%'` search, a partial index on live menu items. Indexes speed reads but slow writes and use space, so each maps to a real query.

**33. What is an N+1 query and how did you avoid it?**
Loading a list, then one query per row for related data. I use `selectinload`/`joinedload` for order items, history and restaurants, and aggregate queries (`GROUP BY`) for analytics.

**34. What is a migration and how do you keep them safe?**
Versioned schema changes (Alembic). I review autogenerated files by hand (they missed ENUM drops and duplicated shared ENUM creation), test upgrade → downgrade → upgrade, and CI runs `alembic check` to ensure models and migrations match.

---

## E. REST APIs and authentication (35–40)

**35. REST conventions you followed?**
Plural nouns, HTTP verbs for actions, status codes with meaning (201, 204, 401 vs 403, 404, 409, 422, 429), versioned prefix `/api/v1`, pagination envelope, uniform error body.

**36. 401 vs 403?**
401: not authenticated (missing/expired token). 403: authenticated but not allowed (wrong role, suspended). For other users' resources I return **404**, so existence isn't revealed.

**37. How does your JWT scheme work?**
HS256 tokens with `sub`, `type`, `jti`, `exp`, `role`. Access: 15 minutes. Refresh: 7 days, stored by `jti`. `decode` pins the algorithm, requires claims, and checks the token type so a refresh token can't be used as an access token.

**38. What is refresh-token rotation and reuse detection?**
Each refresh token works once: using it revokes it and issues a new pair. If a revoked token appears again, someone has a copy, so all that user's sessions are revoked.

**39. How are passwords stored, and how do you avoid user enumeration?**
bcrypt with a per-password salt, cost 12. Login returns the same message for wrong password and unknown email, and verifies against a dummy hash for unknown emails so timing doesn't reveal which exist.

**40. How do you secure the payment webhook?**
HMAC-SHA256 over the raw body with a shared secret, compared in constant time; amount must match; event IDs stored with a unique constraint so retries are ignored; only the webhook (system actor) can move an order to `PLACED`.

---

## F. Caching, queues, performance (41–44)

**41. What do you cache and how is it invalidated?**
Restaurant lists, details, menus, dish search — read-heavy data. List keys carry a catalogue **version**; any write does `INCR`, making all old list keys unreachable instantly. Menus are deleted by key. Invalidation runs after commit; a TTL is the safety net.

**42. What happens if Redis goes down?**
The client doesn't retry and has short timeouts; a circuit breaker skips Redis for 30 s. Cache → DB, rate limiter → allow, enqueue → log. Before the breaker, a test took 14 s for two requests because redis-py retried every call.

**43. How does your background job queue guarantee jobs aren't lost?**
`BLMOVE` moves a job atomically to a processing list; it is acknowledged only after success. Failures retry up to 3 times then go to a dead-letter list; on start the worker requeues anything left in processing. Jobs are enqueued only **after the DB commit** (SQLAlchemy `after_commit`) so we never email about a rolled-back order.

**44. Explain your rate limiting and its weakness.**
Redis fixed-window counters (`INCR` + `EXPIRE`): 5 logins/min per IP+email, 300/min per IP globally. Weakness: bursts across a window boundary can reach 2× the limit; sliding window or token bucket fixes it at more cost. Behind proxies I trust only the `X-Forwarded-For` entries my proxies add.

---

## G. Docker, CI and AWS (45–48)

**45. Explain your Dockerfile choices.**
Multi-stage build (deps in a venv, runtime copies only the venv), requirements copied before code for layer caching, non-root user, `HEALTHCHECK`, `.dockerignore` keeps secrets and tests out. One image runs both API and worker.

**46. How do the Compose services start in the right order?**
Healthchecks plus `depends_on` conditions: Postgres/Redis healthy → one-off `migrate` completes → API and worker start → web starts after API is healthy. Migrations run once, never racing between replicas.

**47. Describe your CI pipeline.**
Backend job (Postgres + Redis service containers, ruff, pytest with 90 % coverage gate, `alembic check`), frontend job (ESLint, Vitest coverage floor, build), then a Docker job that builds the stack, seeds, runs Newman and Playwright against it.

**48. How is the AWS architecture laid out and why?**
CloudFront in front of S3 (React) and the ALB (`/api/*`); ECS Fargate API/worker in public subnets with security groups allowing only the ALB; RDS and ElastiCache in private subnets with TLS; Secrets Manager injects secrets at task start; ALB only accepts CloudFront (prefix list + secret header). No NAT gateway to save cost. Deploys run migrations first and roll back automatically if new tasks are unhealthy.

---

## H. Testing, debugging, behavioural (49–50)

**49. How did you test, and what did the tests catch?**
Pyramid: unit → integration against real Postgres/Redis (transaction rollback per test) → Postman/Newman → Playwright on desktop and mobile. They caught: migration ENUM leaks, timezone leaking into API timestamps, rating drift from rounding, the refresh-token race, a Redis-outage latency bug, and the worker's socket timeout shorter than its blocking wait.

**50. Tell me about a hard bug you debugged.**
After a hot reload, `/admin` redirected to login. API logs showed "refresh token reuse detected" with two refresh calls in the same second. Root cause: two copies of the API client each sent the same single-use refresh token — the server correctly treated it as theft. I fixed it with a Web Lock that serialises refreshes and reads the token inside the lock, verified live with two module instances, and added a regression test.

---

## Resume — ATS-friendly

**MealConnect — Full-Stack Food Ordering & Restaurant Management Platform** *(Python, FastAPI, React, PostgreSQL, Redis, Docker, AWS)*

- Designed and built a three-role marketplace (customers, restaurant owners, admins) with **69 REST endpoints**, JWT authentication with refresh-token rotation, role-based access control and an audited admin console.
- Implemented transactional checkout and an **order state machine** using PostgreSQL row locking and CHECK constraints; integrated payments with **HMAC-verified, idempotent webhooks** (sandbox and Razorpay test mode) and automatic refund retries.
- Reduced catalogue **p95 latency ~50 % (61 → 30 ms)** and raised throughput ~55 % with a Redis cache using versioned invalidation; added rate limiting, a circuit breaker for Redis failures and a Redis-based background job queue with at-least-once delivery.
- Built a responsive **React 19** app (TanStack Query, route-level code splitting, accessible forms) with live order tracking and owner/admin analytics dashboards.
- Achieved **92 % backend coverage** with 151 pytest tests, 33 Vitest tests, Playwright E2E on desktop and mobile, and a Postman/Newman suite; automated checks with **GitHub Actions CI**.
- Containerised with **Docker Compose** (Nginx, API, worker, PostgreSQL, Redis; multi-stage non-root images) and wrote **Terraform** for AWS (ECS Fargate, RDS, ElastiCache, ALB, CloudFront, S3, Secrets Manager, CloudWatch alarms).

**Short version (one line):** Full-stack food ordering platform — FastAPI, React, PostgreSQL, Redis, Docker, AWS (Terraform); 69 APIs, JWT/RBAC, transactional payments with idempotent webhooks, Redis caching (p95 −50 %), 92 % test coverage, CI/CD.

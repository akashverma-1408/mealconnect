# Phase 8 — Advanced Features: Caching, Rate Limiting, Background Jobs, Payments, Security, Performance

Status: **122 backend tests + 26 frontend tests passing.** Measured: Redis cache cuts catalogue **p95 latency ~50 %** (61 → 30 ms) and raises throughput **~55 %** (620 → 960 req/s).

| Feature | Files |
|---|---|
| Redis client + circuit breaker | `app/core/redis.py` |
| Catalogue cache with versioned invalidation | `app/core/cache.py`, `app/api/v1/catalogue.py` |
| Rate limiting (global, login, register) | `app/core/rate_limit.py`, `app/api/v1/auth.py` |
| Background job queue + worker | `app/core/jobs.py`, `app/worker.py`, `app/services/email_service.py` |
| Razorpay test-mode gateway + refund retries | `app/services/payment_providers.py`, `payment_service.py`, migration `6af45fe71227` |
| Security headers | `app/core/middleware.py` |
| Frontend code splitting + Razorpay Checkout | `frontend/src/App.jsx`, `pages/customer/PaymentPage.jsx` |
| Load test | `scripts/benchmark.py` |

Run the worker next to the API:
```bash
cd backend && source .venv/bin/activate
python -m app.worker          # Ctrl-C stops after the current job
```

---

## 1. Redis caching

**What is cached:** restaurant lists (per filter combination), restaurant detail, menus, dish search — read-heavy, change rarely.
**What is not:** carts, orders, payments, reviews list — personal or must always be fresh.

**Pattern: cache-aside** (`cached_json(key, ttl, loader)`): read Redis → on miss run the DB query → store JSON with a TTL.

**Invalidation** — the hard part:
- *List/search keys* contain a version: `mc:cache:v{N}:restaurants:<hash of filters>`. Any change that could affect listings runs `INCR mc:cache:catalogue:version`, so **all** old list keys become unreachable instantly (they expire on their own). No need to know which filter combinations exist.
- *Menu / restaurant keys* are per restaurant and deleted directly.
- Invalidation runs **after `db.commit()`**: invalidating before the commit lets a concurrent request re-cache the old data.
- 13 call sites: owner edits (profile, categories, items, availability, delete), admin approve/suspend, new reviews (rating).
- The TTL (2–5 min) is the safety net if an invalidation is ever missed.

**Measured** (`scripts/benchmark.py`, 1 000 requests, 20 concurrent clients, 2 Uvicorn workers, local Mac):

| | p50 | p95 | p99 | Throughput |
|---|---|---|---|---|
| Cache off | 29 ms | 61 ms | 79–88 ms | ~620 req/s |
| Cache on | 18 ms | 30 ms | 35–45 ms | ~960 req/s |

## 2. Rate limiting

Fixed-window counters in Redis (`INCR` + `EXPIRE` in one pipeline):

| Rule | Key | Default |
|---|---|---|
| Global (middleware) | client IP | 300/minute (health checks exempt) |
| Login | IP + email | 5/minute — stops password guessing on one account without blocking a whole office behind one IP |
| Register | IP | 10/hour |

Responses: `429` + `Retry-After` header + the standard error body (`RATE_LIMITED`).
**Client IP behind proxies:** `X-Forwarded-For` can be forged by clients, so we only trust the entry added by our own proxies (`TRUSTED_PROXY_COUNT`, counted from the right). Fixed windows allow a burst at window edges (up to 2× briefly); sliding windows or token buckets fix that at higher cost.

## 3. Redis is optional — circuit breaker

Redis is an optimization, never the source of truth. Test `test_app_works_when_redis_is_down` first took **14.5 s** for 2 requests: redis-py retried every failed call with backoff, so a Redis outage would have stalled *every* API request. Fix:
- the client makes **no retries** and has 0.5 s timeouts;
- after one failure, a **circuit breaker** skips Redis for 30 s (cache → DB, rate limiter → allow, enqueue → log).
Now 10 requests with Redis down take < 0.1 s.

## 4. Background jobs

Slow/unreliable work (e-mail, retrying refunds) runs in a separate worker process.

```
API request ──commit──► LPUSH mc:jobs ──► worker: BLMOVE → mc:jobs:processing ──► handler
                                                    success → LREM (ack)
                                                    failure → re-queue (≤3 attempts) → mc:jobs:dead
```
- **At-least-once:** `BLMOVE` atomically moves a job to a processing list; a crashed worker's jobs are moved back on restart. Handlers are idempotent.
- **Transactional enqueue:** `enqueue_after_commit(db, …)` uses SQLAlchemy `after_commit` / `after_rollback` events — no e-mail for an order that was rolled back (tested).
- **Jobs:** `welcome_email` (signup), `order_status_email` (each status change), `refund_payment` (gateway was down).
- E-mail uses a console backend in development (`app.email` log); production swaps `send_email` for SES/SendGrid.

**Bug caught:** the worker waits up to 2 s on an empty queue, but shared the API's Redis client with a 0.5 s socket timeout → it would have thrown timeout errors every 2 s in production. The worker now has its own client (`get_worker_redis`, 30 s socket timeout). Regression test added.

## 5. Payments: Razorpay test mode

Same provider interface as the mock gateway; switch with `PAYMENT_PROVIDER=razorpay`.

1. `POST /payments/orders/{id}/checkout` → server creates a **Razorpay Order** (`POST /v1/orders`, amount in **paise**, HTTP Basic auth with key id/secret). Only the public `key_id` goes to the browser.
2. Frontend loads `checkout.js` and opens Razorpay Checkout.
3. Razorpay calls `POST /api/v1/payments/webhook` with `payment.captured` / `payment.failed`, signed as `HMAC-SHA256(webhook_secret, raw_body)` in `X-Razorpay-Signature`. We verify, map the event, store the charge id (`pay_…`, new column `provider_charge_id`), and mark the order PLACED.
4. Rejections/cancellations refund against `pay_…` (`POST /v1/payments/{id}/refund`).
5. **Gateway down:** checkout → `502 GATEWAY_UNAVAILABLE`; refunds → order change still succeeds, refund queued as a retrying job.

To try it with your own account: Razorpay Dashboard → **Test Mode** → API Keys; Webhooks → URL `https://<your-api>/api/v1/payments/webhook` (Phase 11), events `payment.captured`, `payment.failed`, secret = `PAYMENT_WEBHOOK_SECRET`. Locally the mock gateway stays the default. All Razorpay behaviour is covered by tests against a fake Razorpay API (no network).

## 6. Security hardening

| Control | Where |
|---|---|
| `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy`, `Permissions-Policy` | every API response |
| `Content-Security-Policy: default-src 'none'` | JSON responses (Swagger UI exempt) |
| `Strict-Transport-Security` | production only (needs HTTPS) |
| Rate limits, 429 | §2 |
| Webhook HMAC + constant-time compare + idempotency | Phases 5 & 8 |
| Only public payment key sent to the browser | test asserts the secret never appears |
| Suspended users cut off mid-session | Phase 7 |

## 7. Frontend performance

- **Route-level code splitting** (`React.lazy` + `Suspense`): customer/owner/admin pages are separate chunks (1–14 KB each) loaded on first visit.
- TanStack Query caching (30 s stale time), `keepPreviousData`, debounced search, polling only while needed.

## 8. Tests added (23)

`test_advanced.py` (cache hit avoids DB, invalidation on owner/admin changes, Redis-down speed, login/global limits, trusted proxy parsing, security headers, after-commit enqueue and rollback drop, worker e-mail, retries → dead letter, crash recovery, empty-queue wait) and `test_razorpay.py` (paise conversion, signature verification and tampering, order creation call, captured webhook → PLACED, refund uses charge id, 502 on outage, refund retried by worker).

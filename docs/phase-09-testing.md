# Phase 9 — Testing

**Totals: 151 backend tests (92 % coverage, gate 90 %) · 33 frontend tests · 4 Playwright end-to-end runs (desktop + mobile) · 39 Postman requests / 62 assertions.**
Everything runs with one command:

```bash
./scripts/test-all.sh          # lint, unit, integration, coverage gates, migration check, build (~30 s)
./scripts/test-all.sh --full   # + Playwright E2E + Postman/Newman (needs Postgres/Redis; resets DEV demo data)
```

---

## 1. The test pyramid used here

```
                 ▲   E2E (Playwright, 2 scenarios × 2 devices)      few, slow, most realistic
                ▲▲▲  API flow (Postman/Newman, 39 requests)
              ▲▲▲▲▲▲ Integration (pytest + TestClient + real PostgreSQL/Redis, ~120)
          ▲▲▲▲▲▲▲▲▲▲ Unit (pure functions/rules, ~30) + component tests (Vitest, 33)   many, fast
```

| Layer | Tool | What it proves | Speed |
|---|---|---|---|
| Unit (backend) | pytest `-m unit` | money rounding, totals, state-machine table, slugs, LIKE escaping, JWT/bcrypt | ms |
| Integration (backend) | pytest + FastAPI `TestClient` + real PostgreSQL & Redis | every endpoint, DB constraints, transactions, caching, rate limits, jobs, webhooks | ~12 s total |
| Component (frontend) | Vitest + Testing Library (jsdom) | pages render API data, forms validate, guards redirect, dialogs confirm | < 2 s |
| API contract/flow | Postman collection run by Newman | the deployed API behaves as documented, step by step | ~2 s |
| End-to-end | Playwright (Chromium, desktop + Pixel 7) | real browser → React → API → DB → worker-visible state | ~12 s |

**Why real PostgreSQL in integration tests (not SQLite)?** We rely on Postgres features — ENUM types, partial and trigram indexes, `ON CONFLICT`, `FOR UPDATE`, CHECK constraints. SQLite would let bugs through.

---

## 2. Backend tests

```bash
cd backend && source .venv/bin/activate
python -m pytest                       # all
python -m pytest -m unit               # only fast unit tests
python -m pytest tests/test_orders.py -k refund -v   # one area
python -m pytest --cov --cov-report=html && open htmlcov/index.html
```

### Isolation (how 151 tests never interfere)
- Separate **database** `mealconnect_test`, rebuilt by running **all Alembic migrations** once per run (also tests the migrations).
- Each test runs inside a **transaction that is rolled back** (`join_transaction_mode="create_savepoint"`), so app code can `commit()` freely.
- Separate **Redis database** (db 15), flushed before every test, plus the circuit breaker reset.
- Background worker tests share the test session (`nullcontext(db_session)`) because the worker normally opens its own.
- Fast bcrypt in tests (`BCRYPT_ROUNDS=4`).

### Test files

| File | Focus |
|---|---|
| `test_unit_rules.py` | Half-up rounding, totals == parts (5 000 values), escape_like, slugify, every non-final status can finish, final states have no exits, illegal transitions refused |
| `test_security.py` | bcrypt salting, JWT round-trip, wrong type, tampering |
| `test_health.py` | Liveness/readiness, request IDs, 404/405 format |
| `test_auth.py` | Register/login/refresh/logout, token edge cases, suspension |
| `test_users.py` | Profile, password change, addresses, ownership & roles |
| `test_catalogue.py` | Visibility, filters, search, pagination, menu |
| `test_orders.py` | Cart rules, checkout rules, price snapshot, webhooks (forged/duplicate/wrong amount), retries, full state machine, refunds, isolation, rating drift |
| `test_owner.py` | Restaurant & menu management, soft delete, analytics |
| `test_admin.py` | Moderation, force-cancel, complaints, platform analytics, audit |
| `test_advanced.py` | Cache hit/invalidation, Redis down, rate limits, proxy IPs, headers, jobs (after-commit, retries, dead letter, recovery, empty-queue wait) |
| `test_razorpay.py` | Paise, signature verify/tamper, order API call, captured → PLACED, refund by charge id, 502, refund retry |
| `test_seed_and_cli.py` | Seed consistency (ratings, complaint ownership), seeded logins, create-admin (success, mismatch, weak, duplicate), reset clears cache/limits |

---

## 3. Testing success AND failure scenarios

Every feature is tested on its happy path and on the ways it can go wrong. Pattern:

```python
def test_reject_requires_reason_and_refunds(client, world):
    oid = place_paid_order(client, world)["id"]                 # arrange
    assert owner_post(client, world, oid, "reject").status_code == 422      # failure: no reason
    res = owner_post(client, world, oid, "reject", reason="Out of stock")  # act
    assert res.json()["status"] == "REJECTED"                               # success
    assert res.json()["payment_status"] == "refunded"                      # side effect
```

| Feature | Success | Failure scenarios tested |
|---|---|---|
| Register | 201, email normalised, hash stored | duplicate (409), weak password / bad email (422), admin role (422), rate limit (429) |
| Login | tokens + user | wrong password = unknown email (401, same message), suspended (403), 6th attempt/min (429) |
| Protected routes | 200 | no token, garbage, forged signature, expired, refresh-as-access (401), wrong role (403), other user's data (404) |
| Checkout | order PENDING_PAYMENT, cart emptied | empty cart, minimum not met, closed, item unavailable, other user's address |
| Payment webhook | order PLACED | bad signature (400), duplicate event (ignored), amount mismatch (failed), gateway down (502), declined then retry |
| Order status | full timeline | skipped step (400), wrong actor (403), final state (400), other owner (404) |
| Refunds | REFUNDED with gateway id | gateway down → order still changes, refund retried by worker |
| Cache | served from Redis | owner change / admin suspension invalidates; Redis down → still fast |
| Jobs | e-mail sent | rollback → nothing queued; handler error → retries → dead letter; crash → recovered |

---

## 4. Frontend tests

```bash
cd frontend
npm test                 # 33 component/unit tests
npm run test:coverage    # + coverage report (coverage/index.html) and regression floor
npm run e2e              # Playwright, desktop + mobile
npx playwright show-report
```

- **Component tests** mock only the API layer (`vi.mock('../api/endpoints')`) and interact by **accessible role/label** (`getByRole('button', { name: 'Accept order' })`), so they also check that buttons and inputs are labelled correctly.
- Highlights: single-flight + cross-tab token refresh, suspended-session handling, filters stored in the URL, "replace cart?" dialog, place-order navigation, Razorpay Checkout opened with the server's order (and no secret), owner reject needs a reason, admin suspension needs a reason, tracker progress.
- Coverage: 40 % lines with a floor in `vite.config.js` (only goes up). Screens without component tests are exercised by Playwright.

### End-to-end (Playwright)
`frontend/e2e/order-flow.spec.js`, two browser contexts (two people):
1. Customer searches "Spice", adds 2× Paneer Tikka, checks out, pays.
2. Owner opens the order board, accepts, advances to delivered.
3. Customer reloads, sees *Delivered*, rates 4★; notification appears.
4. Guards: anonymous → `/login`; customer → `/admin` bounced home.

Runs on **desktop Chrome and a Pixel 7 profile**. On failure Playwright keeps a **trace** (`npx playwright show-trace …`) with DOM snapshots for every step.

---

## 5. Postman

Files in `postman/`: `MealConnect.postman_collection.json`, `local.postman_environment.json`, and `build_collection.py` that generates them.

- **In Postman:** Import both files → choose environment *MealConnect local* → run the collection (Runner) or click through folders `0. Health` … `6. Review & admin`. Tokens and ids are saved into collection variables automatically by the test scripts.
- **From the terminal / CI (Newman):**
  ```bash
  cd backend && python -m app.seed --reset && uvicorn app.main:app &   # API on :8000
  npx newman run postman/MealConnect.postman_collection.json -e postman/local.postman_environment.json
  ```
  Result: 39 requests, 62 assertions, 0 failures.
- Each request has `pm.test` assertions, e.g. `total = subtotal + fee + tax`, money is a string, reused refresh token → `TOKEN_REVOKED`.

---

## 6. Bugs the tests found in this phase

| Bug | Found by | Fix |
|---|---|---|
| Seed hard-coded `order_id=1` for the demo complaint — wrong whenever ID sequences don't start at 1 | New seed test | Reference the actual first order object |
| `seed --reset` left cached menus (stale for 5 min) and rate-limit counters in Redis | Repeated Playwright runs hitting the login limit | Reset also clears `mc:cache:*` and `mc:rl:*` (not queued jobs); test added |
| E2E login helper returned too early on phones (hamburger visible before login) | Mobile Playwright project | Wait for redirect away from `/login` |
| Desktop and mobile E2E raced on the same customer's server-side cart | Parallel Playwright workers | `workers: 1` (shared demo DB) |

## 7. Debugging a failing test — step by step
1. Run only that test verbosely: `pytest tests/test_orders.py::test_x -vv`.
2. Read the API error body — every error has a `code` (e.g. `ORDER_INVALID_TRANSITION`).
3. Look at the captured logs pytest prints (JSON lines with `request_id`).
4. Drop into the debugger at the failure: `pytest … --pdb`.
5. Frontend: `npx vitest src/pages/pages.test.jsx -t "CartPage"`; `screen.debug()` prints the DOM.
6. E2E: open the trace (`npx playwright show-trace test-results/.../trace.zip`) — it shows each action, network call and DOM snapshot.

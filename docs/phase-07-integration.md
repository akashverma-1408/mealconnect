# Phase 7 — Integration (React ↔ FastAPI ↔ PostgreSQL)

Phase 7 runs the real frontend against the real API and database and walks through every role's workflow in a browser, looking for problems that unit tests can't see.

Result: **all three workflows work end to end; 4 integration bugs found and fixed** (one of them a real multi-tab logout bug). Backend 99 tests, frontend 26 tests.

---

## 1. Run the whole stack locally

Three terminals (or the VS Code terminal split):

```bash
# 1) services (already running as brew services from Phase 3)
brew services list | grep -E "postgresql|redis"

# 2) API
cd ~/Desktop/mealconnect/backend && source .venv/bin/activate
alembic upgrade head && python -m app.seed --reset
uvicorn app.main:app --reload            # http://localhost:8000/docs

# 3) Web app
cd ~/Desktop/mealconnect/frontend
npm run dev                              # http://localhost:5173
```

How the pieces connect in development:

```
Browser ──► http://localhost:5173 (Vite dev server)
              │  /src/...  → React code (hot reload)
              └─ /api/...  → proxy → http://localhost:8000 (FastAPI) ──► PostgreSQL :5432
                                                                     └──► Redis :6379
```
Because the browser only talks to `:5173`, no CORS configuration is needed in development. (`CORS_ORIGINS` still allows `http://localhost:5173` for direct calls.)

---

## 2. Workflows verified in the browser

### Customer (`asha@example.com`)
| Step | Result |
|---|---|
| Browse home, filters, ratings | 6 approved restaurants from PostgreSQL |
| Open Spice Route menu | Categories, veg marks, sold-out item greyed out |
| Add 2× Paneer Tikka + 1× Chicken Tikka | Cart badge 3, sidebar ₹787.00, toasts |
| Reload the page on `/cart` | Still logged in (refresh-token bootstrap) |
| Checkout | 787 + 30 delivery + 39.35 tax = **₹856.35**; default address preselected |
| Place order | Order #19 `PENDING_PAYMENT`, cart emptied, redirected to payment |
| Simulate declined card | Error toast, new payment reference for the retry |
| Pay | Signed webhook → order **PLACED**, tracker + timeline |
| Owner advances order (via API) | Customer page updates **by itself** within 10 s to *Preparing*; Cancel button disappears |

### Restaurant owner (`owner.spice@example.com`)
| Step | Result |
|---|---|
| Login | Lands on `/owner` with both restaurants |
| Orders board → Preparing → Manage #19 | Only the valid next step is offered |
| Out for delivery → Delivered | Toasts, action buttons disappear when final |
| Menu: add "Gulab Jamun ₹79" | Saved, appears in category |
| Toggle Hara Bhara Kebab available | Instantly visible on the public menu |
| Analytics | Revenue, paid orders, AOV, 30-day chart incl. today's order |

### Admin (`admin@example.com`)
| Step | Result |
|---|---|
| Overview | GMV, daily chart, users/restaurants/complaints breakdown |
| Approve pending "Burger Barn" | Pending queue empty, toast |
| Resolve complaint with a note | Status resolved |
| Audit log | Both actions listed with details |

### Responsive check (375 × 812, iPhone size)
Single column, hamburger menu works, **no horizontal page scroll** (`scrollWidth === clientWidth === 375`). Wide admin tables scroll inside their own container.

---

## 3. Bugs found during integration (and fixes)

| # | Bug | How it showed up | Root cause | Fix |
|---|---|---|---|---|
| 1 | **Multi-tab logout**: user logged out of every device | After a hot reload, `/admin` redirected to login; API log showed *"refresh token reuse detected"* with two refreshes at the same second | Two copies of the API client (hot reload — in production: **two tabs** reloading together) each sent the *same* single-use refresh token. The server correctly treated the second as theft and revoked all sessions | `refreshTokens()` now runs inside the browser **Web Locks API** (`navigator.locks.request`) and reads the token *inside* the lock, so a token just rotated by another tab is never replayed. Verified live: 3 concurrent refreshes from 2 module copies → all succeed, no reuse warning. Unit test added |
| 2 | Account suspended mid-session stayed "logged in" | Suspended Ravi via admin API → UI kept showing his pages with errors | Frontend only handled 401, not `403 ACCOUNT_SUSPENDED` | Axios interceptor ends the session; login page shows *"Your account has been suspended"*. Unit test added |
| 3 | Logout from a protected page went to `/login` instead of home | Clicked *Log out* on `/orders/19` | Clearing the user made the route guard redirect before `navigate('/')` ran | Navigate home first, then clear the session |
| 4 | Notification bell count stale after payment / status changes | Bell showed 1 after an "Order placed" notification was created | Badge only polled every 30 s | Invalidate the `['notifications']` cache after payment and whenever a tracked order changes status |

Lesson: the unit tests for the token refresh passed — the bug only appeared with **two independent module instances**, i.e. a real browser. That is exactly why integration testing exists.

---

## 4. Integration checklist

- [x] Frontend calls only relative `/api/v1/...` URLs (works behind the dev proxy and Nginx)
- [x] Money values flow as strings end to end; the UI never computes totals
- [x] Error shape `{"error": {...}}` handled in one place (`errorMessage`)
- [x] 401 → single refresh → retry; refresh failure → logged out cleanly
- [x] 403 suspended → logged out with explanation
- [x] Role guards in the UI match API role checks
- [x] Live updates: order tracking (10 s), owner orders board (15 s), notification badge (30 s + on events)
- [x] Page reload keeps the session; logout revokes the refresh token on the server
- [x] Mobile layout without horizontal scrolling

## 5. Known limitations (addressed in later phases)
- Polling instead of push (WebSockets/SSE would be the next step).
- Restaurant/menu reads hit PostgreSQL every time → Redis caching in **Phase 8**.
- No rate limiting yet on login → **Phase 8**.
- Notifications are written synchronously inside the request → background worker in **Phase 8**.

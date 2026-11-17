# Phase 6 — React Frontend

A responsive single-page app for all three roles, built with React 19, React Router 8, TanStack Query 5 and plain CSS.

Status: **18 pages/screens, 24 automated tests passing, ESLint clean, production build 148 KB gzipped.**

---

## 1. Run it

```bash
cd ~/Desktop/mealconnect/frontend
npm install           # first time
npm run dev           # http://localhost:5173  (backend must run on :8000)
npm test              # 24 passed
npm run lint
npm run build         # -> dist/ (static files served by Nginx in Phase 10)
```

The dev server **proxies `/api` to `http://localhost:8000`** (see `vite.config.js`), so the browser sees one origin and there are no CORS problems in development. In production Nginx plays the same role.

---

## 2. Why these libraries

| Library | Why |
|---|---|
| **Vite** | Instant dev server, fast production builds, built-in proxy |
| **React 19** | Component model; the stack requirement |
| **React Router 8** | URL-based navigation; nested routes + `<Outlet>` let one guard protect a whole group of pages |
| **TanStack Query** | *Server state*: caching, loading/error states, background refetch, polling, invalidation after mutations. Removes most hand-written `useEffect` fetching |
| **Axios** | Interceptors: attach the token to every request, refresh on 401 |
| **Plain CSS + variables** | No framework to learn; mobile-first, dark mode via `prefers-color-scheme` |
| **Vitest + Testing Library** | Same config as Vite; tests interact with the page like a user (labels, roles, clicks) |

### State management — which state lives where
| Kind | Where | Example |
|---|---|---|
| Server data | TanStack Query cache | restaurants, cart, orders |
| Who is logged in | `AuthContext` (React Context) | `user`, `login()`, `logout()` |
| Notifications to the user | `ToastProvider` (Context) | "Order cancelled" |
| Filters & tabs | **The URL** (`useSearchParams`) | `/?city=Pune&sort=name`, `/admin?tab=users` — survive reloads, shareable |
| Form inputs | Local `useState` | login form |

There is no Redux: TanStack Query + two small contexts cover everything. The cart lives on the server (`['cart']` query), so it is the same on every device.

---

## 3. Folder structure

```
frontend/
├── index.html                  App shell (meta tags, root div)
├── vite.config.js              Dev server, /api proxy, Vitest config
├── eslint.config.js            Lint rules (React hooks, fast refresh)
├── public/favicon.svg
└── src/
    ├── main.jsx                Mounts <App/> in StrictMode
    ├── App.jsx                 Providers + route table (role-guarded groups)
    ├── api/
    │   ├── client.js           Axios instance, token storage, single-flight refresh
    │   └── endpoints.js        One function per backend endpoint
    ├── auth/
    │   ├── AuthContext.jsx     Session bootstrap, login/register/logout
    │   └── RequireAuth.jsx     Route guard by role
    ├── components/
    │   ├── Layout.jsx          Navbar (role-aware links, cart + unread badges), footer
    │   ├── Toast.jsx           Toast notifications
    │   └── ui.jsx              Spinner, ErrorBox, EmptyState, QueryState, Pagination,
    │                           StatusBadge, VegMark, Rating, Field, Modal, Stat, BarChart
    ├── hooks/useDebounce.js    Search-as-you-type without a request per keystroke
    ├── utils/                  format.js (money, dates, errors), roles.js, validation.js
    ├── styles/global.css       Design tokens, layout, components, dark mode
    ├── pages/
    │   ├── public/             HomePage, RestaurantPage, LoginPage, RegisterPage, NotFoundPage
    │   ├── customer/           CartPage, PaymentPage, OrdersPage, OrderDetailPage,
    │   │                       ComplaintsPage, ProfilePage, NotificationsPage
    │   ├── owner/              OwnerDashboard, OwnerRestaurantPage (tabs), RestaurantForm
    │   └── admin/              AdminPage (tabs)
    └── test/                   setup.js, utils.jsx (renderRoute, apiError)
```

---

## 4. Routes

| Path | Who | Page |
|---|---|---|
| `/` | everyone | Browse: search, city/cuisine/rating/veg/open filters, sort, pagination |
| `/restaurants/:id` | everyone | Menu by category, veg filter, add to cart, reviews |
| `/login`, `/register` | guests | Auth (register as customer or owner) |
| `/profile`, `/notifications` | any user | Profile, addresses (customers), password; notifications |
| `/cart` | customer | Quantities, totals, address picker / new address, notes, place order |
| `/orders/:id/pay` | customer | Sandbox payment (success / declined card) |
| `/orders`, `/orders/:id` | customer | History; live tracking (polls every 10 s while active), cancel, review, report a problem |
| `/complaints` | customer | Complaints and admin responses |
| `/owner` | owner | Restaurants + register new |
| `/owner/restaurants/:id?tab=` | owner | **Orders** (auto-refresh, accept/reject/advance) · **Menu** (categories, dishes, availability) · **Settings** · **Analytics** (stats, daily chart, top dishes) |
| `/admin?tab=` | admin | **Overview** · **Restaurants** (approve/reject/suspend) · **Users** (search, suspend) · **Orders** (force-cancel) · **Complaints** (assign/resolve) · **Audit log** |

The frontend guards are **for user experience only**. Every rule is enforced again by the API (role + ownership checks), so editing JavaScript in the browser cannot bypass them.

---

## 5. Authentication flow in the browser

1. Login → API returns `access_token` (15 min) + `refresh_token` (7 days).
2. Access token kept **in memory only**; refresh token in `localStorage` so reloads keep you logged in.
3. Every request gets `Authorization: Bearer …` from an Axios request interceptor.
4. A `401` triggers **one** refresh and a retry of the original request (response interceptor).
5. **Single-flight refresh:** refresh tokens are single-use on the server (rotation + reuse detection). If three requests expired at once and each refreshed, the second and third would look like a stolen token and log the user out everywhere. All callers therefore await the *same* promise (`refreshTokens()` in `client.js`, covered by a unit test).
6. The session bootstrap on page load is also module-level, because React StrictMode runs effects twice in development.
7. Logout revokes the refresh token on the server and clears the query cache (no data from the previous user).

**Trade-off:** a refresh token in `localStorage` can be read by injected JavaScript (XSS). React escapes rendered text by default and we never use `dangerouslySetInnerHTML`; Phase 8/10 add a Content-Security-Policy. A stricter alternative is an `httpOnly` cookie for the refresh token.

---

## 6. Patterns worth knowing (interview material)

- **`QueryState`** renders spinner → error (with retry) → data for any query: consistent UX in one line.
- **Cache updates after mutations:** either `setQueryData` with the server's response (cart, order) or `invalidateQueries` to refetch (lists).
- **Polling for "live" updates:** `refetchInterval` returns a number while an order is active and `false` once it's final.
- **`keepPreviousData`:** paginated lists keep the old page visible while the next loads (no flicker).
- **Debounced search:** `useDebounce(q, 350)` → one request after typing stops.
- **Accessible forms:** `Field` links `<label htmlFor>` with the input via `useId()`, sets `aria-invalid`, shows errors. Tests find inputs *by label*, which proves the labels work.
- **Money:** the API sends strings (`"249.00"`); the UI only formats them (`Intl.NumberFormat('en-IN', {currency:'INR'})`) and never does money math — totals come from the server.

---

## 7. Tests (24)

| File | What |
|---|---|
| `utils/format.test.js` | Rupee formatting, API error messages (incl. per-field validation), registration rules mirror the backend |
| `api/client.test.js` | Concurrent refreshes share one request; no refresh token → no request |
| `pages/pages.test.jsx` | Home list/filters-in-URL/empty/error; login redirect per role + error; route guard (anonymous, wrong role, right role); menu with sold-out item; "replace cart?" dialog; cart totals + place order + navigation; checkout blocked with reason |

## 8. Problems found while building

| Problem | Fix |
|---|---|
| `<dialog>`-based modal unreliable in jsdom and awkward to sync with React state | Overlay `div` with `role="dialog"`, `aria-modal`, Esc / backdrop to close |
| TanStack Query 5 passes a second context argument to `mutationFn`; `mutationFn: orderApi.place` forwarded it to the API helper | Always wrap: `mutationFn: (body) => orderApi.place(body)` (test caught it) |
| Fast-refresh lint warnings for helper exports in component files | Moved `homeFor` / `validateRegistration` to `utils/`, allow-listed context hooks |

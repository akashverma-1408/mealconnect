# Software Requirements Specification (SRS) — MealConnect

Version 1.0 · 2026-11-17

## 1. Introduction

### 1.1 Purpose
This document defines what MealConnect must do (functional requirements) and how well it must do it (non-functional requirements). It is the contract between design, development and testing: every test in Phase 9 maps back to a requirement ID here.

### 1.2 Scope
MealConnect is a web platform where customers order food from restaurants, restaurants manage menus and orders, and administrators run the platform. It includes a React web client, a FastAPI REST backend, PostgreSQL storage, Redis caching/queues and a sandbox payment gateway.

Out of scope for v1: native mobile apps, delivery-partner (rider) app, real money, multi-currency, live GPS maps.

### 1.3 Definitions
| Term | Meaning |
|---|---|
| Customer | Registered user who orders food |
| Owner | Registered user who manages one or more restaurants |
| Admin | Platform operator |
| JWT | JSON Web Token used for authentication |
| RBAC | Role-based access control |
| Webhook | HTTP call the payment gateway makes to our server when a payment changes |
| Idempotent | Repeating the same request has the same effect as doing it once |

## 2. Overall description

### 2.1 User classes
| Role | Technical skill | Frequency | Main device |
|---|---|---|---|
| Customer | Low | Daily/weekly | Phone browser |
| Owner | Low–medium | All day during service | Tablet/desktop |
| Admin | Medium | Daily | Desktop |

### 2.2 Operating environment
Modern browsers (Chrome, Safari, Firefox, Edge — last 2 versions), screen widths 360px and up. Server: Linux containers on AWS.

### 2.3 Constraints
- Payment only through a gateway in **test mode**; no card data ever touches our servers (PCI scope avoided).
- Passwords stored only as salted hashes (bcrypt).
- All traffic over HTTPS in production.

### 2.4 Assumptions
- One order contains items from **one restaurant** only.
- Currency is a single currency (INR) stored as `NUMERIC(10,2)`.
- Delivery is handled by the restaurant; we track status only.

## 3. Functional requirements

Priority: **M** = must (v1), **S** = should, **C** = could.

### 3.1 Authentication & accounts (AUTH)
| ID | Requirement | P |
|---|---|---|
| AUTH-1 | A visitor can register as **customer** or **restaurant owner** with name, email, phone, password. Admins cannot self-register. | M |
| AUTH-2 | Email must be unique; password ≥ 8 chars with a letter and a digit. | M |
| AUTH-3 | Login with email + password returns an access token (15 min) and refresh token (7 days). | M |
| AUTH-4 | A refresh token can be exchanged for a new token pair; the old refresh token is revoked (rotation). | M |
| AUTH-5 | Logout revokes the refresh token. | M |
| AUTH-6 | Suspended users cannot log in and their existing tokens stop working. | M |
| AUTH-7 | A user can view and update their profile and delivery addresses. | M |
| AUTH-8 | Login is rate-limited to 5 attempts/minute per IP. | M |

### 3.2 Customer (CUS)
| ID | Requirement | P |
|---|---|---|
| CUS-1 | Browse approved restaurants, paginated (default 20/page). | M |
| CUS-2 | Filter restaurants by city, cuisine, veg-only, minimum rating, open now; sort by rating, delivery fee, newest. | M |
| CUS-3 | Search restaurants and dishes by text (partial, case-insensitive). | M |
| CUS-4 | View a restaurant's menu grouped by category; unavailable items are shown but cannot be added. | M |
| CUS-5 | Add, change quantity, remove items in a server-side cart. Cart may hold items from one restaurant only; adding from another restaurant requires clearing the cart. | M |
| CUS-6 | Place an order from the cart with a delivery address; prices are re-checked on the server at checkout. | M |
| CUS-7 | Pay for an order via the sandbox gateway. Order is confirmed only after a **verified webhook**. | M |
| CUS-8 | View order history and a single order's live status timeline. | M |
| CUS-9 | Cancel an order while status is `PENDING_PAYMENT` or `PLACED` (before restaurant accepts). | M |
| CUS-10 | Rate (1–5) and review a restaurant once per **delivered** order. | M |
| CUS-11 | Raise a complaint about an order. | M |
| CUS-12 | Receive in-app notifications on order status changes. | M |

### 3.3 Restaurant owner (RES)
| ID | Requirement | P |
|---|---|---|
| RES-1 | Register a restaurant (name, address, cuisine, contact, hours). It starts as `PENDING` until an admin approves it. | M |
| RES-2 | Update restaurant profile; toggle open/closed. | M |
| RES-3 | Create, update, delete menu categories and menu items (name, description, price, veg flag, image URL). | M |
| RES-4 | Toggle an item's availability instantly. | M |
| RES-5 | Deleting an item that appears in past orders is a **soft delete**; history stays intact. | M |
| RES-6 | See incoming orders filtered by status, newest first. | M |
| RES-7 | Accept or reject a `PLACED` order (rejection needs a reason; triggers refund). | M |
| RES-8 | Move an accepted order through `PREPARING → OUT_FOR_DELIVERY → DELIVERED`; invalid jumps are refused. | M |
| RES-9 | View sales analytics for a date range: revenue, order count, average order value, top items, orders by status, daily revenue series. | M |
| RES-10 | Owners only see and change their own restaurants and orders. | M |

### 3.4 Administrator (ADM)
| ID | Requirement | P |
|---|---|---|
| ADM-1 | List/search users by role, status, email. | M |
| ADM-2 | Suspend / reactivate users (with reason). | M |
| ADM-3 | List restaurants; approve, reject or suspend them. Suspended restaurants disappear from customer browsing. | M |
| ADM-4 | Monitor all orders with filters (status, restaurant, date range). | M |
| ADM-5 | View, assign, update and resolve complaints with a resolution note. | M |
| ADM-6 | Platform analytics: GMV, orders/day, new users/day, top restaurants, complaint stats. | M |
| ADM-7 | Every admin action is written to an audit log. | M |

### 3.5 Payments (PAY)
| ID | Requirement | P |
|---|---|---|
| PAY-1 | Create a gateway payment/checkout session for an order in `PENDING_PAYMENT`. | M |
| PAY-2 | Webhook endpoint verifies the gateway's HMAC signature; unverified calls get `400` and change nothing. | M |
| PAY-3 | Webhooks are idempotent: the same event ID processed twice has no extra effect. | M |
| PAY-4 | On payment success → order `PLACED` and restaurant notified. On failure → payment `FAILED`, order stays payable. | M |
| PAY-5 | Rejection/cancellation after payment triggers a (sandbox) refund. | S |

## 4. Non-functional requirements (NFR)

| ID | Category | Requirement |
|---|---|---|
| NFR-1 | Performance | p95 latency < 300 ms for read endpoints, < 800 ms for order placement, at 100 concurrent users. |
| NFR-2 | Caching | Restaurant list and menu reads cached in Redis (TTL 60–300 s), invalidated on change. |
| NFR-3 | Scalability | API is stateless so it scales horizontally behind a load balancer. |
| NFR-4 | Security | bcrypt hashing, JWT signed with HS256 secret from env vars, CORS allow-list, input validation on every endpoint, parameterized SQL only (ORM), OWASP Top-10 reviewed. |
| NFR-5 | Rate limiting | 5/min on auth endpoints per IP; 120/min per user elsewhere; `429` with `Retry-After`. |
| NFR-6 | Reliability | Order placement and payment updates run in DB transactions; no partial orders. |
| NFR-7 | Availability | Target 99.5 % monthly; health check endpoint `/health`. |
| NFR-8 | Observability | Structured JSON logs with request ID; errors logged with stack traces; CloudWatch in production. |
| NFR-9 | Maintainability | Layered backend (router/service/model), ≥ 80 % backend test coverage, lint + type check in CI. |
| NFR-10 | Usability | Responsive from 360 px; key flows ≤ 3 clicks from home; accessible forms (labels, keyboard). |
| NFR-11 | Documentation | OpenAPI docs auto-generated at `/docs`; README with setup in < 15 min. |
| NFR-12 | Data integrity | FK constraints, CHECK constraints, unique constraints enforced in the database, not just in code. |

## 5. Business rules
- BR-1 One cart = one restaurant.
- BR-2 Order prices are snapshotted into `order_items` at placement.
- BR-3 Only orders in status `DELIVERED` can be reviewed; one review per order.
- BR-4 Order status can only follow the transitions in the state machine (see `02-diagrams.md`).
- BR-5 Only `APPROVED` restaurants that are not suspended appear to customers.
- BR-6 Minimum order amount per restaurant is enforced at checkout.
- BR-7 Total = subtotal + delivery_fee + tax (5 % of subtotal), rounded to 2 decimals.

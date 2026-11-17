# System Diagrams — MealConnect

All diagrams use **Mermaid**, which GitHub renders automatically. In VS Code, install the "Markdown Preview Mermaid Support" extension to preview them.

---

## 1. Use case diagram

Mermaid has no native UML use-case type, so actors are drawn as boxes and use cases as rounded nodes inside the system boundary.

```mermaid
flowchart LR
    C([Customer])
    O([Restaurant Owner])
    A([Admin])
    PG([Payment Gateway])

    subgraph MC[MealConnect]
        direction TB
        UC1(Register / Login)
        UC2(Manage profile & addresses)
        UC3(Browse & filter restaurants)
        UC4(Search food)
        UC5(Manage cart)
        UC6(Place order)
        UC7(Pay for order)
        UC8(Track order)
        UC9(Cancel order)
        UC10(Review restaurant)
        UC11(Raise complaint)
        UC12(Register restaurant)
        UC13(Manage menu & availability)
        UC14(Accept / reject order)
        UC15(Update order status)
        UC16(View sales analytics)
        UC17(Manage users / suspend)
        UC18(Approve / suspend restaurants)
        UC19(Monitor orders)
        UC20(Resolve complaints)
        UC21(View platform analytics)
        UC22(Receive payment webhook)
    end

    C --- UC1 & UC2 & UC3 & UC4 & UC5 & UC6 & UC7 & UC8 & UC9 & UC10 & UC11
    O --- UC1 & UC12 & UC13 & UC14 & UC15 & UC16
    A --- UC1 & UC17 & UC18 & UC19 & UC20 & UC21
    PG --- UC22
    UC6 -. includes .-> UC7
    UC7 -. triggers .-> UC22
```

---

## 2. System architecture diagram

### 2.1 Production (AWS)

```mermaid
flowchart TB
    U[User browser] -->|HTTPS| R53[Route 53 DNS]
    R53 --> CF[CloudFront CDN]
    CF -->|static assets| S3[(S3 bucket<br/>React build + images)]
    CF -->|/api/*| ALB[Application Load Balancer<br/>TLS via ACM]

    subgraph VPC[AWS VPC]
        subgraph PUB[Public subnets]
            ALB
        end
        subgraph APP[Private subnets – app tier]
            NG[Nginx] --> API1[FastAPI + Uvicorn<br/>container 1]
            NG --> API2[FastAPI + Uvicorn<br/>container 2]
            WK[Background worker<br/>notifications, refunds]
        end
        subgraph DATA[Private subnets – data tier]
            PG[(RDS PostgreSQL)]
            RD[(ElastiCache Redis)]
        end
    end

    ALB --> NG
    API1 & API2 --> PG
    API1 & API2 --> RD
    RD -->|job queue| WK
    WK --> PG
    API1 & API2 & WK -->|logs & metrics| CW[CloudWatch]
    GW[Payment gateway<br/>test mode] -->|signed webhook| ALB
    API1 & API2 -->|create payment| GW
    SM[Secrets Manager / SSM] -.env secrets.-> API1 & API2 & WK
```

### 2.2 Local development (Docker Compose)

```mermaid
flowchart LR
    B[Browser :5173] --> FE[React dev server<br/>Vite]
    B -->|:80| NGX[Nginx]
    NGX -->|/api| BE[FastAPI :8000]
    BE --> DB[(postgres :5432)]
    BE --> RC[(redis :6379)]
    RC --> W[worker]
    W --> DB
```

### 2.3 Backend internal layers

```mermaid
flowchart TB
    REQ[HTTP request] --> MW[Middleware<br/>request ID · logging · CORS · rate limit]
    MW --> RT[Router  app/api/v1/*<br/>paths, status codes]
    RT --> DEP[Dependencies<br/>get_db · get_current_user · require_role]
    RT --> SC[Schemas  app/schemas/*<br/>Pydantic validation]
    RT --> SV[Services  app/services/*<br/>business rules, transactions]
    SV --> MD[Models  app/models/*<br/>SQLAlchemy ORM]
    SV --> CA[Cache  app/core/cache.py]
    SV --> TQ[Task queue  app/workers/*]
    MD --> PG[(PostgreSQL)]
    CA --> RD[(Redis)]
    TQ --> RD
    SV -.raises.-> EX[Domain exceptions] --> EH[Global error handler<br/>uniform JSON errors]
```

---

## 3. Data flow diagrams (DFD)

### 3.1 Level 0 — context diagram

```mermaid
flowchart LR
    C[Customer] -- registration, searches, cart, orders, reviews, complaints --> P((0<br/>MealConnect<br/>System))
    P -- menus, order status, notifications --> C
    O[Restaurant Owner] -- restaurant profile, menu, order decisions --> P
    P -- incoming orders, analytics --> O
    A[Admin] -- approvals, suspensions, complaint resolutions --> P
    P -- platform reports, complaints, orders --> A
    P -- payment requests, refunds --> G[Payment Gateway]
    G -- signed payment events --> P
```

### 3.2 Level 1 — main processes and data stores

```mermaid
flowchart TB
    C[Customer]
    O[Owner]
    A[Admin]
    G[Payment Gateway]

    P1((1.0<br/>Authenticate))
    P2((2.0<br/>Browse & search))
    P3((3.0<br/>Manage cart))
    P4((4.0<br/>Place order))
    P5((5.0<br/>Process payment))
    P6((6.0<br/>Fulfil order))
    P7((7.0<br/>Manage menu))
    P8((8.0<br/>Administer platform))
    P9((9.0<br/>Notify))

    D1[(D1 Users)]
    D2[(D2 Restaurants & menu)]
    D3[(D3 Cart)]
    D4[(D4 Orders)]
    D5[(D5 Payments)]
    D6[(D6 Reviews & complaints)]
    D7[(D7 Notifications)]
    D8[(D8 Redis cache)]

    C & O & A -- credentials --> P1 <--> D1
    C -- filters, query --> P2
    P2 <--> D8
    P2 -- cache miss --> D2
    C -- items --> P3 <--> D3
    P3 -- price/availability check --> D2
    C -- checkout --> P4
    D3 --> P4 --> D4
    P4 -- payment request --> P5 <--> G
    P5 --> D5
    P5 -- paid --> D4
    O -- accept/reject/status --> P6 <--> D4
    O -- menu changes --> P7 --> D2
    P7 -- invalidate --> D8
    A -- approve/suspend/resolve --> P8
    P8 <--> D1 & D2 & D6
    D4 -- status change --> P9 --> D7
    D7 -- notifications --> C & O
    C -- review, complaint --> D6
```

---

## 4. Order state machine

```mermaid
stateDiagram-v2
    [*] --> PENDING_PAYMENT: customer checks out
    PENDING_PAYMENT --> PLACED: webhook payment.succeeded
    PENDING_PAYMENT --> CANCELLED: customer cancels / payment expires
    PLACED --> ACCEPTED: owner accepts
    PLACED --> REJECTED: owner rejects (refund)
    PLACED --> CANCELLED: customer cancels (refund)
    ACCEPTED --> PREPARING
    PREPARING --> OUT_FOR_DELIVERY
    OUT_FOR_DELIVERY --> DELIVERED
    DELIVERED --> [*]
    REJECTED --> [*]
    CANCELLED --> [*]
```

| From | Allowed next | Who |
|---|---|---|
| PENDING_PAYMENT | PLACED / CANCELLED | System (webhook) / Customer |
| PLACED | ACCEPTED / REJECTED / CANCELLED | Owner / Owner / Customer |
| ACCEPTED | PREPARING | Owner |
| PREPARING | OUT_FOR_DELIVERY | Owner |
| OUT_FOR_DELIVERY | DELIVERED | Owner |

Admins can force `CANCELLED` from any non-final state (audited).

---

## 5. Sequence diagram — checkout and payment

```mermaid
sequenceDiagram
    autonumber
    actor Cu as Customer (React)
    participant API as FastAPI
    participant DB as PostgreSQL
    participant GW as Payment Gateway
    participant Q as Redis queue
    participant W as Worker

    Cu->>API: POST /api/v1/orders {address_id, notes}
    API->>DB: BEGIN, read cart + menu prices
    API->>DB: INSERT orders, order_items (price snapshot)<br/>DELETE cart_items, COMMIT
    API-->>Cu: 201 {order_id, status: PENDING_PAYMENT}
    Cu->>API: POST /api/v1/payments/orders/{id}/checkout
    API->>GW: create payment (amount, order_id)
    GW-->>API: provider_payment_id, checkout data
    API->>DB: INSERT payments (PENDING)
    API-->>Cu: checkout data
    Cu->>GW: pays with test card
    GW->>API: POST /api/v1/payments/webhook (signed)
    API->>API: verify HMAC signature
    API->>DB: BEGIN, INSERT payment_events (unique event id)<br/>payment → SUCCEEDED, order → PLACED, COMMIT
    API->>Q: enqueue notify(order_id)
    API-->>GW: 200 OK
    Q->>W: job
    W->>DB: INSERT notifications (owner + customer)
    Cu->>API: GET /api/v1/orders/{id} (polling)
    API-->>Cu: status PLACED
```

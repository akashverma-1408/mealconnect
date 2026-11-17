"""Generates MealConnect.postman_collection.json (Postman v2.1 format).

Edit the request list below and re-run:  python3 build_collection.py
Each request carries Postman test scripts (pm.test) so Newman can run it in CI.
"""

import json

J = {"key": "Content-Type", "value": "application/json"}


def auth(var):
    return {"type": "bearer", "bearer": [{"key": "token", "value": "{{" + var + "}}", "type": "string"}]}


def req(name, method, path, body=None, token=None, tests=(), pre=None, desc=""):
    item = {
        "name": name,
        "request": {
            "method": method,
            "header": [J] if body is not None else [],
            "url": {"raw": "{{baseUrl}}" + path, "host": ["{{baseUrl}}"],
                    "path": [p for p in path.split("?")[0].strip("/").split("/")],
                    **({"query": [{"key": k, "value": v} for k, v in
                                   (q.split("=") for q in path.split("?")[1].split("&"))]} if "?" in path else {})},
            "description": desc,
        },
        "event": [{"listen": "test", "script": {"type": "text/javascript", "exec": list(tests)}}],
    }
    if body is not None:
        item["request"]["body"] = {"mode": "raw", "raw": json.dumps(body, indent=2)}
    item["request"]["auth"] = auth(token) if token else {"type": "noauth"}
    if pre:
        item["event"].append({"listen": "prerequest", "script": {"type": "text/javascript", "exec": list(pre)}})
    return item


def status(code):
    return f"pm.test('status is {code}', () => pm.response.to.have.status({code}));"


def error_code(code):
    return f"pm.test('error code {code}', () => pm.expect(pm.response.json().error.code).to.eql('{code}'));"


def save(var, expr):
    return f"pm.collectionVariables.set('{var}', {expr});"


PW = "{{demoPassword}}"
folders = [
    ("0. Health", [
        req("Liveness", "GET", "/health", tests=[status(200)]),
        req("Readiness (DB + Redis)", "GET", "/health/ready", tests=[
            status(200), "pm.test('db and redis ok', () => pm.expect(pm.response.json().checks).to.eql({database: 'ok', redis: 'ok'}));"]),
    ]),
    ("1. Auth", [
        req("Register new customer", "POST", "/auth/register",
            {"email": "newman{{$timestamp}}@example.com", "password": "Secret123", "full_name": "Newman Tester"},
            tests=[status(201), "pm.test('no password in response', () => pm.expect(pm.response.json()).to.not.have.property('password_hash'));"]),
        req("Register weak password -> 422", "POST", "/auth/register",
            {"email": "weak{{$timestamp}}@example.com", "password": "short", "full_name": "Weak"},
            tests=[status(422), error_code("VALIDATION_ERROR")]),
        req("Login customer", "POST", "/auth/login", {"email": "asha@example.com", "password": PW},
            tests=[status(200), save("customerToken", "pm.response.json().access_token"),
                   save("customerRefresh", "pm.response.json().refresh_token")]),
        req("Login wrong password -> 401", "POST", "/auth/login", {"email": "asha@example.com", "password": "Wrong12345"},
            tests=[status(401), error_code("INVALID_CREDENTIALS")]),
        req("Login owner", "POST", "/auth/login", {"email": "owner.spice@example.com", "password": PW},
            tests=[status(200), save("ownerToken", "pm.response.json().access_token")]),
        req("Login admin", "POST", "/auth/login", {"email": "admin@example.com", "password": PW},
            tests=[status(200), save("adminToken", "pm.response.json().access_token")]),
        req("Me", "GET", "/users/me", token="customerToken",
            tests=[status(200), "pm.test('is asha', () => pm.expect(pm.response.json().email).to.eql('asha@example.com'));"]),
        req("Refresh tokens (rotation)", "POST", "/auth/refresh", {"refresh_token": "{{customerRefresh}}"},
            tests=[status(200), save("customerToken", "pm.response.json().access_token")]),
        req("Reuse old refresh token -> 401", "POST", "/auth/refresh", {"refresh_token": "{{customerRefresh}}"},
            tests=[status(401), error_code("TOKEN_REVOKED")],
            desc="Refresh tokens are single-use; replaying one revokes all sessions."),
        req("Login customer again", "POST", "/auth/login", {"email": "asha@example.com", "password": PW},
            tests=[status(200), save("customerToken", "pm.response.json().access_token")]),
    ]),
    ("2. Catalogue", [
        req("List restaurants (Pune, top rated)", "GET", "/restaurants?city=Pune&sort=-avg_rating",
            tests=[status(200), "const d = pm.response.json();",
                   "pm.test('paginated', () => pm.expect(d).to.include.keys('items','total','page','size','pages'));",
                   "pm.test('money is a string', () => pm.expect(d.items[0].delivery_fee).to.be.a('string'));"]),
        req("Search 'spice'", "GET", "/restaurants?q=spice",
            tests=[status(200), save("restaurantId", "pm.response.json().items[0].id")]),
        req("Menu", "GET", "/restaurants/{{restaurantId}}/menu",
            tests=[status(200),
                   "const items = pm.response.json().sections.flatMap(s => s.items).filter(i => i.is_available);",
                   save("itemId", "items[0].id"), save("itemId2", "items[1].id")]),
        req("Dish search", "GET", "/search/menu-items?q=naan", tests=[status(200)]),
        req("Unknown restaurant -> 404", "GET", "/restaurants/999999", tests=[status(404), error_code("RESTAURANT_NOT_FOUND")]),
    ]),
    ("3. Cart & checkout", [
        req("Clear cart", "DELETE", "/cart", token="customerToken", tests=[status(204)]),
        req("Add item x2", "POST", "/cart/items", {"menu_item_id": "{{itemId}}", "quantity": 2}, token="customerToken",
            tests=[status(200), "pm.test('2 items', () => pm.expect(pm.response.json().item_count).to.eql(2));"]),
        req("Add item quantity 0 -> 422", "POST", "/cart/items", {"menu_item_id": "{{itemId}}", "quantity": 0},
            token="customerToken", tests=[status(422)]),
        req("Add second item", "POST", "/cart/items", {"menu_item_id": "{{itemId2}}", "quantity": 1}, token="customerToken",
            tests=[status(200), "const c = pm.response.json();",
                   "pm.test('total = subtotal + fee + tax', () => pm.expect(Number(c.total)).to.be.closeTo(Number(c.subtotal) + Number(c.delivery_fee) + Number(c.tax), 0.001));"]),
        req("My addresses", "GET", "/users/me/addresses", token="customerToken",
            tests=[status(200), save("addressId", "pm.response.json()[0].id")]),
        req("Place order", "POST", "/orders", {"address_id": "{{addressId}}", "notes": "Postman test"}, token="customerToken",
            tests=[status(201), "pm.test('awaiting payment', () => pm.expect(pm.response.json().status).to.eql('PENDING_PAYMENT'));",
                   save("orderId", "pm.response.json().id")]),
        req("Checkout", "POST", "/payments/orders/{{orderId}}/checkout", token="customerToken", tests=[status(200)]),
        req("Sandbox pay (signed webhook)", "POST", "/payments/sandbox/orders/{{orderId}}/pay?outcome=success",
            token="customerToken", tests=[status(200),
                                          "pm.test('processed', () => pm.expect(pm.response.json().status).to.eql('processed'));"]),
        req("Order is PLACED", "GET", "/orders/{{orderId}}", token="customerToken",
            tests=[status(200), "pm.test('placed', () => pm.expect(pm.response.json().status).to.eql('PLACED'));"]),
    ]),
    ("4. Security", [
        req("No token -> 401", "GET", "/users/me", tests=[status(401), error_code("NOT_AUTHENTICATED")]),
        req("Customer on admin API -> 403", "GET", "/admin/users", token="customerToken", tests=[status(403), error_code("ROLE_FORBIDDEN")]),
        req("Forged webhook -> 400", "POST", "/payments/webhook", {"id": "evt_fake", "type": "payment.succeeded"},
            tests=[status(400), error_code("INVALID_SIGNATURE")]),
        req("Owner skips a step -> 400", "PATCH", "/owner/orders/{{orderId}}/status", {"status": "DELIVERED"},
            token="ownerToken", tests=[status(400), error_code("ORDER_INVALID_TRANSITION")]),
    ]),
    ("5. Restaurant owner", [
        req("Accept", "POST", "/owner/orders/{{orderId}}/accept", token="ownerToken", tests=[status(200)]),
        *[req(f"Mark {s}", "PATCH", "/owner/orders/{{orderId}}/status", {"status": s}, token="ownerToken",
              tests=[status(200), f"pm.test('is {s}', () => pm.expect(pm.response.json().status).to.eql('{s}'));"])
          for s in ("PREPARING", "OUT_FOR_DELIVERY", "DELIVERED")],
        req("Analytics", "GET", "/owner/restaurants/{{restaurantId}}/analytics", token="ownerToken",
            tests=[status(200), "pm.test('has revenue', () => pm.expect(Number(pm.response.json().revenue)).to.be.above(0));"]),
    ]),
    ("6. Review & admin", [
        req("Review delivered order", "POST", "/orders/{{orderId}}/review", {"rating": 5, "comment": "Great (Postman)"},
            token="customerToken", tests=[status(201)]),
        req("Review again -> 409", "POST", "/orders/{{orderId}}/review", {"rating": 1}, token="customerToken",
            tests=[status(409), error_code("ALREADY_REVIEWED")]),
        req("Platform analytics", "GET", "/admin/analytics/overview", token="adminToken", tests=[status(200)]),
        req("Audit log", "GET", "/admin/audit-logs", token="adminToken", tests=[status(200)]),
    ]),
]

collection = {
    "info": {
        "name": "MealConnect API",
        "description": "End-to-end API flow with assertions. Import into Postman, or run: npx newman run MealConnect.postman_collection.json -e local.postman_environment.json\nRequires seeded demo data (python -m app.seed --reset).",
        "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
    },
    "item": [{"name": n, "item": items} for n, items in folders],
    "variable": [{"key": k, "value": ""} for k in
                 ("customerToken", "customerRefresh", "ownerToken", "adminToken", "restaurantId", "itemId", "itemId2", "addressId", "orderId")],
}
environment = {
    "name": "MealConnect local",
    "values": [
        {"key": "baseUrl", "value": "http://localhost:8000/api/v1", "enabled": True},
        {"key": "demoPassword", "value": "DemoPass123", "enabled": True},
    ],
}
json.dump(collection, open("MealConnect.postman_collection.json", "w"), indent=2)
json.dump(environment, open("local.postman_environment.json", "w"), indent=2)
print(sum(len(i) for _, i in folders), "requests")

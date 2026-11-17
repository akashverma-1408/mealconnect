#!/usr/bin/env bash
# End-to-end smoke test against a running API with seeded demo data.
#   cd backend && python -m app.seed --reset && uvicorn app.main:app   (in another terminal)
#   ./scripts/smoke-test.sh [base_url]
set -euo pipefail
B="${1:-http://localhost:8000}/api/v1"
J='Content-Type: application/json'
PW=DemoPass123   # demo password from backend/app/seed.py (local development only)

jqpy() { python3 -c "import json,sys; d=json.load(sys.stdin); print($1)"; }
token() { curl -sf -H "$J" -d "{\"email\":\"$1\",\"password\":\"$PW\"}" "$B/auth/login" | jqpy 'd["access_token"]'; }
step() { printf '\n\033[1m%s\033[0m\n' "$1"; }

CUST=$(token asha@example.com); OWNER=$(token owner.spice@example.com); ADMIN=$(token admin@example.com)
C="Authorization: Bearer $CUST"; O="Authorization: Bearer $OWNER"; A="Authorization: Bearer $ADMIN"

step "1. Browse restaurants in Pune (sorted by rating)"
curl -sf "$B/restaurants?city=Pune" | jqpy '"\n".join(f"  {r["name"]:<14} rating {r["avg_rating"]} ({r["rating_count"]})  fee {r["delivery_fee"]}" for r in d["items"])'
RID=$(curl -sf "$B/restaurants?q=spice" | jqpy 'd["items"][0]["id"]')

step "2. Search dishes: 'naan'"
curl -sf "$B/search/menu-items?q=naan" | jqpy '"\n".join(f"  {i["name"]} @ {i["restaurant"]["name"]}: {i["price"]}" for i in d["items"])'

step "3. Fill cart from the Spice Route menu"
ITEMS=$(curl -sf "$B/restaurants/$RID/menu" | jqpy '" ".join(str(i["id"]) for s in d["sections"] for i in s["items"] if i["is_available"])')
set -- $ITEMS
curl -sf -o /dev/null -X DELETE -H "$C" "$B/cart"
curl -sf -o /dev/null -H "$J" -H "$C" -d "{\"menu_item_id\":$1,\"quantity\":2}" "$B/cart/items"
curl -sf -H "$J" -H "$C" -d "{\"menu_item_id\":$2,\"quantity\":1}" "$B/cart/items" | jqpy 'f"  subtotal {d["subtotal"]} + fee {d["delivery_fee"]} + tax {d["tax"]} = total {d["total"]}  can_checkout={d["can_checkout"]}"'

step "4. Place order, pay in the sandbox"
ADDR=$(curl -sf -H "$C" "$B/users/me/addresses" | jqpy 'd[0]["id"]')
OID=$(curl -sf -H "$J" -H "$C" -d "{\"address_id\":$ADDR}" "$B/orders" | jqpy 'd["id"]')
echo "  order #$OID created: $(curl -sf -H "$C" "$B/orders/$OID" | jqpy 'd["status"]')"
curl -sf -o /dev/null -X POST -H "$C" "$B/payments/orders/$OID/checkout"
echo "  webhook: $(curl -sf -X POST -H "$C" "$B/payments/sandbox/orders/$OID/pay" | jqpy 'd["status"]')"
echo "  status now: $(curl -sf -H "$C" "$B/orders/$OID" | jqpy 'd["status"] + " / payment " + d["payment_status"]')"

step "5. Restaurant owner processes the order"
curl -sf -o /dev/null -X POST -H "$O" "$B/owner/orders/$OID/accept"
for s in PREPARING OUT_FOR_DELIVERY DELIVERED; do
  curl -sf -o /dev/null -X PATCH -H "$J" -H "$O" -d "{\"status\":\"$s\"}" "$B/owner/orders/$OID/status"
done
curl -sf -H "$C" "$B/orders/$OID" | jqpy '"  timeline: " + " -> ".join(h["to_status"] for h in d["history"])'

step "6. Customer reviews the delivered order"
curl -sf -H "$J" -H "$C" -d '{"rating":5,"comment":"Smoke test: excellent!"}' "$B/orders/$OID/review" | jqpy 'f"  review #{d["id"]}: {d["rating"]} stars by {d["author_name"]}"'
curl -sf "$B/restaurants/$RID" | jqpy 'f"  Spice Route rating now {d["avg_rating"]} ({d["rating_count"]} reviews)"'

step "7. Notifications for the customer"
curl -sf -H "$C" "$B/notifications?size=3" | jqpy '"\n".join("  - " + n["title"] for n in d["items"])'

step "8. Admin approves the pending restaurant"
PENDING=$(curl -sf -H "$A" "$B/admin/restaurants?status=pending" | jqpy 'd["items"][0]["id"] if d["items"] else ""')
if [ -n "$PENDING" ]; then
  curl -sf -X PATCH -H "$J" -H "$A" -d '{"status":"approved"}' "$B/admin/restaurants/$PENDING/status" | jqpy 'f"  {d["name"]} -> {d["status"]}"'
else echo "  (no pending restaurants)"; fi

step "9. Analytics"
curl -sf -H "$O" "$B/owner/restaurants/$RID/analytics" | jqpy 'f"  owner: revenue {d["revenue"]} from {d["order_count"]} orders, AOV {d["average_order_value"]}, top item {d["top_items"][0]["name"]}"'
curl -sf -H "$A" "$B/admin/analytics/overview" | jqpy 'f"  admin: GMV {d["gmv"]}, {d["order_count"]} orders, users {d["users_by_role"]}"'

step "10. Security checks"
printf '  customer -> admin API: HTTP %s\n' "$(curl -s -o /dev/null -w '%{http_code}' -H "$C" "$B/admin/users")"
printf '  forged webhook:        HTTP %s\n' "$(curl -s -o /dev/null -w '%{http_code}' -H "$J" -H 'x-mock-signature: bad' -d '{}' "$B/payments/webhook")"
printf '  review twice:          HTTP %s\n' "$(curl -s -o /dev/null -w '%{http_code}' -H "$J" -H "$C" -d '{"rating":1}' "$B/orders/$OID/review")"
echo; echo "Smoke test finished OK."

"""Pure unit tests for business rules: no database, no HTTP, run in milliseconds."""

from decimal import Decimal

import pytest

from app.core.exceptions import BadRequestError, ForbiddenError
from app.models.order import OrderStatus
from app.services.common import calc_totals, escape_like, money
from app.services.order_service import FINAL, TRANSITIONS, transition
from app.services.restaurant_service import _slugify

S = OrderStatus
pytestmark = pytest.mark.unit


# ------------------------------------------------------------------ money
@pytest.mark.parametrize(
    "value,expected",
    [
        ("24.905", "24.91"),  # half-up, not banker's rounding (which gives 24.90)
        ("24.904", "24.90"),
        ("0.005", "0.01"),
        ("10", "10.00"),
    ],
)
def test_money_rounds_half_up(value, expected):
    assert money(Decimal(value)) == Decimal(expected)


@pytest.mark.parametrize(
    "subtotal,fee,tax,total",
    [
        ("498.00", "30.00", "24.90", "552.90"),
        ("557.00", "30.00", "27.85", "614.85"),
        ("0.10", "0.00", "0.01", "0.11"),  # 0.005 tax rounds up
        ("1000.00", "0.00", "50.00", "1050.00"),
    ],
)
def test_calc_totals(subtotal, fee, tax, total):
    assert calc_totals(Decimal(subtotal), Decimal(fee)) == (Decimal(tax), Decimal(total))


def test_totals_never_drift_from_parts():
    """total == subtotal + fee + tax for many values (mirrors the DB CHECK constraint)."""
    for cents in range(1, 5000, 7):
        subtotal = Decimal(cents) / 100
        tax, total = calc_totals(subtotal, Decimal("30.00"))
        assert total == subtotal + Decimal("30.00") + tax


# ------------------------------------------------------------------ helpers
def test_escape_like_neutralises_wildcards():
    assert escape_like("100%_off") == "100\\%\\_off"
    assert escape_like("a\\b") == "a\\\\b"


@pytest.mark.parametrize(
    "name,slug",
    [("Spice Route", "spice-route"), ("  Café  Déjà  ", "caf-d-j"), ("!!!", "restaurant")],
)
def test_slugify(name, slug):
    assert _slugify(name) == slug


# ------------------------------------------------------------------ state machine
def test_final_states_have_no_outgoing_transitions():
    for frm, _to in TRANSITIONS:
        assert frm not in FINAL


def test_every_non_final_state_can_reach_a_final_state():
    graph: dict[OrderStatus, set[OrderStatus]] = {}
    for frm, to in TRANSITIONS:
        graph.setdefault(frm, set()).add(to)
    for start in set(OrderStatus) - FINAL:
        seen, stack = set(), [start]
        while stack:
            node = stack.pop()
            if node in FINAL:
                break
            seen.add(node)
            stack.extend(graph.get(node, set()) - seen)
        else:
            pytest.fail(f"{start} can never finish")


def test_only_the_payment_webhook_can_place_an_order():
    assert TRANSITIONS[(S.PENDING_PAYMENT, S.PLACED)] == {"system"}


class FakeOrder:
    """Just enough of an Order for transition() checks that fail before any DB access."""

    def __init__(self, status):
        self.status = status


@pytest.mark.parametrize(
    "current,target,actor,error",
    [
        (S.PLACED, S.DELIVERED, "restaurant_owner", BadRequestError),  # skipping steps
        (S.DELIVERED, S.CANCELLED, "admin", BadRequestError),  # final state
        (S.PENDING_PAYMENT, S.PLACED, "customer", ForbiddenError),  # can't self-confirm payment
        (S.PLACED, S.ACCEPTED, "customer", ForbiddenError),  # customers don't accept
        (S.ACCEPTED, S.CANCELLED, "customer", ForbiddenError),  # too late for customers
        (S.PREPARING, S.DELIVERED, "restaurant_owner", BadRequestError),
    ],
)
def test_illegal_transitions_are_refused(current, target, actor, error):
    with pytest.raises(error):
        transition(None, FakeOrder(current), target, actor, None)

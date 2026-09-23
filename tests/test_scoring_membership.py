from datetime import date
from types import SimpleNamespace as P

import pytest

from damp import membership
from damp.scoring import points_for


@pytest.mark.parametrize("size", [2, 5, 8, 12])
def test_points_rule_is_sane(size):
    """Whatever the rule in damp/scoring.py: a better placement never gives fewer points."""
    pts = [points_for(p, size) for p in range(1, size + 1)]
    assert pts == sorted(pts, reverse=True)
    assert all(p >= 0 for p in pts)


def test_bigger_table_gives_the_winner_more():
    assert points_for(1, 12) > points_for(1, 6)


def pay(d, years=1, id=None):
    return P(paid_on=d, years=years, id=id)


def test_expiry_is_one_year_after_payment():
    assert membership.expires_on([pay(date(2026, 9, 1))]) == date(2027, 9, 1)
    assert membership.expires_on([]) is None


def test_early_renewal_stacks():
    payments = [pay(date(2026, 9, 1)), pay(date(2027, 6, 1))]
    assert membership.expires_on(payments) == date(2028, 9, 1)


def test_multi_year_payment():
    assert membership.expires_on([pay(date(2026, 9, 1), years=3)]) == date(2029, 9, 1)


def test_gap_starts_new_period():
    payments = [pay(date(2024, 9, 1)), pay(date(2026, 1, 10))]
    assert membership.coverage(payments) == [(date(2024, 9, 1), date(2025, 9, 1)), (date(2026, 1, 10), date(2027, 1, 10))]
    assert not membership.is_active(payments, date(2025, 12, 1))
    assert membership.is_active(payments, date(2026, 1, 10))


def test_is_active_checks_the_given_date():
    payments = [pay(date(2026, 9, 1))]
    assert not membership.is_active(payments, date(2026, 8, 31))
    assert membership.is_active(payments, date(2026, 9, 1))
    assert membership.is_active(payments, date(2027, 9, 1))  # last day inclusive
    assert not membership.is_active(payments, date(2027, 9, 2))


def test_leap_day():
    assert membership.expires_on([pay(date(2028, 2, 29))]) == date(2029, 2, 28)


def test_status_keys():
    on = date(2026, 9, 1)
    assert membership.status([], on).key == "never"
    assert membership.status([pay(date(2025, 8, 1))], on).key == "expired"
    assert membership.status([pay(date(2025, 9, 20))], on).key == "soon"
    assert membership.status([pay(date(2026, 8, 1))], on).key == "active"


def test_future_payment_is_pending_not_expired():
    st = membership.status([pay(date(2025, 8, 1)), pay(date(2026, 9, 29))], date(2026, 9, 23))
    assert (st.active, st.key) == (False, "pending")

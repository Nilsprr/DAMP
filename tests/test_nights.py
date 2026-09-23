from datetime import date

import pytest

from damp.extensions import db
from damp.models import Result
from damp.nights import NightError, recalc_points, save_night
from damp.stats import lp_data

from .conftest import make_member


def seats(*ms, wipes=None):
    return [{"member_id": m.id, "wipes": (wipes or {}).get(m.id, 0)} for m in ms]


def payload(period, *tables, d="2026-09-08"):
    return {"date": d, "period_id": period.id, "tables": list(tables)}


def test_save_night_assigns_points_by_table(period, members):
    a, b, c, d, e = members
    night = save_night(payload(period, seats(a, b, c), seats(d, e)))
    db.session.commit()
    got = {r.member.name: (r.placement, r.points) for t in night.tables for r in t.results}
    assert got == {"Anna": (1, 3), "Bert": (2, 2), "Cleo": (3, 1), "Dan": (1, 2), "Eva": (2, 1)}


def test_rejects_unknown_member(period, members):
    with pytest.raises(NightError) as e:
        save_night(payload(period, [{"member_id": 999}, *seats(members[0])]))
    assert any("okänd medlem" in m for m in e.value.errors)


def test_rejects_expired_member_on_night_date(period, members):
    old = make_member("Old", paid_on=date(2025, 1, 1))
    with pytest.raises(NightError) as e:
        save_night(payload(period, seats(old, members[0])))
    assert any("Old" in m and "aktivt medlemskap" in m for m in e.value.errors)


def test_membership_is_checked_against_night_date_not_today(period):
    # Paid 2026-09-01: fine on a 09-08 night, not on a 08-31 night even if entered later.
    a = make_member("A", paid_on=date(2026, 9, 1))
    b = make_member("B", paid_on=date(2026, 8, 1))
    with pytest.raises(NightError):
        save_night(payload(period, seats(a, b), d="2026-08-31"))
    save_night(payload(period, seats(a, b), d="2026-09-08"))


def test_rejects_member_twice_in_a_night(period, members):
    a, b, c, *_ = members
    with pytest.raises(NightError) as e:
        save_night(payload(period, seats(a, b), seats(c, a)))
    assert any("Anna" in m and "bord 1" in m for m in e.value.errors)


def test_rejects_small_table_and_duplicate_date(period, members):
    a, b, c, *_ = members
    with pytest.raises(NightError):
        save_night(payload(period, seats(a)))
    save_night(payload(period, seats(a, b)))
    db.session.commit()
    with pytest.raises(NightError) as e:
        save_night(payload(period, seats(a, c)))
    assert any("redan en kväll" in m for m in e.value.errors)


def test_rejects_impossible_wipes(period, members):
    a, b, *_ = members
    with pytest.raises(NightError):
        save_night(payload(period, seats(a, b, wipes={a.id: 2})))


def test_edit_replaces_results(period, members):
    a, b, c, *_ = members
    night = save_night(payload(period, seats(a, b)))
    db.session.commit()
    save_night(payload(period, seats(c, b, a)), night)
    db.session.commit()
    assert [r.member.name for r in night.tables[0].results] == ["Cleo", "Bert", "Anna"]
    assert db.session.query(Result).count() == 3


def test_recalc_points(period, members, monkeypatch):
    a, b, *_ = members
    save_night(payload(period, seats(a, b)))
    db.session.commit()
    monkeypatch.setattr("damp.nights.points_for", lambda placement, size, wipes=0: 100 if placement == 1 else 0)
    assert recalc_points(period) == 2
    assert sorted(r.points for r in db.session.query(Result)) == [0, 100]


def test_lp_series_and_stats(period, members):
    a, b, c, *_ = members
    save_night(payload(period, seats(a, b, c), d="2026-09-01"))
    save_night(payload(period, seats(b, c), d="2026-09-08"))
    db.session.commit()
    data = lp_data(period)
    assert [n["date"] for n in data["nights"]] == ["2026-09-01", "2026-09-08"]
    by = {p["name"]: p for p in data["players"]}
    assert by["Anna"]["series"] == [0, 3, 3]  # flat when not playing
    assert by["Bert"]["series"] == [0, 2, 4]
    assert by["Cleo"]["series"] == [0, 1, 2]
    assert (by["Bert"]["wins"], by["Bert"]["nights"], by["Bert"]["avg"], by["Bert"]["best"]) == (1, 2, 1.5, 1)
    assert [p["name"] for p in data["players"]] == ["Bert", "Anna", "Cleo"]
    assert [p["rank"] for p in data["players"]] == [1, 2, 3]


def test_ties_share_rank(period, members):
    a, b, c, d, _ = members
    save_night(payload(period, seats(a, b), seats(c, d), d="2026-09-01"))
    db.session.commit()
    data = lp_data(period)
    assert [(p["name"], p["points"], p["rank"]) for p in data["players"]] == [
        ("Anna", 2, 1), ("Cleo", 2, 1), ("Bert", 1, 3), ("Dan", 1, 3)
    ]

import random
from datetime import date

import pytest

from damp.manual import PointsImportError, find_members, find_period, import_totals, parse_totals, spread, tuesdays
from damp.store import from_files

from .conftest import base_files

PASTED = "Anna \t9\nLiam\t14,5\n\nJonathan Hedström \t2\nEva 45\n# kommentar\n"


@pytest.fixture
def store():
    return from_files(base_files())


def test_parse_totals_handles_tabs_spaces_and_decimal_comma():
    assert parse_totals(PASTED) == [("Anna", 9), ("Liam", 14.5), ("Jonathan Hedström", 2), ("Eva", 45)]


def test_parse_totals_reports_bad_lines():
    with pytest.raises(PointsImportError) as e:
        parse_totals("Harald\nIan\tmånga\nIan 3\nian 4")
    assert len(e.value.errors) == 3  # no points, bad number, duplicate name


def test_find_period_by_label_or_slug(store):
    assert find_period("LP1 26/27", store).id == "lp1-26-27"
    assert find_period("lp1 26/27", store).id == "lp1-26-27"
    assert find_period("lp4-25-26", store).label == "LP4 25/26"
    assert find_period("LP2 26/27", store) is None


def test_import_on_date_creates_missing_members(store):
    files = base_files()
    members, manual = files["members.json"], files["manual-points.json"]
    result = import_totals(members, manual, store.period("lp1-26-27"), parse_totals(PASTED), on=date(2026, 9, 22), note="Importerad total")
    assert result == {"created": ["Liam", "Jonathan Hedström"], "matched": 2, "entries": 4}
    assert members[-2:] == [{"id": 6, "first_name": "Liam"}, {"id": 7, "first_name": "Jonathan", "last_name": "Hedström"}]
    assert {(e["member"], e["points"]) for e in manual} == {(1, 9), (6, 14.5), (7, 2), (5, 45)}
    from_files(files)  # still valid


def test_import_rejects_date_outside_lp_and_changes_nothing(store):
    members, manual = [], []
    with pytest.raises(PointsImportError):
        import_totals(members, manual, store.period("lp1-26-27"), [("Someone", 3)], on=date(2027, 1, 1))
    assert members == [] and manual == []


@pytest.mark.parametrize("total", [45, 20, 3, 14.5])
def test_spread_sums_exactly_and_stays_on_given_dates(total):
    dates = tuesdays(date(2026, 3, 23), date(2026, 6, 7))
    assert len(dates) == 11 and all(d.weekday() == 1 for d in dates)
    parts = spread(total, dates, random.Random(1))
    assert sum(p for _, p in parts) == total
    assert all(p >= 0.5 for _, p in parts) and {d for d, _ in parts} <= set(dates)
    assert len({d for d, _ in parts}) == len(parts)


def test_spread_is_reproducible_with_seed():
    dates = tuesdays(date(2026, 3, 23), date(2026, 6, 7))
    assert spread(20, dates, random.Random(7)) == spread(20, dates, random.Random(7))


def test_find_members_by_full_name_display_name_ltu_id_or_unique_first_name():
    members = base_files()["members.json"] + [{"id": 9, "first_name": "Anna", "last_name": "Annorlunda"}]
    ids = lambda name: [m["id"] for m in find_members(name, members)]
    assert ids("anna andersson") == [1]
    assert ids("Cleopatra") == [3]
    assert ids("ANNAND-5") == [1]
    assert ids("Bert") == [2]
    assert ids("Anna") == []  # two Annas: not a unique first name

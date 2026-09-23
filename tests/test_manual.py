import random
from datetime import date

import pytest

from damp.extensions import db
from damp.manual import PointsImportError, find_period, import_totals, parse_totals, spread, tuesdays
from damp.models import ManualPoints, Member
from damp.nights import recalc_points, save_night
from damp.stats import lp_data

from .conftest import make_member

PASTED = "Harald \t9\nLiam\t14,5\n\nJonathan Hedström \t2\nEve 45\n# kommentar\n"


def test_parse_totals_handles_tabs_spaces_and_decimal_comma():
    assert parse_totals(PASTED) == [("Harald", 9), ("Liam", 14.5), ("Jonathan Hedström", 2), ("Eve", 45)]


def test_parse_totals_reports_bad_lines():
    with pytest.raises(PointsImportError) as e:
        parse_totals("Harald\nIan\tmånga\nIan 3\nian 4")
    assert len(e.value.errors) == 3  # no points, bad number, duplicate name


def test_find_period_by_label(period):
    assert find_period("LP1 26/27") is period
    assert find_period("lp1 26/27") is period
    assert find_period(str(period.id)) is period
    assert find_period("LP2 26/27") is None


def test_import_on_date_creates_missing_members(period, members):
    result = import_totals(period, [("Anna", 5), ("Ny Spelare", 14.5)], on=date(2026, 9, 22), note="Importerad total")
    db.session.commit()
    assert result == {"created": ["Ny Spelare"], "matched": 1, "entries": 2}
    new = db.session.query(Member).filter_by(name="Ny Spelare").one()
    assert new.joined_on is None and new.payments == []
    assert sorted(m.points for m in db.session.query(ManualPoints)) == [5, 14.5]


def test_import_rejects_date_outside_lp_and_changes_nothing(period):
    with pytest.raises(PointsImportError):
        import_totals(period, [("Someone", 3)], on=date(2027, 1, 1))
    db.session.rollback()
    assert db.session.query(Member).count() == 0


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
    assert spread(45, dates, random.Random(7)) == spread(45, dates, random.Random(7))


def test_stats_merge_manual_points_with_nights(period, members):
    a, b, c, *_ = members
    save_night({"date": "2026-09-08", "period_id": period.id, "tables": [[{"member_id": a.id}, {"member_id": b.id}]]})
    import_totals(period, [("Anna", 10), ("Cleo", 14.5)], on=date(2026, 9, 22))
    db.session.commit()
    data = lp_data(period)
    assert [n["label"] for n in data["nights"]] == ["8 sep", "22 sep"]
    by = {p["name"]: p for p in data["players"]}
    assert by["Anna"]["series"] == [0, 2, 12] and by["Anna"]["nights"] == 2
    assert (by["Anna"]["wins"], by["Anna"]["avg"]) == (1, 1.0)  # placements only from the real night
    assert by["Cleo"]["series"] == [0, 0, 14.5] and by["Cleo"]["points"] == 14.5
    assert (by["Cleo"]["wins"], by["Cleo"]["avg"], by["Cleo"]["best"], by["Cleo"]["wipes"]) == (None, None, None, None)
    assert by["Cleo"]["has_manual"] and not by["Bert"]["has_manual"]
    assert [p["name"] for p in data["players"]] == ["Cleo", "Anna", "Bert"]


def test_recalc_leaves_manual_points_alone(period, members):
    import_totals(period, [("Anna", 7.5)], on=date(2026, 9, 22))
    db.session.commit()
    assert recalc_points(period) == 0
    assert db.session.query(ManualPoints).one().points == 7.5


def test_cli_import(app, period, tmp_path):
    f = tmp_path / "lp1.tsv"
    f.write_text("Erik\t25\nLiam\t14,5\n", encoding="utf-8")
    runner = app.test_cli_runner()
    r = runner.invoke(args=["import-points", str(f), "--lp", "LP1 26/27", "--date", "2026-09-22"])
    assert r.exit_code == 0, r.output
    assert "totalt 39,5 poäng" in r.output
    r = runner.invoke(args=["import-points", str(f), "--lp", "LP1 26/27", "--date", "2026-09-22"])
    assert r.exit_code != 0 and "--replace" in r.output  # no double import
    r = runner.invoke(args=["import-points", str(f), "--lp", "LP1 26/27", "--date", "2026-09-22", "--replace"])
    assert r.exit_code == 0 and db.session.query(ManualPoints).count() == 2
    assert db.session.query(Member).count() == 2  # members matched, not duplicated


def test_public_page_shows_decimal_and_missing_stats(client, period):
    import_totals(period, [("Liam", 14.5)], on=date(2026, 9, 22))
    db.session.commit()
    html = client.get("/").text
    assert "14,5" in html and "1 kväll" in html


def test_admin_manual_points_crud(admin_client, period):
    make_member("Erik")
    r = admin_client.post(f"/admin/lp/{period.id}/manuella-poang", data={"member": "erik", "date": "2026-09-22", "points": "25"})
    assert r.status_code == 302
    entry = db.session.query(ManualPoints).one()
    assert entry.points == 25
    page = admin_client.get(f"/admin/lp/{period.id}/manuella-poang").text
    assert "Erik" in page and "totalt 25" in page
    admin_client.post(f"/admin/manuella-poang/{entry.id}", data={"date": "2026-09-22", "points": "24,5", "note": "rättad"})
    assert db.session.get(ManualPoints, entry.id).points == 24.5
    r = admin_client.post(f"/admin/lp/{period.id}/manuella-poang", data={"member": "Okänd", "date": "2026-09-22", "points": "3"}, follow_redirects=True)
    assert "Ingen medlem heter" in r.text
    r = admin_client.post(f"/admin/lp/{period.id}/manuella-poang", data={"member": "Erik", "date": "2027-02-01", "points": "3"}, follow_redirects=True)
    assert "måste ligga inom" in r.text
    admin_client.post(f"/admin/manuella-poang/{entry.id}/radera")
    assert db.session.query(ManualPoints).count() == 0


def test_member_and_period_with_manual_points_cannot_be_deleted(admin_client, period):
    import_totals(period, [("Erik", 25)], on=date(2026, 9, 22))
    db.session.commit()
    erik = db.session.query(Member).one()
    admin_client.post(f"/admin/medlemmar/{erik.id}/radera")
    admin_client.post(f"/admin/lp/{period.id}/radera")
    assert db.session.query(Member).count() == 1 and db.session.get(type(period), period.id) is not None


def test_member_without_join_date_renders_in_admin(admin_client, period):
    import_totals(period, [("Erik", 25)], on=date(2026, 9, 22))
    db.session.commit()
    erik = db.session.query(Member).one()
    assert admin_client.get("/admin/medlemmar?sort=gick-med").status_code == 200
    assert admin_client.get(f"/admin/medlemmar/{erik.id}").status_code == 200
    r = admin_client.post(f"/admin/medlemmar/{erik.id}", data={"name": "Erik", "joined_on": ""})
    assert r.status_code == 302 and db.session.get(Member, erik.id).joined_on is None

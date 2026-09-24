import json
from datetime import date

import pytest

from damp.store import DataError, Member, assign_public_names, dumps, from_files, load, read_files

from .conftest import base_files, seat


def errors_for(**changes) -> list[str]:
    """Errors from loading the base data with some files replaced.

    Keyword names become paths: members -> members.json, manual_points -> manual-points.json,
    tables_2026_09_08_1 -> tables/2026-09-08-1.json.
    """
    files = base_files()
    for key, content in changes.items():
        path = ("tables/" + key[7:] if key.startswith("tables_") else key).replace("_", "-") + ".json"
        files[path] = content
    with pytest.raises(DataError) as e:
        from_files(files)
    return e.value.errors


def test_loads_base_data(data_dir):
    store = load(data_dir)
    assert [p.id for p in store.periods] == ["lp1-26-27", "lp4-25-26"]  # newest first
    lp1 = store.period("lp1-26-27")
    assert lp1.label == "LP1 26/27"
    assert [t.id for t in lp1.tables] == ["2026-09-01-1", "2026-09-01-2"]
    first = lp1.tables[0]
    assert first.period is lp1 and first.note == "Första bordet" and first.number == 1
    assert [(r.member.name, r.placement, r.points) for r in first.results] == [
        ("Anna Andersson", 1, 3), ("Bert Berg", 2, 2), ("Cleo Carlsson", 3, 1),
    ]
    anna = store.members[1]
    assert (anna.ltu_id, anna.joined_on) == ("annand-5", date(2025, 10, 21))
    assert store.news[0].body_md == "Vi ses **18:30**."


def test_names():
    store = from_files(base_files())
    cleo = store.members[3]
    assert (cleo.name, cleo.full_name, cleo.public_name) == ("Cleo Carlsson", 'Cleo "Cleopatra" Carlsson', "Cleopatra")
    anna = store.members[1]
    assert (anna.full_name, anna.public_name) == ("Anna Andersson", "Anna")


def test_shared_first_names_get_an_initial():
    members = [
        Member(1, "Nils", "Salomonsson"), Member(2, "Nils", "Kjellberg"), Member(3, "Carl", "Witt"),
        Member(4, "Carl", "Wall"), Member(5, "Nils", "Svensson", display_name="Nisse"), Member(6, "Eve"),
    ]
    assign_public_names(members)
    assert [m.public_name for m in members] == ["Nils S.", "Nils K.", "Carl Witt", "Carl Wall", "Nisse", "Eve"]


def test_stored_points_are_used_as_is():
    files = base_files()
    files["tables/2026-09-01-1.json"]["players"][0]["points"] = 99.5
    store = from_files(files)
    assert store.tables[0].results[0].points == 99.5


def test_several_tables_the_same_day_may_share_players():
    files = base_files()
    files["tables/2026-09-01-3.json"] = {"players": [seat(1, 2), seat(4, 1)]}  # Anna and Dan again: a final table
    assert len(from_files(files).tables) == 3


def test_unknown_member():
    assert any("okänd medlem 42" in e for e in errors_for(tables_2026_09_08_1={"players": [seat(1, 2), seat(42, 1)]}))


def test_member_twice_at_a_table():
    assert any("två gånger" in e for e in errors_for(tables_2026_09_08_1={"players": [seat(1, 2), seat(1, 1)]}))


def test_table_needs_two_players():
    assert any("minst 2 spelare" in e for e in errors_for(tables_2026_09_08_1={"players": [seat(1, 1)]}))


def test_wipes_must_fit_the_table():
    assert any("wipes" in e for e in errors_for(tables_2026_09_08_1={"players": [seat(1, 2, wipes=2), seat(2, 1)]}))


def test_points_are_required():
    assert any("poäng saknas" in e for e in errors_for(tables_2026_09_08_1={"players": [{"member": 1}, seat(2, 1)]}))


def test_table_outside_every_lp():
    assert any("ligger inte i något LP" in e for e in errors_for(tables_2026_07_07_1={"players": [seat(1, 2), seat(2, 1)]}))


@pytest.mark.parametrize("key", ["tables_2026_13_40_1", "tables_2026_09_08_0"])
def test_invalid_table_filename(key):
    files = base_files()
    files[("tables/" + key[7:]).replace("_", "-") + ".json"] = {"players": [seat(1, 2), seat(2, 1)]}
    with pytest.raises(DataError):
        from_files(files)


def test_overlapping_periods():
    periods = base_files()["periods.json"] + [{"start_year": 2026, "lp": 2, "starts_on": "2026-10-20", "ends_on": "2027-01-17"}]
    assert any("överlappar" in e for e in errors_for(periods=periods))


@pytest.mark.parametrize(
    "extra, message",
    [
        ({"id": 9, "first_name": "anna", "last_name": "andersson"}, "finns redan"),
        ({"id": 9, "first_name": "Ny", "last_name": "Person", "ltu_id": "ANNAND-5"}, "LTU-id"),
        ({"id": 9, "first_name": "Ny", "last_name": "Person", "display_name": "cleopatra"}, "visningsnamnet"),
        ({"id": 9, "last_name": "Utan förnamn"}, "first_name"),
        ({"id": 1, "first_name": "Samma", "last_name": "Id"}, "id 1 finns redan"),
        ({"id": 9, "first_name": "Ny", "joined_on": "igår"}, "joined_on"),
    ],
)
def test_member_rules(extra, message):
    members = base_files()["members.json"] + [extra]
    assert any(message in e for e in errors_for(members=members))


def test_manual_points_outside_every_lp():
    assert any("ligger inte i något LP" in e for e in errors_for(manual_points=[{"date": "2026-07-01", "member": 1, "points": 3}]))


def test_all_problems_are_reported_at_once():
    errs = errors_for(
        tables_2026_09_08_1={"players": [seat(1, 1)]},
        manual_points=[{"date": "2026-09-08", "member": 77, "points": 3}],
    )
    assert len(errs) == 2


def test_read_files_rejects_unknown_files_and_bad_json(data_dir):
    (data_dir / "tables" / "notes.json").write_text("{}")
    (data_dir / "news.json").write_text("{not json")
    with pytest.raises(DataError) as e:
        read_files(data_dir)
    assert len(e.value.errors) == 2


def test_other_files_and_the_history_are_ignored(data_dir):
    (data_dir / "lp1-26-27.tsv").write_text("Anna 3\n")
    (data_dir / "history").mkdir()
    (data_dir / "history" / "2026-09.json").write_text("not even json")
    assert "members.json" in read_files(data_dir)


def test_dumps_format():
    text = dumps({"points": 24.0, "half": 14.5, "name": "Hedström"})
    assert text == '{\n  "points": 24,\n  "half": 14.5,\n  "name": "Hedström"\n}\n'
    assert json.loads(text)["points"] == 24

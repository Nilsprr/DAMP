from damp.stats import lp_data
from damp.store import from_files

from .conftest import base_files, seat


def lp1(files=None):
    return from_files(files or base_files()).period("lp1-26-27")


def by_name(data):
    return {p["name"]: p for p in data["players"]}


def test_standings_from_two_tables():
    data = lp_data(lp1())
    # Ties on points are listed by wins, then average placement; the rank itself is shared.
    assert [(p["name"], p["rank"]) for p in data["players"]] == [("Anna", 1), ("Dan", 2), ("Bert", 2), ("Eva", 4), ("Cleopatra", 4)]
    anna = by_name(data)["Anna"]
    assert anna["full_name"] == "Anna Andersson"
    assert (anna["points"], anna["tables"], anna["wins"], anna["avg"], anna["best"], anna["wipes"]) == (3, 1, 1, 1, 1, 0)
    assert anna["series"] == [0, 3]
    assert anna["results"] == [{"date": 0, "table": 1, "placement": 1, "size": 3, "points": 3, "wipes": 0, "manual": False}]
    assert by_name(data)["Cleopatra"]["full_name"] == 'Cleo "Cleopatra" Carlsson'
    assert data["tables"] == 2
    assert data["dates"] == [{"date": "2026-09-01", "label": "1 sep", "tables": 2, "players": 5}]


def test_series_is_cumulative_and_flat_when_absent():
    files = base_files()
    files["tables/2026-09-08-1.json"] = {"players": [seat(2, 2), seat(3, 1)]}
    data = lp_data(lp1(files))
    players = by_name(data)
    assert [d["date"] for d in data["dates"]] == ["2026-09-01", "2026-09-08"]
    assert players["Anna"]["series"] == [0, 3, 3]
    assert players["Bert"]["series"] == [0, 2, 4]
    assert players["Bert"]["tables"] == 2


def test_two_tables_the_same_day_add_up():
    files = base_files()
    files["tables/2026-09-01-3.json"] = {"players": [seat(1, 2), seat(4, 1)]}
    anna = by_name(lp_data(lp1(files)))["Anna"]
    assert (anna["points"], anna["tables"], anna["series"]) == (5, 2, [0, 5])
    assert [r["table"] for r in anna["results"]] == [1, 3]


def test_manual_points_count_but_are_not_tables():
    files = base_files()
    files["manual-points.json"] = [{"date": "2026-09-15", "member": 5, "points": 14.5}, {"date": "2026-09-15", "member": 1, "points": 1}]
    data = lp_data(lp1(files))
    eva = by_name(data)["Eva"]
    assert eva["points"] == 15.5
    assert eva["has_manual"] and eva["tables"] == 1
    assert data["dates"][-1] == {"date": "2026-09-15", "label": "15 sep", "tables": 0, "players": 2}


def test_manual_only_player_has_no_table_stats():
    files = base_files()
    files["manual-points.json"] = [{"date": "2026-04-01", "member": 2, "points": 7}]
    data = lp_data(from_files(files).period("lp4-25-26"))
    [bert] = data["players"]
    assert (bert["tables"], bert["wins"], bert["avg"], bert["best"], bert["wipes"]) == (None, None, None, None, None)

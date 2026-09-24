import json

import pytest

from damp import history

from .conftest import seat, write_files


@pytest.fixture
def runner(app):
    return app.test_cli_runner()


def read(data_dir, path):
    return json.loads((data_dir / path).read_text())


def test_recalc_points_rewrites_stale_points_and_logs_it(runner, data_dir):
    write_files(data_dir, {"tables/2026-09-08-1.json": {"players": [seat(1, 10), seat(2, 1)]}})
    result = runner.invoke(args=["recalc-points", "--lp", "LP1 26/27"])
    assert result.exit_code == 0, result.output
    assert "1 resultat ändrades på 1 bord" in result.output
    assert [s["points"] for s in read(data_dir, "tables/2026-09-08-1.json")["players"]] == [2, 1]
    [event] = history.read_all(data_dir)
    assert event["lps"] == ["lp1-26-27"] and event["by"] == "test@example.com"
    assert event["details"] == ["2026-09-08, bord 1"]


def test_recalc_points_without_changes_logs_nothing(runner, data_dir):
    assert runner.invoke(args=["recalc-points"]).exit_code == 0
    assert history.read_all(data_dir) == []


def test_import_points_on_a_date(runner, data_dir, tmp_path):
    src = tmp_path / "totals.tsv"
    src.write_text("Anna\t9\nNy Spelare\t14,5\n")
    result = runner.invoke(args=["import-points", str(src), "--lp", "LP1 26/27", "--date", "2026-09-22"])
    assert result.exit_code == 0, result.output
    assert "Nya medlemmar (1): Ny Spelare" in result.output
    assert read(data_dir, "members.json")[-1] == {"id": 6, "first_name": "Ny", "last_name": "Spelare"}
    assert read(data_dir, "manual-points.json") == [
        {"date": "2026-09-22", "member": 1, "points": 9, "note": "Importerad total"},
        {"date": "2026-09-22", "member": 6, "points": 14.5, "note": "Importerad total"},
    ]
    [event] = history.read_all(data_dir)
    assert event["message"].startswith("Importerade totaler i LP1 26/27")
    assert event["lps"] == ["lp1-26-27"]
    assert "Anna: 9 p" in event["details"]


def test_import_points_refuses_to_add_twice_without_replace(runner, tmp_path):
    src = tmp_path / "totals.tsv"
    src.write_text("Anna\t9\n")
    args = ["import-points", str(src), "--lp", "LP1 26/27", "--date", "2026-09-22"]
    assert runner.invoke(args=args).exit_code == 0
    assert runner.invoke(args=args).exit_code != 0
    assert runner.invoke(args=args + ["--replace"]).exit_code == 0

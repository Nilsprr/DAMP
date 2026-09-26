import copy
import os
import subprocess

import pytest

from damp import create_app
from damp.store import write_json

MEMBERS = [
    {"id": 1, "first_name": "Anna", "last_name": "Andersson", "ltu_id": "annand-5", "joined_on": "2025-10-21"},
    {"id": 2, "first_name": "Bert", "last_name": "Berg"},
    {"id": 3, "first_name": "Cleo", "last_name": "Carlsson", "display_name": "Cleopatra"},
    {"id": 4, "first_name": "Dan", "last_name": "Dahl"},
    {"id": 5, "first_name": "Eva", "last_name": "Ek"},
]
PERIODS = [
    {"start_year": 2025, "lp": 4, "starts_on": "2026-03-23", "ends_on": "2026-06-07"},
    {"start_year": 2026, "lp": 1, "starts_on": "2026-08-31", "ends_on": "2026-11-01"},
]
NEWS = [{"id": 1, "title": "Välkommen", "published_at": "2026-08-30T12:00", "body": "Vi ses **18:30**."}]


def seat(member, points, wipes=0):
    return {"member": member, "wipes": wipes, "points": points}


# Two tables on 2026-09-01 (LP1 26/27): Anna, Bert, Cleo (in finishing order), and Dan, Eva.
TABLE_1 = {"note": "Första bordet", "players": [seat(1, 3), seat(2, 2), seat(3, 1)]}
TABLE_2 = {"players": [seat(4, 2), seat(5, 1)]}


def base_files() -> dict:
    return copy.deepcopy(
        {
            "members.json": MEMBERS,
            "periods.json": PERIODS,
            "tables/2026-09-01-1.json": TABLE_1,
            "tables/2026-09-01-2.json": TABLE_2,
            "manual-points.json": [],
            "news.json": NEWS,
        }
    )


def write_files(data_dir, files: dict):
    for path, content in files.items():
        write_json(data_dir / path, content)


def git(repo, *args, date="2026-09-26T18:53:12+02:00"):
    """Run git in `repo` as a fixed author at a fixed time, whatever the global git config says."""
    env = {**os.environ, "GIT_AUTHOR_DATE": date, "GIT_COMMITTER_DATE": date}
    cmd = ["git", "-C", str(repo), "-c", "user.name=Nils", "-c", "user.email=nils@example.com", "-c", "commit.gpgsign=false", *args]
    subprocess.run(cmd, check=True, capture_output=True, env=env)


def simple_points(placement, table_size, wipes=0):
    return table_size - placement + 1


@pytest.fixture(autouse=True)
def fixed_scoring(monkeypatch):
    """Mechanics tests use a fixed rule, so editing damp/scoring.py doesn't break them."""
    monkeypatch.setattr("damp.scoring.points_for", simple_points)
    monkeypatch.setattr("damp.cli.points_for", simple_points)


@pytest.fixture(autouse=True)
def fixed_author(monkeypatch):
    monkeypatch.setattr("damp.history.local_author", lambda: "test@example.com")


@pytest.fixture
def data_dir(tmp_path):
    d = tmp_path / "data"
    write_files(d, base_files())
    return d


@pytest.fixture
def app(data_dir):
    return create_app(data_dir)


@pytest.fixture
def client(app):
    return app.test_client()

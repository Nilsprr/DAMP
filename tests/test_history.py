from datetime import datetime, timezone

import pytest

from damp import history

from .conftest import git


def test_make_event_cleans_up():
    at = datetime(2026, 9, 24, 10, 38, 5, 123456, tzinfo=timezone.utc)
    event = history.make_event("  Nytt   bord ", ["lp1-26-27", "lp1-26-27"], ["1.  Anna: 3 p"], by="a@b.se", at=at)
    assert event == {"at": "2026-09-24T10:38:05Z", "by": "a@b.se", "message": "Nytt bord", "lps": ["lp1-26-27"], "details": ["1. Anna: 3 p"]}
    assert "details" not in history.make_event("x", by="a@b.se")


@pytest.mark.parametrize("message, lps, details", [("", [], []), ("x", ["lp5-26-27"], []), ("x", "lp1-26-27", []), ("x", [], [1])])
def test_make_event_rejects_bad_input(message, lps, details):
    with pytest.raises(ValueError):
        history.make_event(message, lps, details, by="a@b.se")


def test_append_and_read_across_months(tmp_path):
    first = history.make_event("i augusti", by="a", at=datetime(2026, 8, 31, 23, 0, tzinfo=timezone.utc))
    second = history.make_event("i september", by="a", at=datetime(2026, 9, 1, 8, 0, tzinfo=timezone.utc))
    assert history.append(tmp_path, first) == "history/2026-08.json"
    assert history.append(tmp_path, second) == "history/2026-09.json"
    assert [e["message"] for e in history.read_all(tmp_path)] == ["i september", "i augusti"]


def test_read_all_without_a_log(tmp_path):
    assert history.read_all(tmp_path) == []


def test_own_commits_leave_out_admin_saves_and_merges(tmp_path):
    git(tmp_path, "init", "-q", "-b", "master")
    git(tmp_path, "commit", "-q", "--allow-empty", "-m", "Ny om-sida\n\nQR-koder längst ner\n\n  och kortare text  ", date="2026-09-26T18:53:12+02:00")
    git(tmp_path, "commit", "-q", "--allow-empty", "-m", "Raderad nyhet: X\n\nVia DAMP-admin av a@b.se", date="2026-09-26T18:54:00+02:00")
    git(tmp_path, "checkout", "-q", "-b", "sido")
    git(tmp_path, "commit", "-q", "--allow-empty", "-m", "På en sidogren", date="2026-09-26T18:55:00+02:00")
    git(tmp_path, "checkout", "-q", "master")
    git(tmp_path, "merge", "-q", "--no-ff", "sido", "-m", "Merge branch 'sido'", date="2026-09-26T18:56:00+02:00")

    commits = history.own_commits(tmp_path)
    assert [c["message"] for c in commits] == ["På en sidogren", "Ny om-sida"]
    first = commits[-1]
    assert first["at"] == "2026-09-26T16:53:12Z" and first["by"] == "nils@example.com" and first["lps"] == []
    assert first["details"] == ["QR-koder längst ner", "och kortare text"] and len(first["sha"]) == 40
    assert "details" not in commits[0]


def test_own_commits_outside_a_repository(tmp_path, monkeypatch):
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))
    assert history.own_commits(tmp_path) == []

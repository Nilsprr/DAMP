"""The local admin API (damp/devapi.py). Same contract as the Cloudflare function."""

import json

import pytest

from damp import history

from .conftest import git, seat

NEW_TABLE = {"players": [seat(1, 2), seat(2, 1)]}


def get_data(client):
    resp = client.get("/admin/api/data")
    assert resp.status_code == 200
    return resp.get_json()


def post_save(client, base, changes, message="test", lps=(), details=()):
    return client.post("/admin/api/save", json={"base": base, "message": message, "lps": list(lps), "details": list(details), "changes": changes})


def test_data_returns_every_file_and_a_version(client):
    body = get_data(client)
    assert set(body["files"]) == {"members.json", "periods.json", "tables/2026-09-01-1.json", "tables/2026-09-01-2.json", "manual-points.json", "news.json"}
    assert body["user"]["dev"] is True
    assert len(body["version"]) == 40


def test_save_writes_the_file_in_the_shared_format(client, data_dir):
    base = get_data(client)["version"]
    resp = post_save(client, base, {"tables/2026-09-08-1.json": NEW_TABLE})
    assert resp.status_code == 200
    assert resp.get_json()["rebased"] is False
    text = (data_dir / "tables/2026-09-08-1.json").read_text()
    assert text.startswith('{\n  "players": [') and text.endswith("\n")
    assert json.loads(text) == NEW_TABLE
    assert resp.get_json()["version"] == get_data(client)["version"] != base


def test_every_save_is_logged(client, data_dir):
    base = get_data(client)["version"]
    post_save(client, base, {"tables/2026-09-08-1.json": NEW_TABLE}, "Nytt bord: tis 8 sep 2026, bord 1", ["lp1-26-27"], ["1. Anna Andersson: 2 p"])
    [event] = client.get("/admin/api/history").get_json()["events"]
    assert event["message"] == "Nytt bord: tis 8 sep 2026, bord 1"
    assert event["lps"] == ["lp1-26-27"] and event["details"] == ["1. Anna Andersson: 2 p"]
    assert event["by"] == "test@example.com" and event["at"].endswith("Z")
    assert (data_dir / "history" / f"{event['at'][:7]}.json").exists()
    assert "history" not in json.dumps(sorted(get_data(client)["files"]))  # the log isn't part of the data


def test_history_lists_commits_made_outside_the_admin(client, data_dir):
    git(data_dir, "init", "-q")
    git(data_dir, "commit", "-q", "--allow-empty", "-m", "Ny om-sida")
    git(data_dir, "commit", "-q", "--allow-empty", "-m", "Raderad nyhet: X\n\nVia DAMP-admin av a@b.se", date="2026-09-26T18:54:00+02:00")
    body = client.get("/admin/api/history").get_json()
    assert [c["message"] for c in body["commits"]] == ["Ny om-sida"]
    assert body["events"] == []


def test_history_is_newest_first(client):
    for i in range(3):
        post_save(client, get_data(client)["version"], {"news.json": []}, f"ändring {i}")
    assert [e["message"] for e in client.get("/admin/api/history").get_json()["events"]] == ["ändring 2", "ändring 1", "ändring 0"]


@pytest.mark.parametrize("event", [{"message": ""}, {"message": "x", "lps": ["LP1 26/27"]}, {"message": "x", "details": "not a list"}])
def test_bad_events_are_refused(client, event):
    body = {"base": get_data(client)["version"], "changes": {"news.json": []}, **event}
    assert client.post("/admin/api/save", json=body).status_code == 400


def test_null_deletes(client, data_dir):
    base = get_data(client)["version"]
    assert post_save(client, base, {"tables/2026-09-01-2.json": None}).status_code == 200
    assert not (data_dir / "tables/2026-09-01-2.json").exists()


def test_stale_base_with_other_files_changed_is_merged(client):
    base = get_data(client)["version"]
    assert post_save(client, base, {"tables/2026-09-08-1.json": NEW_TABLE}).status_code == 200
    resp = post_save(client, base, {"news.json": []})
    assert resp.status_code == 200 and resp.get_json()["rebased"] is True


def test_stale_base_with_the_same_file_changed_is_a_conflict(client, data_dir):
    base = get_data(client)["version"]
    assert post_save(client, base, {"tables/2026-09-08-1.json": NEW_TABLE}).status_code == 200
    resp = post_save(client, base, {"tables/2026-09-08-1.json": {"players": [seat(3, 2), seat(4, 1)]}})
    assert resp.status_code == 409
    assert resp.get_json() == {"error": "conflict", "paths": ["tables/2026-09-08-1.json"]}
    assert json.loads((data_dir / "tables/2026-09-08-1.json").read_text()) == NEW_TABLE


def test_unknown_base_is_a_conflict(client):
    assert post_save(client, "0" * 40, {"news.json": []}).status_code == 409


@pytest.mark.parametrize(
    "path", ["../evil.json", "tables/../../x.json", "damp/scoring.py", "tables/2026-9-1-1.json", "Members.json", "history/2026-09.json", "nights/2026-09-01.json"]
)
def test_only_data_files_can_be_written(client, path):
    resp = post_save(client, get_data(client)["version"], {path: {}})
    assert resp.status_code == 400


def test_invalid_data_is_refused_and_nothing_written(client, data_dir):
    resp = post_save(client, get_data(client)["version"], {"tables/2026-09-08-1.json": {"players": [seat(1, 2), seat(99, 1)]}})
    assert resp.status_code == 422
    assert any("okänd medlem 99" in e for e in resp.get_json()["errors"])
    assert not (data_dir / "tables/2026-09-08-1.json").exists()
    assert history.read_all(data_dir) == []


def test_form_posts_are_refused(client):
    resp = client.post("/admin/api/save", data={"changes": "x"})
    assert resp.status_code == 400

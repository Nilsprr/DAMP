from datetime import datetime, timezone

import pytest

from damp import history


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

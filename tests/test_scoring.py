"""The real rule in damp/scoring.py (these tests don't use the fixed test rule)."""

import pytest

from damp import scoring


@pytest.fixture(autouse=True)
def fixed_scoring():
    """Override conftest: test the actual points_for."""


@pytest.mark.parametrize("size", [2, 5, 8, 12])
def test_better_placement_never_gives_fewer_points(size):
    pts = [scoring.points_for(p, size) for p in range(1, size + 1)]
    assert pts == sorted(pts, reverse=True)
    assert all(p >= 0 for p in pts)


def test_bigger_table_gives_the_winner_more():
    assert scoring.points_for(1, 12) > scoring.points_for(1, 6)


def test_more_wipes_never_gives_fewer_points():
    assert scoring.points_for(3, 8, 2) >= scoring.points_for(3, 8, 0)


def test_points_table_is_points_for():
    table = scoring.points_table(max_size=10)
    assert set(table) == {str(n) for n in range(2, 11)}
    for size in (2, 7, 10):
        rows = table[str(size)]
        assert len(rows) == size and all(len(r) == size for r in rows)
        assert rows[0][0] == scoring.points_for(1, size, 0)
        assert rows[size - 1][size - 1] == scoring.points_for(size, size, size - 1)

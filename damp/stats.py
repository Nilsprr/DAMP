"""Standings, cumulative point series and per-player stats for one LP."""

from collections import Counter

from .store import Member, Period
from .util import short_date


def _num(x: float) -> int | float:
    """Clean JSON numbers: 24.0 -> 24, 14.5 -> 14.5."""
    x = round(x, 2)
    return int(x) if x == int(x) else x


def lp_data(period: Period) -> dict:
    """Everything the viewer needs for one LP, JSON-ready.

    The timeline ("dates") is every date with points: tables plus manual points.
    players[i].series has len(dates) + 1 values: 0 at the start, then the cumulative
    total after each date (flat when the player has no points that date). Players are
    sorted by rank (points, then wins, then average placement). Tables / wins / avg /
    best / wipes are None for a player without any placements (only manual points).
    """
    tables = period.tables
    manual = period.manual_points
    dates = sorted({t.date for t in tables} | {m.date for m in manual})
    index = {d: i for i, d in enumerate(dates)}
    tables_on = Counter(t.date for t in tables)
    players: dict[int, dict] = {}
    per_date_players: list[set[int]] = [set() for _ in dates]

    def entry(member: Member) -> dict:
        p = players.get(member.id)
        if p is None:
            p = players[member.id] = {
                "id": member.id,
                "name": member.public_name,
                "full_name": member.full_name,
                "per_date": [0.0] * len(dates),
                "results": [],
            }
        return p

    for table in tables:
        i = index[table.date]
        size = len(table.results)
        for r in table.results:
            p = entry(r.member)
            p["per_date"][i] += r.points
            per_date_players[i].add(r.member_id)
            p["results"].append(
                {"date": i, "table": table.number, "placement": r.placement, "size": size,
                 "points": _num(r.points), "wipes": r.wipes, "manual": False}
            )
    for mp in manual:
        i = index[mp.date]
        p = entry(mp.member)
        p["per_date"][i] += mp.points
        per_date_players[i].add(mp.member_id)
        p["results"].append(
            {"date": i, "table": None, "placement": None, "size": None,
             "points": _num(mp.points), "wipes": None, "manual": True}
        )

    rows = []
    for p in players.values():
        results = sorted(p.pop("results"), key=lambda r: (r["date"], r["manual"], r["table"] or 0))
        series, total = [0], 0.0
        for pts in p.pop("per_date"):
            total += pts
            series.append(_num(total))
        placements = [r["placement"] for r in results if r["placement"] is not None]
        rows.append(
            p
            | {
                "points": _num(total),
                "tables": len(placements) if placements else None,
                "wins": placements.count(1) if placements else None,
                "avg": round(sum(placements) / len(placements), 2) if placements else None,
                "best": min(placements) if placements else None,
                "wipes": sum(r["wipes"] for r in results if r["wipes"] is not None) if placements else None,
                "has_manual": any(r["manual"] for r in results),
                "series": series,
                "results": results,
            }
        )

    rows.sort(
        key=lambda r: (
            -r["points"],
            -(r["wins"] or 0),
            r["avg"] if r["avg"] is not None else float("inf"),
            r["name"].casefold(),
        )
    )
    # Competition ranking on points: 1, 2, 2, 4
    for i, r in enumerate(rows):
        r["rank"] = rows[i - 1]["rank"] if i and rows[i - 1]["points"] == r["points"] else i + 1

    return {
        "period": {"id": period.id, "label": period.label},
        "tables": len(tables),
        "dates": [
            {"date": d.isoformat(), "label": short_date(d), "tables": tables_on[d], "players": len(per_date_players[i])}
            for i, d in enumerate(dates)
        ],
        "players": rows,
    }

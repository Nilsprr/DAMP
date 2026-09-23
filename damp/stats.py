"""Standings, cumulative point series and per-player stats for one LP."""

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from .extensions import db
from .models import ManualPoints, Night, Period, PokerTable, Result
from .util import short_date


def _num(x: float) -> int | float:
    """Clean JSON numbers: 24.0 -> 24, 14.5 -> 14.5."""
    x = round(x, 2)
    return int(x) if x == int(x) else x


def _nights(period: Period) -> list[Night]:
    return list(
        db.session.scalars(
            select(Night)
            .where(Night.period_id == period.id)
            .order_by(Night.date)
            .options(selectinload(Night.tables).selectinload(PokerTable.results).selectinload(Result.member))
        )
    )


def _manual(period: Period) -> list[ManualPoints]:
    return list(
        db.session.scalars(
            select(ManualPoints)
            .where(ManualPoints.period_id == period.id)
            .options(selectinload(ManualPoints.member))
        )
    )


def lp_data(period: Period) -> dict:
    """Everything the viewer needs for one LP, JSON-ready.

    The timeline ("nights") is every date with points: nights with tables plus
    dates with manual points. players[i].series has len(nights) + 1 values: 0 at
    the start, then the cumulative total after each date (flat when the player
    has no points that date). Players are sorted by rank (points, then wins, then
    average placement). Wins / avg / best / wipes are None for a player without
    any placements (only manual points).
    """
    nights = _nights(period)
    manual = _manual(period)
    dates = sorted({n.date for n in nights} | {m.date for m in manual})
    index = {d: i for i, d in enumerate(dates)}
    notes = {n.date: n.note for n in nights}
    players: dict[int, dict] = {}
    per_date_players: list[set[int]] = [set() for _ in dates]

    def entry(member) -> dict:
        p = players.get(member.id)
        if p is None:
            p = players[member.id] = {
                "id": member.id,
                "name": member.public_name,
                "per_date": [0.0] * len(dates),
                "results": [],
            }
        return p

    for night in nights:
        i = index[night.date]
        for table in night.tables:
            size = len(table.results)
            for r in table.results:
                p = entry(r.member)
                p["per_date"][i] += r.points
                per_date_players[i].add(r.member_id)
                p["results"].append(
                    {"night": i, "table": table.table_no, "placement": r.placement, "size": size,
                     "points": _num(r.points), "wipes": r.wipes, "manual": False}
                )
    for mp in manual:
        i = index[mp.date]
        p = entry(mp.member)
        p["per_date"][i] += mp.points
        per_date_players[i].add(mp.member_id)
        p["results"].append(
            {"night": i, "table": None, "placement": None, "size": None,
             "points": _num(mp.points), "wipes": None, "manual": True}
        )

    rows = []
    for p in players.values():
        results = sorted(p.pop("results"), key=lambda r: (r["night"], r["manual"]))
        series, total = [0], 0.0
        for pts in p.pop("per_date"):
            total += pts
            series.append(_num(total))
        placements = [r["placement"] for r in results if r["placement"] is not None]
        rows.append(
            p
            | {
                "points": _num(total),
                "nights": len({r["night"] for r in results}),
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
        "nights": [
            {"date": d.isoformat(), "label": short_date(d), "note": notes.get(d), "players": len(per_date_players[i])}
            for i, d in enumerate(dates)
        ],
        "players": rows,
    }

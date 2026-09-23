"""Creating and editing poker nights from the admin night editor's JSON payload.

Payload shape (placement = position in the list, 1 = winner):
    {"date": "2026-09-22", "period_id": 3, "note": "",
     "tables": [[{"member_id": 12, "wipes": 1}, {"member_id": 7, "wipes": 0}, ...], ...]}
"""

from dataclasses import dataclass

from sqlalchemy import select

from .extensions import db
from .models import Member, Night, Period, PokerTable, Result
from .scoring import points_for
from .util import parse_date

MIN_TABLE_SIZE = 2


class NightError(Exception):
    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = errors


@dataclass
class _Seat:
    member: Member
    wipes: int


def _parse(payload: dict, night: Night | None) -> tuple:
    errors: list[str] = []

    d = parse_date(payload.get("date"))
    if d is None:
        errors.append("Ogiltigt datum.")

    period = db.session.get(Period, payload.get("period_id") or 0)
    if period is None:
        errors.append("Välj ett LP.")

    if d is not None:
        clash = db.session.scalar(select(Night).where(Night.date == d))
        if clash is not None and clash is not night:
            errors.append(f"Det finns redan en kväll {d.isoformat()}. Redigera den istället.")

    raw_tables = payload.get("tables")
    if not isinstance(raw_tables, list) or not raw_tables:
        errors.append("Lägg till minst ett bord.")
        raw_tables = []

    tables: list[list[_Seat]] = []
    seen: dict[int, int] = {}  # member_id -> table number
    for t_no, raw_seats in enumerate(raw_tables, start=1):
        if not isinstance(raw_seats, list) or len(raw_seats) < MIN_TABLE_SIZE:
            errors.append(f"Bord {t_no}: minst {MIN_TABLE_SIZE} spelare.")
            continue
        seats = []
        for raw in raw_seats:
            member = db.session.get(Member, raw.get("member_id") or 0) if isinstance(raw, dict) else None
            if member is None:
                errors.append(f"Bord {t_no}: okänd medlem.")
                continue
            try:
                wipes = int(raw.get("wipes") or 0)
            except (TypeError, ValueError):
                wipes = -1
            if not 0 <= wipes < len(raw_seats):
                errors.append(f"Bord {t_no}: ogiltigt antal wipes för {member.name}.")
            if member.id in seen:
                where = "vid samma bord" if seen[member.id] == t_no else f"även vid bord {seen[member.id]}"
                errors.append(f"{member.name} är med {where}.")
            seen[member.id] = t_no
            if d is not None and not member.is_active(d):
                errors.append(f"{member.name} har inget aktivt medlemskap {d.isoformat()}.")
            seats.append(_Seat(member, wipes))
        tables.append(seats)

    if errors:
        raise NightError(errors)
    note = (payload.get("note") or "").strip()[:200] or None
    return d, period, note, tables


def _fill(night: Night, tables: list[list[_Seat]]) -> None:
    night.tables.clear()
    db.session.flush()  # delete old rows before re-inserting under the same unique keys
    for t_no, seats in enumerate(tables, start=1):
        table = PokerTable(table_no=t_no)
        size = len(seats)
        for placement, seat in enumerate(seats, start=1):
            table.results.append(
                Result(
                    member_id=seat.member.id,
                    placement=placement,
                    wipes=seat.wipes,
                    points=points_for(placement, size, seat.wipes),
                )
            )
        night.tables.append(table)


def save_night(payload: dict, night: Night | None = None) -> Night:
    """Validate `payload` and create (night=None) or replace `night`. Raises NightError."""
    d, period, note, tables = _parse(payload, night)
    if night is None:
        night = Night(date=d, period=period, note=note)
        db.session.add(night)
    else:
        night.date, night.period, night.note = d, period, note
    _fill(night, tables)
    return night


def recalc_points(period: Period | None = None) -> int:
    """Re-apply the current `points_for` to stored results. Returns how many changed."""
    q = select(Result).join(PokerTable).join(Night)
    if period is not None:
        q = q.where(Night.period_id == period.id)
    changed = 0
    for r in db.session.scalars(q):
        new = points_for(r.placement, len(r.table.results), r.wipes)
        if new != r.points:
            r.points = new
            changed += 1
    return changed


def period_for_date(d) -> Period | None:
    return db.session.scalar(select(Period).where(Period.starts_on <= d, Period.ends_on >= d))

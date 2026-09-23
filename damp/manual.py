"""Points without placements: parsing pasted totals, matching members, importing.

Input is what you get when copying two columns from a spreadsheet, one player per line:
    Liam<TAB>14,5
    Eve 45
The last field is the points (decimal comma or point); everything before it is the name.
"""

import random
import re
from datetime import date, timedelta

from sqlalchemy import select

from .extensions import db
from .models import AdminUser, ManualPoints, Member, Period

_LP_LABEL = re.compile(r"^\s*LP\s*([1-4])\s+(\d{2})\s*/\s*(\d{2})\s*$", re.IGNORECASE)


class PointsImportError(ValueError):
    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = errors


def parse_points(value: str) -> float:
    """'14,5' / '14.5' / '−2' -> float. Raises ValueError."""
    return float(value.strip().replace(",", ".").replace("−", "-"))


def parse_totals(text: str) -> list[tuple[str, float]]:
    rows: list[tuple[str, float]] = []
    errors: list[str] = []
    seen: set[str] = set()
    for n, line in enumerate(text.splitlines(), start=1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.rsplit(None, 1)
        if len(parts) != 2:
            errors.append(f"Rad {n}: förväntade 'namn poäng', fick '{line}'.")
            continue
        name, raw = " ".join(parts[0].split()), parts[1]
        try:
            points = parse_points(raw)
        except ValueError:
            errors.append(f"Rad {n}: ogiltiga poäng '{raw}'.")
            continue
        if name.casefold() in seen:
            errors.append(f"Rad {n}: {name} finns redan i listan.")
        seen.add(name.casefold())
        rows.append((name, points))
    if errors:
        raise PointsImportError(errors)
    return rows


def find_period(spec: str) -> Period | None:
    """'LP1 26/27' or a period id."""
    spec = spec.strip()
    if spec.isdigit():
        return db.session.get(Period, int(spec))
    m = _LP_LABEL.match(spec)
    if not m:
        return None
    return db.session.scalar(select(Period).where(Period.lp == int(m[1]), Period.start_year == 2000 + int(m[2])))


def _keys(m: Member) -> set[str]:
    return {v.casefold() for v in (m.name, m.display_name, m.ltu_id) if v}


def find_members(name: str, members: list[Member]) -> list[Member]:
    """Exact (case-insensitive) match on name, display name or LTU-id."""
    key = name.casefold()
    return [m for m in members if key in _keys(m)]


def tuesdays(start: date, end: date) -> list[date]:
    d = start + timedelta(days=(1 - start.weekday()) % 7)
    out = []
    while d <= end:
        out.append(d)
        d += timedelta(days=7)
    return out


def spread(total: float, dates: list[date], rng: random.Random) -> list[tuple[date, float]]:
    """Fake a per-night history for a known total.

    Picks a random 50–90 % of `dates` as nights played and splits the total over
    them with skewed random weights (mostly small nights, the odd big one, like
    real placement points). Parts are whole points (half points if the total has
    a half), every night played gets at least one, and they sum exactly to `total`.
    """
    unit = 1.0 if float(total).is_integer() else 0.5
    units = round(total / unit)
    if units <= 0 or not dates:
        raise PointsImportError([f"Kan inte fördela {total} poäng över {len(dates)} kvällar."])
    k = max(1, min(len(dates), units, round(len(dates) * rng.uniform(0.5, 0.9))))
    played = sorted(rng.sample(dates, k))
    weights = [rng.expovariate(1.0) + 0.2 for _ in played]
    share = [(units - k) * w / sum(weights) for w in weights]
    parts = [1 + int(s) for s in share]
    by_remainder = sorted(range(k), key=lambda i: share[i] - int(share[i]), reverse=True)
    for i in by_remainder[: units - sum(parts)]:
        parts[i] += 1
    return [(d, p * unit) for d, p in zip(played, parts)]


def import_totals(
    period: Period,
    rows: list[tuple[str, float]],
    *,
    on: date | None = None,
    spread_dates: list[date] | None = None,
    rng: random.Random | None = None,
    note: str | None = None,
    admin: AdminUser | None = None,
) -> dict:
    """Add ManualPoints for each (name, total): all on `on`, or spread over `spread_dates`.

    Names that match no member become new members (no join date, no payment).
    Raises PointsImportError without changing anything if a row can't be imported.
    """
    if (on is None) == (spread_dates is None):
        raise ValueError("Give exactly one of on / spread_dates.")
    errors = []
    if on is not None and not period.contains(on):
        errors.append(f"{on.isoformat()} ligger utanför {period.label} ({period.starts_on}–{period.ends_on}).")

    members = list(db.session.scalars(select(Member)))
    targets: list[tuple[Member | str, float]] = []
    for name, total in rows:
        hits = find_members(name, members)
        if len(hits) > 1:
            errors.append(f"'{name}' matchar flera medlemmar: " + ", ".join(m.name for m in hits) + ".")
        targets.append((hits[0] if len(hits) == 1 else name, total))
    plans = []
    for target, total in targets:
        try:
            plans.append((target, [(on, total)] if on else spread(total, spread_dates, rng or random.Random())))
        except PointsImportError as e:
            errors.extend(f"{target if isinstance(target, str) else target.name}: {msg}" for msg in e.errors)
    if errors:
        raise PointsImportError(errors)

    created, entries = [], 0
    for target, parts in plans:
        if isinstance(target, str):
            target = Member(name=target)
            db.session.add(target)
            created.append(target.name)
        for d, points in parts:
            db.session.add(ManualPoints(period=period, member=target, date=d, points=points, note=note, created_by=admin))
            entries += 1
    return {"created": created, "matched": len(plans) - len(created), "entries": entries}

"""Points without placements: parsing pasted totals, matching members, importing.

Input is what you get when copying two columns from a spreadsheet, one player per line:
    Liam<TAB>14,5
    Eve 45
The last field is the points (decimal comma or point); everything before it is the name.

Used by the import-points CLI command (the admin only edits one entry at a time).
"""

import random
import re
from datetime import date, timedelta

from .store import Period, Store

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


def find_period(spec: str, store: Store) -> Period | None:
    """'LP1 26/27' or its slug 'lp1-26-27'."""
    spec = spec.strip()
    m = _LP_LABEL.match(spec)
    if m:
        return next((p for p in store.periods if p.lp == int(m[1]) and p.start_year == 2000 + int(m[2])), None)
    return store.period(spec.lower())


def member_name(m: dict) -> str:
    return " ".join(v for v in (m.get("first_name"), m.get("last_name")) if v)


def find_members(name: str, members: list[dict]) -> list[dict]:
    """members.json entries that `name` refers to (case-insensitive): full name, display
    name or LTU-id; failing those, the first name if exactly one member has it."""
    key = " ".join(name.split()).casefold()
    exact = [m for m in members if key in {v.casefold() for v in (member_name(m), m.get("display_name"), m.get("ltu_id")) if v}]
    if exact:
        return exact
    firsts = [m for m in members if (m.get("first_name") or "").casefold() == key]
    return firsts if len(firsts) == 1 else []


def tuesdays(start: date, end: date) -> list[date]:
    d = start + timedelta(days=(1 - start.weekday()) % 7)
    out = []
    while d <= end:
        out.append(d)
        d += timedelta(days=7)
    return out


def spread(total: float, dates: list[date], rng: random.Random) -> list[tuple[date, float]]:
    """Fake a per-date history for a known total.

    Picks a random 50–90 % of `dates` as days played and splits the total over
    them with skewed random weights (mostly small days, the odd big one, like
    real placement points). Parts are whole points (half points if the total has
    a half), every day played gets at least one, and they sum exactly to `total`.
    """
    unit = 1.0 if float(total).is_integer() else 0.5
    units = round(total / unit)
    if units <= 0 or not dates:
        raise PointsImportError([f"Kan inte fördela {total} poäng över {len(dates)} tisdagar."])
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
    members: list[dict],
    manual: list[dict],
    period: Period,
    rows: list[tuple[str, float]],
    *,
    on: date | None = None,
    spread_dates: list[date] | None = None,
    rng: random.Random | None = None,
    note: str | None = None,
) -> dict:
    """Append manual points for each (name, total) to `manual`: all on `on`, or spread over `spread_dates`.

    `members` / `manual` are the lists from members.json / manual-points.json and are
    changed in place. Names that match no member are added to `members` (first word as
    first name, the rest as last name). Raises PointsImportError, changing nothing, if a
    row can't be imported.
    """
    if (on is None) == (spread_dates is None):
        raise ValueError("Give exactly one of on / spread_dates.")
    errors = []
    if on is not None and not period.contains(on):
        errors.append(f"{on.isoformat()} ligger utanför {period.label} ({period.starts_on}–{period.ends_on}).")

    targets: list[tuple[dict | str, float]] = []
    for name, total in rows:
        hits = find_members(name, members)
        if len(hits) > 1:
            errors.append(f"'{name}' matchar flera medlemmar: " + ", ".join(member_name(m) for m in hits) + ".")
        targets.append((hits[0] if len(hits) == 1 else name, total))
    plans = []
    for target, total in targets:
        try:
            plans.append((target, [(on, total)] if on else spread(total, spread_dates, rng or random.Random())))
        except PointsImportError as e:
            errors.extend(f"{target if isinstance(target, str) else member_name(target)}: {msg}" for msg in e.errors)
    if errors:
        raise PointsImportError(errors)

    created, entries = [], 0
    next_id = max((m["id"] for m in members), default=0) + 1
    for target, parts in plans:
        if isinstance(target, str):
            first, _, last = target.partition(" ")
            target = {"id": next_id, "first_name": first, **({"last_name": last} if last else {})}
            next_id += 1
            members.append(target)
            created.append(member_name(target))
        for d, points in parts:
            entry = {"date": d.isoformat(), "member": target["id"], "points": points}
            if note:
                entry["note"] = note
            manual.append(entry)
            entries += 1
    manual.sort(key=lambda e: e["date"])
    return {"created": created, "matched": len(plans) - len(created), "entries": entries}

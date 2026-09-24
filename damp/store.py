"""The league data: JSON files in data/, loaded and validated into plain objects.

Layout (paths relative to the data dir):
    members.json              [{"id": 1, "first_name": "Harald", "last_name": "Malmström",
                                "ltu_id": "ahaamo-5", "joined_on": "2025-10-21", "display_name": "Hacke"}]
                              last_name, ltu_id, joined_on and display_name are optional.
    periods.json              [{"start_year": 2026, "lp": 1, "starts_on": "2026-08-31", "ends_on": "2026-11-01"}]
    tables/<date>-<n>.json    one poker table, e.g. tables/2026-09-22-2.json = the 2nd table that day:
                              {"note": "…", "players": [{"member": 1, "wipes": 0, "points": 8}, …]}
                              players in finishing order (first = winner)
    manual-points.json        [{"date": "2026-09-22", "member": 1, "points": 9, "note": "…"}]
    news.json                 [{"id": 1, "title": "…", "published_at": "2026-08-30T12:00", "body": "markdown"}]
    history/<YYYY-MM>.json    the change log (damp/history.py); not loaded here

Tables and manual points belong to the LP whose dates contain them. Points are
stored when a table is saved (see scoring.py); loading never recomputes them.

The admin (static JS + Cloudflare function, or the local dev API) writes these
files; the build loads them with `load()` and refuses to publish invalid data.
"""

import json
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

MIN_TABLE_SIZE = 2
MAX_FIRST_NAME = 60
MAX_LAST_NAME = 80
MAX_DISPLAY_NAME = 40
MAX_NOTE = 200

# Every file the admin may write. Kept in sync with DATA_PATH in functions/admin/api/[[path]].js.
DATA_PATH = re.compile(r"^(members|periods|manual-points|news)\.json$|^tables/\d{4}-\d{2}-\d{2}-[1-9]\d*\.json$")
TABLE_FILE = re.compile(r"^tables/(\d{4}-\d{2}-\d{2})-([1-9]\d*)\.json$")


class DataError(Exception):
    def __init__(self, errors: list[str]):
        super().__init__("\n".join(errors))
        self.errors = errors


# ---------- model ----------


@dataclass(eq=False)
class Member:
    id: int
    first_name: str
    last_name: str | None = None
    display_name: str | None = None
    ltu_id: str | None = None
    joined_on: date | None = None
    # What the public site shows: the display name, else the first name (made unique, see
    # assign_public_names). Set when the Store is built.
    public_name: str = ""

    @property
    def name(self) -> str:
        """'Harald Malmström': for the admin and messages."""
        return f"{self.first_name} {self.last_name}" if self.last_name else self.first_name

    @property
    def full_name(self) -> str:
        """'Oleksandra "Sasha" Pozniakova': shown when someone opens a player's stats."""
        nick = f' "{self.display_name}"' if self.display_name else ""
        return f"{self.first_name}{nick} {self.last_name}" if self.last_name else f"{self.first_name}{nick}"


def assign_public_names(members: list[Member]) -> None:
    """Display name, else first name; two members who'd show the same first name get
    their last name's initial ("Nils S.", "Nils K."), or the whole last name if that clashes too."""
    base = {m.id: m.display_name or m.first_name for m in members}
    taken = Counter(v.casefold() for v in base.values())
    for m in members:
        name = base[m.id]
        if taken[name.casefold()] > 1 and not m.display_name and m.last_name:
            name = f"{m.first_name} {m.last_name[0]}."
        m.public_name = name
    taken = Counter(m.public_name.casefold() for m in members)
    for m in members:
        if taken[m.public_name.casefold()] > 1 and not m.display_name and m.last_name:
            m.public_name = m.name


@dataclass(eq=False)
class Period:
    """A läsperiod, e.g. LP1 26/27 (start_year=2026, lp=1)."""

    start_year: int
    lp: int
    starts_on: date
    ends_on: date
    tables: list["PokerTable"] = field(default_factory=list)
    manual_points: list["ManualPoints"] = field(default_factory=list)

    @property
    def id(self) -> str:
        """URL slug, e.g. 'lp1-26-27'."""
        return f"lp{self.lp}-{self.start_year % 100:02d}-{(self.start_year + 1) % 100:02d}"

    @property
    def school_year(self) -> str:
        return f"{self.start_year % 100:02d}/{(self.start_year + 1) % 100:02d}"

    @property
    def label(self) -> str:
        return f"LP{self.lp} {self.school_year}"

    @property
    def point_dates(self) -> set[date]:
        """Dates with any points in this LP: tables plus manual points."""
        return {t.date for t in self.tables} | {m.date for m in self.manual_points}

    def contains(self, d: date) -> bool:
        return self.starts_on <= d <= self.ends_on


@dataclass(eq=False)
class Result:
    member: Member
    placement: int
    wipes: int
    points: float

    @property
    def member_id(self) -> int:
        return self.member.id


@dataclass(eq=False)
class PokerTable:
    date: date
    number: int  # 1, 2, … within its date
    results: list[Result]
    note: str | None = None
    period: Period | None = None

    @property
    def id(self) -> str:
        """'2026-09-22-2', also the file name."""
        return f"{self.date.isoformat()}-{self.number}"


@dataclass(eq=False)
class ManualPoints:
    """Points on a date without a placement, e.g. LP totals imported from a spreadsheet.

    Counted in standings and the chart, but not as tables played, wins, average
    placement or wipes.
    """

    date: date
    member: Member
    points: float
    note: str | None = None
    period: Period | None = None

    @property
    def member_id(self) -> int:
        return self.member.id


@dataclass(eq=False)
class NewsPost:
    id: int
    title: str
    body_md: str
    published_at: datetime


@dataclass
class Store:
    members: dict[int, Member]
    periods: list[Period]  # newest first
    tables: list[PokerTable]  # oldest first
    manual_points: list[ManualPoints]
    news: list[NewsPost]  # newest first

    def period(self, slug: str) -> Period | None:
        return next((p for p in self.periods if p.id == slug), None)

    def period_for(self, d: date) -> Period | None:
        return next((p for p in self.periods if p.contains(d)), None)


# ---------- reading / writing files ----------


def read_files(data_dir: Path) -> dict[str, Any]:
    """Parsed JSON of every data file, keyed by path relative to `data_dir` (history/ excluded)."""
    data_dir = Path(data_dir)
    files: dict[str, Any] = {}
    errors: list[str] = []
    for path in sorted([*data_dir.glob("*.json"), *data_dir.glob("tables/*.json")]):
        rel = path.relative_to(data_dir).as_posix()
        if not DATA_PATH.match(rel):
            errors.append(f"{rel}: okänd fil i data/ (fel namn?).")
            continue
        try:
            files[rel] = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, UnicodeDecodeError) as e:
            errors.append(f"{rel}: ogiltig JSON ({e}).")
    if errors:
        raise DataError(errors)
    return files


def clean_numbers(obj):
    """24.0 -> 24 everywhere, so files look the same whoever wrote them (Python or JS)."""
    if isinstance(obj, float) and obj.is_integer():
        return int(obj)
    if isinstance(obj, list):
        return [clean_numbers(v) for v in obj]
    if isinstance(obj, dict):
        return {k: clean_numbers(v) for k, v in obj.items()}
    return obj


def dumps(obj) -> str:
    """The on-disk format: 2-space indent, UTF-8, trailing newline. Matches JSON.stringify(obj, null, 2)."""
    return json.dumps(clean_numbers(obj), indent=2, ensure_ascii=False) + "\n"


def write_json(path: Path, obj) -> None:
    """Write via a temporary file, so a reader (the dev server) never sees a half-written file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(dumps(obj), encoding="utf-8")
    tmp.replace(path)


def load(data_dir: Path) -> Store:
    return from_files(read_files(data_dir))


# ---------- validation ----------


class _Bad(Exception):
    pass


def _is_int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _is_num(v) -> bool:
    return (isinstance(v, (int, float)) and not isinstance(v, bool)) and v == v  # not NaN


def _str(raw: dict, key: str, *, required: bool = True, max_len: int | None = None) -> str | None:
    v = raw.get(key)
    if v is None or (isinstance(v, str) and not v.strip()):
        if required:
            raise _Bad(f"'{key}' saknas.")
        return None
    if not isinstance(v, str):
        raise _Bad(f"'{key}' ska vara text.")
    v = " ".join(v.split())
    if max_len and len(v) > max_len:
        raise _Bad(f"'{key}' är längre än {max_len} tecken.")
    return v


def _date(raw: dict, key: str, *, required: bool = True) -> date | None:
    v = raw.get(key)
    if v is None and not required:
        return None
    try:
        return date.fromisoformat(v)
    except (TypeError, ValueError):
        raise _Bad(f"'{key}' ska vara ett datum ÅÅÅÅ-MM-DD, inte {v!r}.")


def _list(files: dict, path: str, errors: list[str]) -> list:
    v = files.get(path, [])
    if not isinstance(v, list):
        errors.append(f"{path}: ska vara en lista.")
        return []
    return v


def _members(files: dict, errors: list[str]) -> dict[int, Member]:
    members: dict[int, Member] = {}
    names: dict[str, str] = {}
    ltu_ids: dict[str, str] = {}
    display_names: dict[str, str] = {}
    for i, raw in enumerate(_list(files, "members.json", errors), start=1):
        where = f"members.json, post {i}"
        try:
            if not isinstance(raw, dict):
                raise _Bad("ska vara ett objekt.")
            mid = raw.get("id")
            if not _is_int(mid) or mid < 1:
                raise _Bad(f"ogiltigt id {mid!r}.")
            if mid in members:
                raise _Bad(f"id {mid} finns redan ({members[mid].name}).")
            m = Member(
                id=mid,
                first_name=_str(raw, "first_name", max_len=MAX_FIRST_NAME),
                last_name=_str(raw, "last_name", required=False, max_len=MAX_LAST_NAME),
                display_name=_str(raw, "display_name", required=False, max_len=MAX_DISPLAY_NAME),
                ltu_id=_str(raw, "ltu_id", required=False, max_len=32),
                joined_on=_date(raw, "joined_on", required=False),
            )
            if m.name.casefold() in names:
                raise _Bad(f"{m.name} finns redan.")
            if m.ltu_id and m.ltu_id.casefold() in ltu_ids:
                raise _Bad(f"LTU-id {m.ltu_id} används redan av {ltu_ids[m.ltu_id.casefold()]}.")
            if m.display_name and m.display_name.casefold() in display_names:
                raise _Bad(f"visningsnamnet {m.display_name} används redan av {display_names[m.display_name.casefold()]}.")
        except _Bad as e:
            errors.append(f"{where}: {e}")
            continue
        members[mid] = m
        names[m.name.casefold()] = m.name
        if m.ltu_id:
            ltu_ids[m.ltu_id.casefold()] = m.name
        if m.display_name:
            display_names[m.display_name.casefold()] = m.name
    assign_public_names(list(members.values()))
    return members


def _periods(files: dict, errors: list[str]) -> list[Period]:
    periods: list[Period] = []
    seen_labels: set[str] = set()
    for i, raw in enumerate(_list(files, "periods.json", errors), start=1):
        where = f"periods.json, post {i}"
        try:
            if not isinstance(raw, dict):
                raise _Bad("ska vara ett objekt.")
            year, lp = raw.get("start_year"), raw.get("lp")
            if not _is_int(year) or not 2000 <= year <= 2100:
                raise _Bad(f"ogiltigt start_year {year!r}.")
            if not _is_int(lp) or not 1 <= lp <= 4:
                raise _Bad(f"lp ska vara 1–4, inte {lp!r}.")
            p = Period(start_year=year, lp=lp, starts_on=_date(raw, "starts_on"), ends_on=_date(raw, "ends_on"))
            if p.starts_on > p.ends_on:
                raise _Bad(f"{p.label} slutar före den börjar.")
            if p.label in seen_labels:
                raise _Bad(f"{p.label} finns redan.")
        except _Bad as e:
            errors.append(f"{where}: {e}")
            continue
        seen_labels.add(p.label)
        periods.append(p)
    periods.sort(key=lambda p: p.starts_on)
    for a, b in zip(periods, periods[1:]):
        if b.starts_on <= a.ends_on:
            errors.append(f"periods.json: {a.label} och {b.label} överlappar.")
    periods.reverse()
    return periods


def from_files(files: dict[str, Any]) -> Store:
    """Build a Store from parsed data files. Raises DataError listing every problem found."""
    errors: list[str] = []
    members = _members(files, errors)
    periods = _periods(files, errors)

    def member(v) -> Member:
        if not _is_int(v) or v not in members:
            raise _Bad(f"okänd medlem {v!r}.")
        return members[v]

    def period_for(d: date) -> Period | None:
        return next((p for p in periods if p.contains(d)), None)

    # tables
    tables: list[PokerTable] = []
    for path in sorted(p for p in files if p.startswith("tables/")):
        raw = files[path]
        try:
            m = TABLE_FILE.match(path)
            try:
                d = date.fromisoformat(m[1]) if m else None
            except ValueError:
                d = None
            if d is None:
                raise _Bad("filnamnet ska vara tables/ÅÅÅÅ-MM-DD-N.json.")
            if not isinstance(raw, dict):
                raise _Bad("ska vara ett objekt.")
            note = _str(raw, "note", required=False, max_len=MAX_NOTE)
            seats = raw.get("players")
            if not isinstance(seats, list) or len(seats) < MIN_TABLE_SIZE:
                raise _Bad(f"minst {MIN_TABLE_SIZE} spelare.")
            results: list[Result] = []
            seen: set[int] = set()
            problems: list[str] = []
            for placement, seat in enumerate(seats, start=1):
                try:
                    if not isinstance(seat, dict):
                        raise _Bad("ska vara ett objekt.")
                    mem = member(seat.get("member"))
                    wipes = seat.get("wipes", 0)
                    if not _is_int(wipes) or not 0 <= wipes < len(seats):
                        raise _Bad(f"ogiltigt antal wipes {wipes!r} för {mem.name}.")
                    points = seat.get("points")
                    if not _is_num(points):
                        raise _Bad(f"poäng saknas för {mem.name}.")
                    if mem.id in seen:
                        raise _Bad(f"{mem.name} är med två gånger.")
                    seen.add(mem.id)
                    results.append(Result(member=mem, placement=placement, wipes=wipes, points=points))
                except _Bad as e:
                    problems.append(f"plats {placement}: {e}")
            period = period_for(d)
            if period is None:
                problems.append(f"{d.isoformat()} ligger inte i något LP.")
            if problems:
                raise _Bad(" ".join(problems))
        except _Bad as e:
            errors.append(f"{path}: {e}")
            continue
        table = PokerTable(date=d, number=int(m[2]), results=results, note=note, period=period)
        period.tables.append(table)
        tables.append(table)

    # manual points
    manual: list[ManualPoints] = []
    for i, raw in enumerate(_list(files, "manual-points.json", errors), start=1):
        where = f"manual-points.json, post {i}"
        try:
            if not isinstance(raw, dict):
                raise _Bad("ska vara ett objekt.")
            d = _date(raw, "date")
            mem = member(raw.get("member"))
            points = raw.get("points")
            if not _is_num(points):
                raise _Bad(f"ogiltiga poäng {points!r}.")
            note = _str(raw, "note", required=False, max_len=MAX_NOTE)
            period = period_for(d)
            if period is None:
                raise _Bad(f"{d.isoformat()} ligger inte i något LP.")
        except _Bad as e:
            errors.append(f"{where}: {e}")
            continue
        mp = ManualPoints(date=d, member=mem, points=points, note=note, period=period)
        period.manual_points.append(mp)
        manual.append(mp)

    # news
    news: list[NewsPost] = []
    news_ids: set[int] = set()
    for i, raw in enumerate(_list(files, "news.json", errors), start=1):
        where = f"news.json, post {i}"
        try:
            if not isinstance(raw, dict):
                raise _Bad("ska vara ett objekt.")
            nid = raw.get("id")
            if not _is_int(nid) or nid < 1 or nid in news_ids:
                raise _Bad(f"ogiltigt eller upprepat id {nid!r}.")
            title = _str(raw, "title", max_len=200)
            body = raw.get("body", "")
            if not isinstance(body, str):
                raise _Bad("'body' ska vara text.")
            try:
                published = datetime.fromisoformat(raw.get("published_at"))
            except (TypeError, ValueError):
                raise _Bad(f"ogiltigt published_at {raw.get('published_at')!r}.")
        except _Bad as e:
            errors.append(f"{where}: {e}")
            continue
        news_ids.add(nid)
        news.append(NewsPost(id=nid, title=title, body_md=body, published_at=published.replace(tzinfo=None)))

    if errors:
        raise DataError(errors)

    tables.sort(key=lambda t: (t.date, t.number))
    for p in periods:
        p.tables.sort(key=lambda t: (t.date, t.number))
        p.manual_points.sort(key=lambda m: m.date)
    news.sort(key=lambda n: (n.published_at, n.id), reverse=True)
    return Store(members=members, periods=periods, tables=tables, manual_points=manual, news=news)

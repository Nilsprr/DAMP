"""Data CLI. Run with: uv run flask --app damp <command>

The commands edit the JSON files in data/ and log what they did in the history
(damp/history.py), like the admin does. Commit the result like any other change.
"""

import random
from datetime import date

import click

from . import history
from .manual import PointsImportError, find_members, find_period, import_totals, member_name, parse_totals, tuesdays
from .scoring import points_for
from .store import TABLE_FILE, DataError, from_files, load, read_files, write_json
from .util import fmt_points, parse_date, today


def recalc_table(table: dict) -> int:
    """Re-apply points_for to one table file's content (in place). Returns how many players changed."""
    seats = table["players"]
    changed = 0
    for placement, seat in enumerate(seats, start=1):
        new = points_for(placement, len(seats), seat.get("wipes", 0))
        if new != seat.get("points"):
            seat["points"] = new
            changed += 1
    return changed


MEMBER_KEYS = ["id", "first_name", "last_name", "display_name", "ltu_id", "joined_on"]


class MergeError(ValueError):
    pass


def merge_member_files(files: dict, source: dict, target: dict, display_name: str | None) -> tuple[dict, list[str], list[str]]:
    """Move `source`'s table results and manual points to `target` and drop `source`.

    `files` are the parsed data files (not changed). Returns (changed files, dates moved,
    history details). The target keeps its own names; `display_name` replaces its display
    name, and fields it lacks (last name, LTU-id, joined) are taken from the source.
    """
    changed: dict = {}
    dates: list[str] = []
    clashes, tables = [], 0
    for path, table in files.items():
        m = TABLE_FILE.match(path)
        if not m or not any(s["member"] == source["id"] for s in table["players"]):
            continue
        if any(s["member"] == target["id"] for s in table["players"]):
            clashes.append(f"{m[1]}, bord {m[2]}")
            continue
        changed[path] = {**table, "players": [{**s, "member": target["id"]} if s["member"] == source["id"] else s for s in table["players"]]}
        dates.append(m[1])
        tables += 1
    if clashes:
        raise MergeError("Båda är med vid samma bord: " + ", ".join(clashes))
    manual = [dict(e) for e in files.get("manual-points.json", [])]
    points = 0
    for e in manual:
        if e["member"] == source["id"]:
            e["member"] = target["id"]
            dates.append(e["date"])
            points += 1
    if points:
        changed["manual-points.json"] = manual
    merged = {**target, "display_name": display_name}
    for key in ("last_name", "ltu_id", "joined_on"):
        merged[key] = merged.get(key) or source.get(key)
    merged = {k: merged[k] for k in MEMBER_KEYS if merged.get(k)}
    changed["members.json"] = [merged if m["id"] == target["id"] else m for m in files["members.json"] if m["id"] != source["id"]]
    details = [f"{tables} bord och {points} manuella poäng flyttades från {member_name(source)} till {member_name(target)}."]
    labels = {"last_name": "Efternamn", "display_name": "Visningsnamn", "ltu_id": "LTU-id", "joined_on": "Medlem sedan"}
    details += [f"{label}: {target.get(k) or '–'} → {merged.get(k) or '–'}" for k, label in labels.items() if target.get(k) != merged.get(k)]
    return changed, dates, details


def register_cli(app):
    def data_dir():
        return app.config["DATA_DIR"]

    def store_or_fail():
        try:
            return load(data_dir())
        except DataError as e:
            raise click.ClickException("Datan i data/ är ogiltig:\n" + "\n".join(e.errors))

    def log(message, lps=(), details=()):
        history.append(data_dir(), history.make_event(message, list(lps), list(details), by=history.local_author()))

    @app.cli.command("recalc-points")
    @click.option("--lp", "lp_spec", help='Bara ett LP, t.ex. "LP1 26/27" (standard: alla).')
    def recalc_points_cmd(lp_spec):
        """Re-apply scoring.points_for to the stored points in data/tables/."""
        store = store_or_fail()
        period = find_period(lp_spec, store) if lp_spec else None
        if lp_spec and period is None:
            raise click.ClickException(f"Hittar inget LP '{lp_spec}'.")
        files = read_files(data_dir())
        changed, touched = 0, []
        for path, table in files.items():
            m = TABLE_FILE.match(path)
            if not m or (period and not period.contains(date.fromisoformat(m[1]))):
                continue
            n = recalc_table(table)
            if n:
                write_json(data_dir() / path, table)
                changed += n
                touched.append((m[1], int(m[2])))
        if changed:
            lps = {store.period_for(date.fromisoformat(d)).id for d, _ in touched}
            where = period.label if period else "alla LP"
            log(f"Räknade om poäng i {where}: {changed} resultat på {len(touched)} bord ändrades",
                lps, [f"{d}, bord {n}" for d, n in sorted(touched)])
        click.echo(f"{changed} resultat ändrades på {len(touched)} bord.")

    @app.cli.command("merge-members")
    @click.argument("source")
    @click.argument("target")
    @click.option("--display-name", "display", help="Visningsnamn efteråt (standard: SOURCE:s smeknamn, t.ex. Slalle).")
    def merge_members_cmd(source, target, display):
        """Move SOURCE's tables and manual points to TARGET and remove SOURCE.

        For a nickname from the old spreadsheet that turns out to be a listed member:
        merge-members Slalle "Nils Salomonsson" gives Nils "Slalle" Salomonsson.
        """
        store = store_or_fail()
        files = read_files(data_dir())
        members = files.get("members.json", [])

        def one(name, candidates):
            hits = find_members(name, candidates)
            if len(hits) != 1:
                raise click.ClickException(f"'{name}' matchar {len(hits)} medlemmar, inte en.")
            return hits[0]

        src = one(source, members)
        dst = one(target, [m for m in members if m["id"] != src["id"]])
        nickname = src.get("display_name") or (src["first_name"] if not src.get("last_name") else None)
        display = " ".join(display.split()) if display is not None else (nickname or dst.get("display_name"))
        try:
            changed, dates, details = merge_member_files(files, src, dst, display or None)
            from_files({**files, **changed})
        except MergeError as e:
            raise click.ClickException(str(e))
        except DataError as e:
            raise click.ClickException("Sammanslagningen skulle ge ogiltig data:\n" + "\n".join(e.errors))
        for path, content in changed.items():
            write_json(data_dir() / path, content)
        lps = {store.period_for(date.fromisoformat(d)).id for d in dates}
        message = f"Slog ihop {member_name(src)} med {member_name(dst)}"
        log(message, lps, details)
        click.echo(message + ". " + " ".join(details))

    @app.cli.command("import-points")
    @click.argument("file", type=click.File(encoding="utf-8"))
    @click.option("--lp", "lp_spec", required=True, help='LP, t.ex. "LP1 26/27".')
    @click.option("--date", "on", help="Lägg alla poäng på detta datum (YYYY-MM-DD).")
    @click.option("--spread", "do_spread", is_flag=True, help="Fiktiv kurva: fördela varje total slumpmässigt över LP:ets tisdagar.")
    @click.option("--seed", type=int, help="Slumpfrö för --spread (samma frö ger samma fördelning).")
    @click.option("--replace", is_flag=True, help="Ta bort LP:ets befintliga manuella poäng först.")
    def import_points_cmd(file, lp_spec, on, do_spread, seed, replace):
        """Import 'namn poäng' lines (e.g. pasted from a spreadsheet) as points without placements.

        Names that match no member are added as new members.
        """
        store = store_or_fail()
        period = find_period(lp_spec, store)
        if period is None:
            raise click.ClickException(f"Hittar inget LP '{lp_spec}'. Skapa det under Admin → LP först.")
        if bool(on) == do_spread:
            raise click.ClickException("Ange antingen --date eller --spread.")
        day = parse_date(on) if on else None
        if on and day is None:
            raise click.ClickException(f"Ogiltigt datum: {on}")

        files = read_files(data_dir())
        members = files.get("members.json", [])
        manual = files.get("manual-points.json", [])
        in_period = [e for e in manual if period.contains(date.fromisoformat(e["date"]))]
        if in_period and not replace:
            raise click.ClickException(f"{period.label} har redan {len(in_period)} manuella poäng. Kör med --replace för att ersätta dem.")
        if replace:
            manual = [e for e in manual if e not in in_period]
        try:
            rows = parse_totals(file.read())
            if do_spread:
                dates = tuesdays(period.starts_on, min(period.ends_on, today()))
                result = import_totals(
                    members, manual, period, rows, spread_dates=dates, rng=random.Random(seed),
                    note="Slumpmässigt fördelad del av en importerad total",
                )
            else:
                result = import_totals(members, manual, period, rows, on=day, note="Importerad total")
            from_files({**files, "members.json": members, "manual-points.json": manual})
        except PointsImportError as e:
            raise click.ClickException("\n".join(e.errors))
        except DataError as e:
            raise click.ClickException("Importen skulle ge ogiltig data:\n" + "\n".join(e.errors))
        write_json(data_dir() / "members.json", members)
        write_json(data_dir() / "manual-points.json", manual)
        total = sum(points for _, points in rows)
        summary = f"{len(rows)} spelare, {result['entries']} poster, totalt {fmt_points(total)} poäng"
        details = [f"{name}: {fmt_points(points)} p" for name, points in rows]
        if replace and in_period:
            details.insert(0, f"Ersatte {len(in_period)} tidigare manuella poäng.")
        if result["created"]:
            details.append("Nya medlemmar: " + ", ".join(result["created"]))
        log(f"Importerade totaler i {period.label} ({summary})", [period.id], details)
        click.echo(f"{period.label}: {summary}.")
        if result["created"]:
            click.echo(f"Nya medlemmar ({len(result['created'])}): " + ", ".join(result["created"]))

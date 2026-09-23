"""Admin CLI. Run with: uv run flask --app damp <command>"""

import json
import random

import click
from sqlalchemy import delete, select
from werkzeug.security import generate_password_hash

from .extensions import db
from .manual import PointsImportError, find_period, import_totals, parse_totals, tuesdays
from .models import AdminUser, AuditLog, ManualPoints, Period
from .nights import recalc_points
from .util import fmt_points, parse_date, today

MIN_PASSWORD = 12


def _prompt_password() -> str:
    while True:
        pw = click.prompt("Lösenord", hide_input=True, confirmation_prompt="Upprepa lösenord")
        if len(pw) >= MIN_PASSWORD:
            return pw
        click.echo(f"Minst {MIN_PASSWORD} tecken.")


def _admin(username: str) -> AdminUser:
    user = db.session.scalar(select(AdminUser).where(AdminUser.username == username.lower()))
    if user is None:
        raise click.ClickException(f"Ingen admin som heter {username}.")
    return user


def register_cli(app):
    @app.cli.command("create-admin")
    @click.argument("username")
    def create_admin(username):
        """Create an admin account. TOTP is set up at first login."""
        username = username.strip().lower()
        if db.session.scalar(select(AdminUser).where(AdminUser.username == username)):
            raise click.ClickException(f"{username} finns redan.")
        db.session.add(AdminUser(username=username, password_hash=generate_password_hash(_prompt_password())))
        db.session.commit()
        click.echo(f"Skapade {username}. Logga in på /admin/login och skanna QR-koden med en autentiseringsapp.")

    @app.cli.command("set-password")
    @click.argument("username")
    def set_password(username):
        """Change an admin's password."""
        user = _admin(username)
        user.password_hash = generate_password_hash(_prompt_password())
        db.session.commit()
        click.echo("Lösenordet är ändrat.")

    @app.cli.command("reset-totp")
    @click.argument("username")
    def reset_totp(username):
        """Remove an admin's TOTP secret (lost phone). They re-enrol at next login."""
        user = _admin(username)
        user.totp_secret = None
        user.last_totp_step = None
        db.session.commit()
        click.echo(f"TOTP för {user.username} är nollställd. Ny QR-kod visas vid nästa inloggning.")

    @app.cli.command("delete-admin")
    @click.argument("username")
    @click.confirmation_option(prompt="Radera kontot?")
    def delete_admin(username):
        db.session.delete(_admin(username))
        db.session.commit()
        click.echo("Raderat.")

    @app.cli.command("list-admins")
    def list_admins():
        for u in db.session.scalars(select(AdminUser).order_by(AdminUser.username)):
            totp = "TOTP ok" if u.totp_secret else "TOTP ej aktiverad"
            click.echo(f"{u.username:20} {totp:18} senast inloggad: {u.last_login_at or '-'}")

    @app.cli.command("recalc-points")
    @click.option("--lp", "period_id", type=int, help="Period id (default: all)")
    def recalc_points_cmd(period_id):
        """Re-apply scoring.points_for to stored results."""
        period = db.session.get(Period, period_id) if period_id else None
        if period_id and period is None:
            raise click.ClickException("Okänt LP-id.")
        changed = recalc_points(period)
        db.session.commit()
        click.echo(f"{changed} resultat ändrades.")

    @app.cli.command("import-points")
    @click.argument("file", type=click.File(encoding="utf-8"))
    @click.option("--lp", "lp_spec", required=True, help='LP, t.ex. "LP1 26/27" (eller dess id).')
    @click.option("--date", "on", help="Lägg alla poäng på detta datum (YYYY-MM-DD).")
    @click.option("--spread", "do_spread", is_flag=True, help="Fiktiv kurva: fördela varje total slumpmässigt över LP:ets tisdagar.")
    @click.option("--seed", type=int, help="Slumpfrö för --spread (samma frö ger samma fördelning).")
    @click.option("--replace", is_flag=True, help="Ta bort LP:ets befintliga manuella poäng först.")
    def import_points_cmd(file, lp_spec, on, do_spread, seed, replace):
        """Import 'namn poäng' lines (e.g. pasted from a spreadsheet) as points without placements.

        Names that match no member are created as new members without payments.
        """
        period = find_period(lp_spec)
        if period is None:
            raise click.ClickException(f"Hittar inget LP '{lp_spec}'. Skapa det under Admin → LP först.")
        if bool(on) == do_spread:
            raise click.ClickException("Ange antingen --date eller --spread.")
        day = parse_date(on) if on else None
        if on and day is None:
            raise click.ClickException(f"Ogiltigt datum: {on}")
        existing = len(period.manual_points)
        if existing and not replace:
            raise click.ClickException(f"{period.label} har redan {existing} manuella poäng. Kör med --replace för att ersätta dem.")
        try:
            rows = parse_totals(file.read())
            if replace:
                db.session.execute(delete(ManualPoints).where(ManualPoints.period_id == period.id))
            if do_spread:
                dates = tuesdays(period.starts_on, min(period.ends_on, today()))
                result = import_totals(
                    period, rows, spread_dates=dates, rng=random.Random(seed),
                    note="Slumpmässigt fördelad del av en importerad total",
                )
            else:
                result = import_totals(period, rows, on=day, note="Importerad total")
        except PointsImportError as e:
            db.session.rollback()
            raise click.ClickException("\n".join(e.errors))
        db.session.add(
            AuditLog(action="points_imported", detail=json.dumps(
                {"lp": period.label, "date": on, "spread": do_spread, "rows": len(rows), "replaced": existing if replace else 0},
                ensure_ascii=False,
            ))
        )
        db.session.commit()
        total = sum(points for _, points in rows)
        click.echo(f"{period.label}: {len(rows)} spelare, {result['entries']} poster, totalt {fmt_points(total)} poäng.")
        if result["created"]:
            click.echo(f"Nya medlemmar ({len(result['created'])}): " + ", ".join(result["created"]))
            click.echo("De har ingen registrerad betalning. Lägg in den under Admin → Medlemmar.")

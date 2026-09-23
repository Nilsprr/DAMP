"""Admin HTML pages: dashboard, nights, members, LPs, manual points, news, audit log."""

from datetime import date

from flask import abort, flash, g, redirect, render_template, request, url_for
from sqlalchemy import func, select

from ..extensions import db
from ..manual import find_members, parse_points
from ..models import AuditLog, ManualPoints, Member, MembershipPayment, NewsPost, Night, Period, Result, utcnow
from ..nights import period_for_date, recalc_points
from ..public import default_period
from ..util import fmt_points, latest_tuesday, parse_date, render_markdown, today
from . import audit, bp

# ---------- helpers ----------


def _get(model, obj_id):
    return db.session.get(model, obj_id) or abort(404)


def _int(value, default=None):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _periods_desc():
    return list(db.session.scalars(select(Period).order_by(Period.start_year.desc(), Period.lp.desc())))


def _member_json(m: Member, on) -> dict:
    st = m.status(on)
    return {
        "id": m.id,
        "name": m.name,
        "display_name": m.display_name,
        "ltu_id": m.ltu_id,
        "active": st.active,
        "status": st.key,
        "expires_on": st.expires_on.isoformat() if st.expires_on else None,
    }


# ---------- dashboard ----------


@bp.get("/")
def dashboard():
    t = today()
    members = db.session.scalars(select(Member)).all()
    statuses = [(m, m.status(t)) for m in members]
    expiring = sorted(
        [(m, s) for m, s in statuses if s.key == "soon"], key=lambda ms: ms[1].days_left
    )
    period = default_period(_periods_desc())
    recent = db.session.scalars(select(Night).order_by(Night.date.desc()).limit(5)).all()
    return render_template(
        "admin/dashboard.html",
        active_count=sum(1 for _, s in statuses if s.active),
        member_count=len(members),
        expiring=expiring,
        period=period,
        recent=recent,
    )


# ---------- nights ----------


@bp.get("/kvallar")
def nights():
    rows = db.session.scalars(select(Night).order_by(Night.date.desc())).all()
    return render_template("admin/nights.html", nights=rows)


def _editor_state(night: Night | None) -> dict:
    periods = _periods_desc()
    if night is None:
        d = latest_tuesday(today())
        p = period_for_date(d)
        tables, note, period_id = [[]], "", p.id if p else None
    else:
        d = night.date
        period_id, note = night.period_id, night.note or ""
        tables = [
            [
                _member_json(r.member, d) | {"member_id": r.member_id, "wipes": r.wipes}
                for r in t.results
            ]
            for t in night.tables
        ]
    return {
        "mode": "edit" if night else "new",
        "night_id": night.id if night else None,
        "date": d.isoformat(),
        "period_id": period_id,
        "note": note,
        "tables": tables,
        "periods": [
            {"id": p.id, "label": p.label, "starts_on": p.starts_on.isoformat(), "ends_on": p.ends_on.isoformat()}
            for p in periods
        ],
        "urls": {
            "members": url_for("admin.api_members"),
            "preview": url_for("admin.api_points_preview"),
            "save": url_for("admin.api_night_update", night_id=night.id) if night else url_for("admin.api_night_create"),
            "payment": url_for("admin.api_member_payment", member_id=0),
            "members_page": url_for("admin.members"),
        },
    }


@bp.get("/kvallar/ny")
def night_new():
    if not db.session.scalar(select(func.count(Period.id))):
        flash("Skapa ett LP först.", "warning")
        return redirect(url_for("admin.period_new"))
    return render_template("admin/night_editor.html", state=_editor_state(None), night=None)


@bp.get("/kvallar/<int:night_id>")
def night_view(night_id):
    return render_template("admin/night_view.html", night=_get(Night, night_id))


@bp.get("/kvallar/<int:night_id>/redigera")
def night_edit(night_id):
    night = _get(Night, night_id)
    return render_template("admin/night_editor.html", state=_editor_state(night), night=night)


@bp.post("/kvallar/<int:night_id>/radera")
def night_delete(night_id):
    night = _get(Night, night_id)
    audit("night_deleted", date=night.date, players=night.player_count)
    db.session.delete(night)
    db.session.commit()
    flash(f"Kvällen {night.date.isoformat()} är raderad.", "ok")
    return redirect(url_for("admin.nights"))


# ---------- members ----------

SORTS = {
    "utgang": "Dagar kvar",
    "namn": "Namn",
    "gick-med": "Gick med",
    "betalning": "Senaste betalning",
}
FILTERS = {"alla": "Alla", "aktiva": "Aktiva", "snart": "Går snart ut", "utgangna": "Utgångna"}


@bp.get("/medlemmar")
def members():
    t = today()
    sort = request.args.get("sort", "utgang")
    flt = request.args.get("filter", "alla")
    q = request.args.get("q", "").strip().casefold()
    rows = []
    for m in db.session.scalars(select(Member)):
        if q and not any(q in (v or "").casefold() for v in (m.name, m.display_name, m.ltu_id)):
            continue
        s = m.status(t)
        if flt == "aktiva" and not s.active:
            continue
        if flt == "snart" and s.key != "soon":
            continue
        if flt == "utgangna" and s.key not in ("expired", "never"):
            continue
        rows.append((m, s))

    far = 10**6
    keys = {
        "utgang": lambda ms: (ms[1].days_left if ms[1].days_left is not None else -far, ms[0].name.casefold()),
        "namn": lambda ms: ms[0].name.casefold(),
        # newest first; unknown dates last
        "gick-med": lambda ms: ms[0].joined_on or date.min,
        "betalning": lambda ms: ms[1].last_paid_on or date.min,
    }
    rows.sort(key=keys.get(sort, keys["utgang"]), reverse=sort in ("gick-med", "betalning"))
    return render_template(
        "admin/members.html", rows=rows, sort=sort, flt=flt, q=request.args.get("q", ""), SORTS=SORTS, FILTERS=FILTERS
    )


def _member_from_form(member: Member | None) -> tuple[Member | None, list[str]]:
    f = request.form
    errors = []
    name = f.get("name", "").strip()
    display = f.get("display_name", "").strip() or None
    ltu_id = f.get("ltu_id", "").strip().lower() or None
    joined_raw = f.get("joined_on", "").strip()
    joined = parse_date(joined_raw)  # empty = unknown
    if not name:
        errors.append("Namn saknas.")
    if joined_raw and joined is None:
        errors.append("Ogiltigt datum för när personen gick med.")
    if ltu_id:
        clash = db.session.scalar(select(Member).where(Member.ltu_id == ltu_id))
        if clash is not None and clash is not member:
            errors.append(f"LTU-id {ltu_id} används redan av {clash.name}.")
    if errors:
        return None, errors
    member = member or Member()
    member.name, member.display_name, member.ltu_id, member.joined_on = name, display, ltu_id, joined
    member.notes = f.get("notes", "").strip() or None
    return member, []


@bp.route("/medlemmar/ny", methods=["GET", "POST"])
def member_new():
    if request.method == "POST":
        member, errors = _member_from_form(None)
        years = _int(request.form.get("years"), 0)
        paid_on = parse_date(request.form.get("paid_on")) or (member.joined_on if member else None) or today()
        if years < 0 or years > 10:
            errors.append("Antal år måste vara 0–10.")
        if not errors:
            db.session.add(member)
            if years:
                member.payments.append(MembershipPayment(paid_on=paid_on, years=years, recorded_by=g.admin))
            db.session.flush()
            audit("member_created", member_id=member.id, name=member.name, years=years)
            db.session.commit()
            flash(f"{member.name} är tillagd.", "ok")
            return redirect(url_for("admin.members"))
        for e in errors:
            flash(e, "error")
    return render_template("admin/member_form.html", member=None, form=request.form)


@bp.route("/medlemmar/<int:member_id>", methods=["GET", "POST"])
def member_edit(member_id):
    member = _get(Member, member_id)
    if request.method == "POST":
        _, errors = _member_from_form(member)
        if not errors:
            audit("member_updated", member_id=member.id, name=member.name)
            db.session.commit()
            flash("Sparat.", "ok")
            return redirect(url_for("admin.member_edit", member_id=member.id))
        db.session.rollback()
        for e in errors:
            flash(e, "error")
    result_count = db.session.scalar(select(func.count(Result.id)).where(Result.member_id == member.id)) + len(
        member.manual_points
    )
    return render_template(
        "admin/member_form.html", member=member, form=request.form, status=member.status(today()), result_count=result_count
    )


@bp.post("/medlemmar/<int:member_id>/betalning")
def member_payment(member_id):
    member = _get(Member, member_id)
    paid_on = parse_date(request.form.get("paid_on"))
    years = _int(request.form.get("years"), 0)
    if paid_on is None or not 1 <= years <= 10:
        flash("Ange datum och 1–10 år.", "error")
    else:
        member.payments.append(MembershipPayment(paid_on=paid_on, years=years, recorded_by=g.admin))
        audit("payment_added", member_id=member.id, name=member.name, paid_on=paid_on, years=years)
        db.session.commit()
        st = member.status(today())
        flash(f"Betalning registrerad. Medlemskapet gäller till {st.expires_on.isoformat()}.", "ok")
    return redirect(request.form.get("back") or url_for("admin.member_edit", member_id=member.id))


@bp.post("/medlemmar/<int:member_id>/betalning/<int:payment_id>/radera")
def payment_delete(member_id, payment_id):
    payment = _get(MembershipPayment, payment_id)
    if payment.member_id != member_id:
        abort(404)
    audit("payment_deleted", member_id=member_id, paid_on=payment.paid_on, years=payment.years)
    db.session.delete(payment)
    db.session.commit()
    flash("Betalningen är borttagen.", "ok")
    return redirect(url_for("admin.member_edit", member_id=member_id))


@bp.post("/medlemmar/<int:member_id>/radera")
def member_delete(member_id):
    member = _get(Member, member_id)
    if member.results or member.manual_points:
        flash("Medlemmen har poäng och kan inte raderas. Ta bort resultaten först.", "error")
        return redirect(url_for("admin.member_edit", member_id=member.id))
    audit("member_deleted", member_id=member.id, name=member.name)
    db.session.delete(member)
    db.session.commit()
    flash(f"{member.name} är raderad.", "ok")
    return redirect(url_for("admin.members"))


# ---------- periods (LP) ----------


@bp.get("/lp")
def periods():
    return render_template("admin/periods.html", periods=_periods_desc())


def _period_from_form(period: Period | None) -> list[str]:
    f = request.form
    errors = []
    start_year, lp = _int(f.get("start_year")), _int(f.get("lp"))
    starts, ends = parse_date(f.get("starts_on")), parse_date(f.get("ends_on"))
    if not start_year or not 2000 <= start_year <= 2100:
        errors.append("Ogiltigt läsår.")
    if lp not in (1, 2, 3, 4):
        errors.append("LP måste vara 1–4.")
    if not starts or not ends or ends < starts:
        errors.append("Ogiltiga datum (slut måste vara efter start).")
    if errors:
        return errors
    for other in db.session.scalars(select(Period)):
        if other is period:
            continue
        if (other.start_year, other.lp) == (start_year, lp):
            errors.append(f"{other.label} finns redan.")
        elif other.starts_on <= ends and starts <= other.ends_on:
            errors.append(f"Datumen överlappar {other.label} ({other.starts_on}–{other.ends_on}).")
    if period is not None:
        outside = sorted(d.isoformat() for d in period.point_dates if not starts <= d <= ends)
        if outside:
            errors.append("Kvällar hamnar utanför datumen: " + ", ".join(outside))
    if errors:
        return errors
    period = period or Period()
    period.start_year, period.lp, period.starts_on, period.ends_on = start_year, lp, starts, ends
    if period.id is None:
        db.session.add(period)
    return []


@bp.route("/lp/ny", methods=["GET", "POST"])
def period_new():
    if request.method == "POST":
        errors = _period_from_form(None)
        if not errors:
            audit("period_created", **{k: request.form.get(k) for k in ("start_year", "lp", "starts_on", "ends_on")})
            db.session.commit()
            flash("LP skapat.", "ok")
            return redirect(url_for("admin.periods"))
        for e in errors:
            flash(e, "error")
    t = today()
    return render_template("admin/period_form.html", period=None, form=request.form, default_year=t.year if t.month >= 7 else t.year - 1)


@bp.route("/lp/<int:period_id>", methods=["GET", "POST"])
def period_edit(period_id):
    period = _get(Period, period_id)
    if request.method == "POST":
        errors = _period_from_form(period)
        if not errors:
            audit("period_updated", period_id=period.id, label=period.label)
            db.session.commit()
            flash("Sparat.", "ok")
            return redirect(url_for("admin.periods"))
        db.session.rollback()
        for e in errors:
            flash(e, "error")
    return render_template("admin/period_form.html", period=period, form=request.form, default_year=period.start_year)


@bp.post("/lp/<int:period_id>/rakna-om")
def period_recalc(period_id):
    period = _get(Period, period_id)
    changed = recalc_points(period)
    audit("points_recalculated", period=period.label, changed=changed)
    db.session.commit()
    flash(f"Poängen för {period.label} är omräknade ({changed} resultat ändrades).", "ok")
    return redirect(url_for("admin.periods"))


@bp.post("/lp/<int:period_id>/radera")
def period_delete(period_id):
    period = _get(Period, period_id)
    if period.nights or period.manual_points:
        flash("LP:t har poäng och kan inte raderas.", "error")
    else:
        audit("period_deleted", label=period.label)
        db.session.delete(period)
        db.session.commit()
        flash(f"{period.label} är raderat.", "ok")
    return redirect(url_for("admin.periods"))


# ---------- manual points (points without placements) ----------


@bp.get("/lp/<int:period_id>/manuella-poang")
def manual_points(period_id):
    period = _get(Period, period_id)
    entries = sorted(period.manual_points, key=lambda e: (e.date, e.member.name.casefold()))
    return render_template(
        "admin/manual_points.html",
        period=period,
        entries=entries,
        total=sum(e.points for e in entries),
        members=db.session.scalars(select(Member).order_by(Member.name)).all(),
        default_date=min(max(latest_tuesday(today()), period.starts_on), period.ends_on),
    )


def _manual_fields(period: Period) -> tuple[dict, list[str]]:
    f, errors, out = request.form, [], {}
    d = parse_date(f.get("date"))
    if d is None or not period.contains(d):
        errors.append(f"Datumet måste ligga inom {period.label} ({period.starts_on}–{period.ends_on}).")
    try:
        out["points"] = parse_points(f.get("points", ""))
    except ValueError:
        errors.append("Ogiltiga poäng. Skriv t.ex. 12 eller 14,5.")
    out["date"], out["note"] = d, f.get("note", "").strip()[:200] or None
    return out, errors


@bp.post("/lp/<int:period_id>/manuella-poang")
def manual_points_add(period_id):
    period = _get(Period, period_id)
    fields, errors = _manual_fields(period)
    name = request.form.get("member", "").strip()
    hits = find_members(name, list(db.session.scalars(select(Member))))
    if len(hits) != 1:
        errors.append(f"Flera medlemmar matchar '{name}'." if hits else f"Ingen medlem heter '{name}'. Lägg till personen under Medlemmar först.")
    if errors:
        for e in errors:
            flash(e, "error")
    else:
        entry = ManualPoints(period=period, member=hits[0], created_by=g.admin, **fields)
        db.session.add(entry)
        audit("manual_points_added", period=period.label, member=hits[0].name, date=entry.date, points=entry.points)
        db.session.commit()
        flash(f"{hits[0].name}: {fmt_points(fields['points'])} poäng tillagda.", "ok")
    return redirect(url_for("admin.manual_points", period_id=period.id))


@bp.post("/manuella-poang/<int:entry_id>")
def manual_points_update(entry_id):
    entry = _get(ManualPoints, entry_id)
    fields, errors = _manual_fields(entry.period)
    if errors:
        for e in errors:
            flash(e, "error")
    else:
        before = {"date": entry.date, "points": entry.points, "note": entry.note}
        for k, v in fields.items():
            setattr(entry, k, v)
        audit("manual_points_updated", member=entry.member.name, before=before, after=fields)
        db.session.commit()
        flash(f"Sparat: {entry.member.name}.", "ok")
    return redirect(url_for("admin.manual_points", period_id=entry.period_id))


@bp.post("/manuella-poang/<int:entry_id>/radera")
def manual_points_delete(entry_id):
    entry = _get(ManualPoints, entry_id)
    period_id = entry.period_id
    audit("manual_points_deleted", member=entry.member.name, date=entry.date, points=entry.points)
    db.session.delete(entry)
    db.session.commit()
    flash("Posten är borttagen.", "ok")
    return redirect(url_for("admin.manual_points", period_id=period_id))


# ---------- news ----------


@bp.get("/nyheter")
def news():
    posts = db.session.scalars(select(NewsPost).order_by(NewsPost.published_at.desc())).all()
    return render_template("admin/news.html", posts=posts)


def _news_form(post: NewsPost | None):
    f = request.form
    title, body = f.get("title", "").strip(), f.get("body_md", "")
    if f.get("action") == "preview":
        return None, render_markdown(body)
    if not title or not body.strip():
        flash("Titel och text behövs.", "error")
        return None, None
    post = post or NewsPost(author=g.admin, published_at=utcnow())
    post.title, post.body_md = title, body
    return post, None


@bp.route("/nyheter/ny", methods=["GET", "POST"])
def news_new():
    preview = None
    if request.method == "POST":
        post, preview = _news_form(None)
        if post:
            db.session.add(post)
            db.session.flush()
            audit("news_created", post_id=post.id, title=post.title)
            db.session.commit()
            flash("Nyheten är publicerad.", "ok")
            return redirect(url_for("admin.news"))
    return render_template("admin/news_form.html", post=None, form=request.form, preview=preview)


@bp.route("/nyheter/<int:post_id>", methods=["GET", "POST"])
def news_edit(post_id):
    post = _get(NewsPost, post_id)
    preview = None
    if request.method == "POST":
        saved, preview = _news_form(post)
        if saved:
            audit("news_updated", post_id=post.id, title=post.title)
            db.session.commit()
            flash("Sparat.", "ok")
            return redirect(url_for("admin.news"))
        db.session.rollback()
    return render_template("admin/news_form.html", post=post, form=request.form, preview=preview)


@bp.post("/nyheter/<int:post_id>/radera")
def news_delete(post_id):
    post = _get(NewsPost, post_id)
    audit("news_deleted", title=post.title)
    db.session.delete(post)
    db.session.commit()
    flash("Nyheten är raderad.", "ok")
    return redirect(url_for("admin.news"))


# ---------- audit log ----------


@bp.get("/logg")
def audit_log():
    entries = db.session.scalars(select(AuditLog).order_by(AuditLog.at.desc()).limit(300)).all()
    return render_template("admin/audit.html", entries=entries)

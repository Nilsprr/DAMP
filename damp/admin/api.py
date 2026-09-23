"""JSON endpoints used by the admin night editor."""

from flask import g, jsonify, request, url_for
from sqlalchemy import select

from ..extensions import db
from ..models import Member, MembershipPayment, Night
from ..nights import NightError, save_night
from ..scoring import points_for
from ..util import parse_date, today
from . import audit, bp
from .routes import _get, _int, _member_json

MAX_SUGGESTIONS = 8


@bp.get("/api/members")
def api_members():
    """Name / display name / LTU-id search. Status is evaluated on `date` (the night's date)."""
    q = request.args.get("q", "").strip().casefold()
    on = parse_date(request.args.get("date")) or today()
    if not q:
        return jsonify([])
    scored = []
    for m in db.session.scalars(select(Member)):
        fields = [(m.name or "").casefold(), (m.display_name or "").casefold(), (m.ltu_id or "").casefold()]
        if any(f.startswith(q) for f in fields) or any(w.startswith(q) for f in fields[:2] for w in f.split()):
            rank = 0
        elif any(q in f for f in fields):
            rank = 1
        else:
            continue
        scored.append((rank, m.name.casefold(), m))
    scored.sort(key=lambda t: t[:2])
    return jsonify([_member_json(m, on) for _, _, m in scored[:MAX_SUGGESTIONS]])


@bp.post("/api/points-preview")
def api_points_preview():
    """{"tables": [[wipes, wipes, ...], ...]} -> {"tables": [[points, ...], ...]} in placement order."""
    tables = (request.get_json(silent=True) or {}).get("tables") or []
    out = []
    for wipes_list in tables:
        size = len(wipes_list)
        out.append([points_for(i, size, _int(w, 0)) for i, w in enumerate(wipes_list, start=1)])
    return jsonify(tables=out)


def _save(night: Night | None):
    payload = request.get_json(silent=True) or {}
    editing = night is not None
    try:
        night = save_night(payload, night)
    except NightError as e:
        db.session.rollback()
        return jsonify(errors=e.errors), 400
    db.session.flush()
    audit(
        "night_updated" if editing else "night_created",
        night_id=night.id,
        date=night.date,
        tables=[[r.member.name for r in t.results] for t in night.tables],
    )
    db.session.commit()
    return jsonify(ok=True, id=night.id, url=url_for("admin.night_view", night_id=night.id))


@bp.post("/api/nights")
def api_night_create():
    return _save(None)


@bp.post("/api/nights/<int:night_id>")
def api_night_update(night_id):
    return _save(_get(Night, night_id))


@bp.post("/api/members/<int:member_id>/payments")
def api_member_payment(member_id):
    """The editor's "Förnya nu": record a payment and return the member's status on the night date."""
    member = _get(Member, member_id)
    body = request.get_json(silent=True) or {}
    paid_on = parse_date(body.get("paid_on"))
    years = _int(body.get("years"), 0)
    if paid_on is None or not 1 <= years <= 10:
        return jsonify(errors=["Ange datum och 1–10 år."]), 400
    member.payments.append(MembershipPayment(paid_on=paid_on, years=years, recorded_by=g.admin))
    audit("payment_added", member_id=member.id, name=member.name, paid_on=paid_on, years=years, via="night_editor")
    db.session.commit()
    on = parse_date(body.get("date")) or today()
    return jsonify(_member_json(member, on))

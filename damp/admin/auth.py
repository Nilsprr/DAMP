"""Admin login: username + password, then a TOTP code from an authenticator app.

First login for an account without a TOTP secret goes through enrolment
(scan QR, confirm one code). Accounts are created from the CLI only.
"""

import hmac
import time

import pyotp
import segno
from flask import flash, redirect, render_template, request, session, url_for
from sqlalchemy import select
from werkzeug.security import check_password_hash, generate_password_hash

from ..extensions import db, limiter
from ..models import AdminUser, utcnow
from . import audit, bp

PENDING_TTL = 300  # seconds between a correct password and the TOTP step
ISSUER = "DAMP"
# Compared against when the username doesn't exist, so timing doesn't reveal valid usernames.
_DUMMY_HASH = generate_password_hash("not-a-real-password")


def verify_totp(secret: str, code: str, last_step: int | None) -> int | None:
    """Return the matched time step, or None. Rejects steps at or before `last_step` (replay)."""
    code = "".join(code.split())
    if len(code) != 6 or not code.isdigit():
        return None
    totp = pyotp.TOTP(secret)
    now_step = int(time.time()) // totp.interval
    for step in (now_step - 1, now_step, now_step + 1):
        if last_step is not None and step <= last_step:
            continue
        if hmac.compare_digest(totp.generate_otp(step), code):
            return step
    return None


def _safe_next(url: str | None) -> str | None:
    if url and url.startswith("/admin") and not url.startswith("//"):
        return url
    return None


def _pending_user() -> AdminUser | None:
    uid, at = session.get("pending_admin"), session.get("pending_at", 0)
    if not uid or time.time() - at > PENDING_TTL:
        return None
    return db.session.get(AdminUser, uid)


def _finish_login(user: AdminUser):
    next_url = session.get("pending_next")
    session.clear()
    session.permanent = True
    session["admin_id"] = user.id
    user.last_login_at = utcnow()
    audit("login", username=user.username)
    db.session.commit()
    return redirect(next_url or url_for("admin.dashboard"))


@bp.route("/login", methods=["GET", "POST"])
@limiter.limit("10 per minute", methods=["POST"])
def auth_login():
    if request.method == "POST":
        username = request.form.get("username", "").strip().lower()
        password = request.form.get("password", "")
        user = db.session.scalar(select(AdminUser).where(AdminUser.username == username))
        ok = check_password_hash(user.password_hash if user else _DUMMY_HASH, password)
        if user and ok:
            next_url = _safe_next(request.args.get("next"))
            session.clear()
            session.update(pending_admin=user.id, pending_at=time.time(), pending_next=next_url)
            return redirect(url_for("admin.auth_totp" if user.totp_secret else "admin.auth_enroll"))
        flash("Fel användarnamn eller lösenord.", "error")
    return render_template("admin/login.html")


@bp.route("/login/kod", methods=["GET", "POST"])
@limiter.limit("10 per minute", methods=["POST"])
def auth_totp():
    user = _pending_user()
    if user is None:
        flash("Logga in igen.", "warning")
        return redirect(url_for("admin.auth_login"))
    if not user.totp_secret:
        return redirect(url_for("admin.auth_enroll"))
    if request.method == "POST":
        step = verify_totp(user.totp_secret, request.form.get("code", ""), user.last_totp_step)
        if step is not None:
            user.last_totp_step = step
            return _finish_login(user)
        flash("Fel kod. Försök igen.", "error")
    return render_template("admin/totp.html")


@bp.route("/login/aktivera", methods=["GET", "POST"])
@limiter.limit("10 per minute", methods=["POST"])
def auth_enroll():
    user = _pending_user()
    if user is None:
        flash("Logga in igen.", "warning")
        return redirect(url_for("admin.auth_login"))
    if user.totp_secret:
        return redirect(url_for("admin.auth_totp"))

    secret = session.get("enroll_secret")
    if not secret:
        secret = session["enroll_secret"] = pyotp.random_base32()

    if request.method == "POST":
        step = verify_totp(secret, request.form.get("code", ""), None)
        if step is not None:
            user.totp_secret = secret
            user.last_totp_step = step
            audit("totp_enrolled", username=user.username)
            return _finish_login(user)
        flash("Koden stämde inte. Kontrollera att appen visar DAMP och försök igen.", "error")

    uri = pyotp.TOTP(secret).provisioning_uri(name=user.username, issuer_name=ISSUER)
    qr_svg = segno.make(uri, error="m").svg_inline(scale=5, border=2)
    return render_template("admin/enroll.html", qr_svg=qr_svg, secret=secret)


@bp.post("/logout")
def auth_logout():
    session.clear()
    flash("Du är utloggad.", "ok")
    return redirect(url_for("public.index"))

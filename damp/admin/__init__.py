import json

from flask import Blueprint, g, jsonify, redirect, request, session, url_for

from ..extensions import db
from ..models import AdminUser, AuditLog

bp = Blueprint("admin", __name__, url_prefix="/admin")

# Endpoints reachable without a full login (password + TOTP).
PUBLIC_ENDPOINTS = {"admin.auth_login", "admin.auth_totp", "admin.auth_enroll"}


@bp.before_request
def require_login():
    if request.endpoint in PUBLIC_ENDPOINTS:
        return None
    if g.get("admin") is None:
        if request.path.startswith("/admin/api/"):
            return jsonify(error="Inte inloggad."), 401
        return redirect(url_for("admin.auth_login", next=request.full_path.rstrip("?")))
    return None


def load_admin():
    """Registered app-wide so public pages can show the Admin link to logged-in admins."""
    admin_id = session.get("admin_id")
    g.admin = db.session.get(AdminUser, admin_id) if admin_id else None
    if admin_id and g.admin is None:
        session.pop("admin_id", None)


def audit(action: str, **detail) -> None:
    db.session.add(
        AuditLog(
            admin_id=g.admin.id if g.get("admin") else None,
            action=action,
            detail=json.dumps(detail, ensure_ascii=False, default=str) if detail else None,
        )
    )


from . import api, auth, routes  # noqa: E402,F401

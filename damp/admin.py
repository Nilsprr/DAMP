"""Admin pages. Each is a static shell; the JS in static/admin/ loads the data and saves changes.

Saving goes through /admin/api/*: in production a Cloudflare Pages Function that
commits to GitHub (functions/admin/api/[[path]].js), locally devapi.py.
"""

from flask import Blueprint, jsonify, render_template

from .scoring import points_table

bp = Blueprint("admin", __name__, url_prefix="/admin")

# endpoint -> (url, menu label, template)
PAGES = {
    "dashboard": ("/", "Översikt", "dashboard.html"),
    "table_editor": ("/bord/redigera/", "+ Nytt bord", "table_editor.html"),
    "tables": ("/bord/", "Bord", "tables.html"),
    "members": ("/medlemmar/", "Medlemmar", "members.html"),
    "periods": ("/lp/", "LP", "periods.html"),
    "manual_points": ("/manuella-poang/", "Manuella poäng", "manual_points.html"),
    "news": ("/nyheter/", "Nyheter", "news.html"),
    "history": ("/historik/", "Historik", "history.html"),
}


def _page(template: str):
    return lambda: render_template(f"admin/{template}", admin_pages=PAGES)


for endpoint, (url, _label, template) in PAGES.items():
    bp.add_url_rule(url, endpoint, _page(template), methods=["GET"])


@bp.get("/poang.json")
def points():
    """scoring.points_for as a lookup table, for the table editor's preview and saved points."""
    return jsonify(points_table())

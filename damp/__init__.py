import os
from pathlib import Path

from flask import Flask, render_template

from .store import DataError
from .util import fmt_decimal, fmt_points, long_date, render_markdown, short_date, today

ROOT = Path(__file__).resolve().parent.parent

# Sent by the dev server and written to dist/_headers for Cloudflare Pages.
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "same-origin",
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self'; img-src 'self' data:; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src https://fonts.gstatic.com; "
        "connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    ),
}


def create_app(data_dir: str | Path | None = None, *, dev_admin: bool = True) -> Flask:
    """The site as a Flask app: served live for local development, rendered to dist/ by build.py.

    dev_admin=True adds the local admin API (reads and writes data/ directly, no login).
    It is never part of the published site.
    """
    app = Flask(__name__)
    app.config.update(
        DATA_DIR=Path(data_dir or os.environ.get("DAMP_DATA_DIR") or ROOT / "data"),
        DEV_ADMIN=dev_admin,
        TIMEZONE="Europe/Stockholm",
    )

    from .admin import bp as admin_bp
    from .cli import register_cli
    from .public import bp as public_bp

    app.register_blueprint(public_bp)
    app.register_blueprint(admin_bp)
    if dev_admin:
        from .devapi import bp as devapi_bp

        app.register_blueprint(devapi_bp)
    register_cli(app)

    @app.errorhandler(DataError)
    def data_error(e):
        return render_template("data_error.html", errors=e.errors), 500

    @app.errorhandler(404)
    def not_found(e):
        return render_template("404.html"), 404

    @app.after_request
    def security_headers(resp):
        for k, v in SECURITY_HEADERS.items():
            resp.headers.setdefault(k, v)
        return resp

    app.jinja_env.filters["short_date"] = short_date
    app.jinja_env.filters["long_date"] = long_date
    app.jinja_env.filters["markdown"] = render_markdown
    app.jinja_env.filters["points"] = fmt_points
    app.jinja_env.filters["decimal"] = fmt_decimal
    app.jinja_env.globals["today"] = today
    app.jinja_env.globals["THEMES"] = [("data", "DATA"), ("slop", "AI SLOP"), ("dark", "DARK")]
    return app

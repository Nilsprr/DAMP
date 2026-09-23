import os

from flask import Flask
from sqlalchemy import event
from sqlalchemy.engine import Engine

from .config import Config
from .extensions import csrf, db, limiter, migrate
from .util import fmt_decimal, fmt_points, long_date, render_markdown, short_date, today


@event.listens_for(Engine, "connect")
def _sqlite_pragmas(dbapi_conn, _record):
    if dbapi_conn.__class__.__module__.startswith("sqlite3"):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()


def create_app(test_config: dict | None = None) -> Flask:
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(Config)
    if test_config:
        app.config.update(test_config)
    if not app.config.get("SQLALCHEMY_DATABASE_URI"):
        os.makedirs(app.instance_path, exist_ok=True)
        app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + os.path.join(app.instance_path, "damp.db")
    if os.environ.get("DAMP_ENV") == "production" and app.config["SECRET_KEY"].startswith("dev-"):
        raise RuntimeError("Set DAMP_SECRET_KEY in production.")

    db.init_app(app)
    migrate.init_app(app, db, render_as_batch=True)
    csrf.init_app(app)
    limiter.init_app(app)

    from . import models  # noqa: F401  (register tables with SQLAlchemy/Alembic)
    from .admin import bp as admin_bp
    from .cli import register_cli
    from .public import bp as public_bp

    from .admin import load_admin

    app.before_request(load_admin)
    app.register_blueprint(public_bp)
    app.register_blueprint(admin_bp)
    register_cli(app)

    @app.after_request
    def security_headers(resp):
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("Referrer-Policy", "same-origin")
        resp.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; img-src 'self' data:; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src https://fonts.gstatic.com; "
            "frame-ancestors 'none'; base-uri 'self'; form-action 'self'",
        )
        return resp

    app.jinja_env.filters["short_date"] = short_date
    app.jinja_env.filters["long_date"] = long_date
    app.jinja_env.filters["markdown"] = render_markdown
    app.jinja_env.filters["points"] = fmt_points
    app.jinja_env.filters["decimal"] = fmt_decimal
    app.jinja_env.globals["today"] = today
    app.jinja_env.globals["THEMES"] = [("data", "DATA"), ("slop", "AI SLOP"), ("dark", "DARK")]
    return app

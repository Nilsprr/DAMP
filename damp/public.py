"""Public viewer. GET only: no login, nothing here changes data."""

from flask import Blueprint, abort, jsonify, render_template, request
from sqlalchemy import select

from .extensions import db
from .models import NewsPost, Period
from .stats import lp_data
from .util import today

bp = Blueprint("public", __name__)

NEWS_PER_PAGE = 10


def _periods() -> list[Period]:
    return list(db.session.scalars(select(Period).order_by(Period.start_year.desc(), Period.lp.desc())))


def default_period(periods: list[Period]) -> Period | None:
    """The LP running today; otherwise the latest one that has points; otherwise the latest."""
    t = today()
    current = next((p for p in periods if p.contains(t)), None)
    if current and current.point_dates:
        return current
    return next((p for p in periods if p.point_dates and p.starts_on <= t), current or (periods[0] if periods else None))


@bp.get("/")
def index():
    periods = _periods()
    wanted = request.args.get("lp", type=int)
    period = next((p for p in periods if p.id == wanted), None) or default_period(periods)
    news = db.session.scalars(select(NewsPost).order_by(NewsPost.published_at.desc()).limit(3)).all()
    return render_template(
        "public/index.html",
        periods=periods,
        period=period,
        data=lp_data(period) if period else None,
        news=news,
    )


@bp.get("/api/lp/<int:period_id>")
def api_lp(period_id: int):
    period = db.session.get(Period, period_id) or abort(404)
    return jsonify(lp_data(period))


@bp.get("/om")
def about():
    return render_template("public/about.html")


@bp.get("/nyheter")
def news():
    page = max(request.args.get("sida", 1, type=int), 1)
    posts = db.paginate(
        select(NewsPost).order_by(NewsPost.published_at.desc()), page=page, per_page=NEWS_PER_PAGE, error_out=False
    )
    return render_template("public/news.html", posts=posts)


@bp.get("/nyheter/<int:post_id>")
def news_post(post_id: int):
    post = db.session.get(NewsPost, post_id) or abort(404)
    return render_template("public/news_post.html", post=post)

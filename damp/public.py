"""Public viewer. GET only; build.py renders every page here to static HTML."""

import math

from flask import Blueprint, abort, render_template

from .stats import lp_data
from .store import Period
from .util import get_store, today

bp = Blueprint("public", __name__)

NEWS_PER_PAGE = 10


def default_period(periods: list[Period]) -> Period | None:
    """The LP running today; otherwise the latest one that has points; otherwise the latest."""
    t = today()
    current = next((p for p in periods if p.contains(t)), None)
    if current and current.point_dates:
        return current
    return next((p for p in periods if p.point_dates and p.starts_on <= t), current or (periods[0] if periods else None))


@bp.get("/")
@bp.get("/lp/<slug>/")
def index(slug: str | None = None):
    store = get_store()
    period = store.period(slug) if slug else default_period(store.periods)
    if slug and period is None:
        abort(404)
    return render_template(
        "public/index.html",
        periods=store.periods,
        period=period,
        data=lp_data(period) if period else None,
        news=store.news[:3],
    )


class Page:
    """Just enough of Flask-SQLAlchemy's Pagination for news.html."""

    def __init__(self, items: list, page: int, per_page: int):
        self.page = page
        self.pages = max(1, math.ceil(len(items) / per_page))
        self.items = items[(page - 1) * per_page : page * per_page]
        self.has_prev = page > 1
        self.has_next = page < self.pages
        # Page 1 lives at /nyheter/ (url_for drops None), so it isn't reachable as /nyheter/sida/1/.
        self.prev_num = page - 1 if page > 2 else None
        self.next_num = page + 1


@bp.get("/nyheter/")
@bp.get("/nyheter/sida/<int:sida>/")
def news(sida: int | None = None):
    if sida is not None and sida < 2:
        abort(404)
    posts = Page(get_store().news, sida or 1, NEWS_PER_PAGE)
    if posts.page > posts.pages:
        abort(404)
    return render_template("public/news.html", posts=posts)


@bp.get("/nyheter/<int:post_id>/")
def news_post(post_id: int):
    post = next((p for p in get_store().news if p.id == post_id), None) or abort(404)
    return render_template("public/news_post.html", post=post)


@bp.get("/om/")
def about():
    return render_template("public/about.html")


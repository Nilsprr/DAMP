from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from flask import current_app

WEEKDAYS_SV = ["mån", "tis", "ons", "tor", "fre", "lör", "sön"]
MONTHS_SV = ["jan", "feb", "mar", "apr", "maj", "jun", "jul", "aug", "sep", "okt", "nov", "dec"]


def now() -> datetime:
    return datetime.now(ZoneInfo(current_app.config["TIMEZONE"]))


def today() -> date:
    return now().date()


def latest_tuesday(on: date) -> date:
    """The most recent Tuesday on or before `on`."""
    return on - timedelta(days=(on.weekday() - 1) % 7)


def add_years(d: date, years: int) -> date:
    try:
        return d.replace(year=d.year + years)
    except ValueError:  # 29 Feb -> 28 Feb
        return d.replace(year=d.year + years, day=28)


def parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        return None


def short_date(d: date) -> str:
    """'22 sep'"""
    return f"{d.day} {MONTHS_SV[d.month - 1]}"


def long_date(d: date) -> str:
    """'tis 22 sep 2026'"""
    return f"{WEEKDAYS_SV[d.weekday()]} {d.day} {MONTHS_SV[d.month - 1]} {d.year}"


def fmt_points(value) -> str:
    """Swedish number format for points: 24 -> '24', 14.5 -> '14,5', -2 -> '−2'."""
    if value is None:
        return "–"
    text = f"{round(float(value), 2):.2f}".rstrip("0").rstrip(".")
    return text.replace(".", ",").replace("-", "\u2212")


def fmt_decimal(value, digits: int = 1) -> str:
    """3.25 -> '3,3' (fixed decimals, Swedish comma); None -> '–'."""
    return "–" if value is None else f"{value:.{digits}f}".replace(".", ",")


def render_markdown(text: str | None):
    import markdown
    import nh3
    from markupsafe import Markup

    html = markdown.markdown(text or "", extensions=["extra", "sane_lists", "nl2br"])
    return Markup(nh3.clean(html, link_rel="noopener noreferrer nofollow"))

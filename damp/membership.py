"""Membership coverage. A payment covers `years` years from its payment day.

Renewals stack: paying while still active extends from the current expiry, so
paying early never loses time. A gap (paying after expiry) starts a new period.
"""

from dataclasses import dataclass
from datetime import date

from .util import add_years


def coverage(payments) -> list[tuple[date, date]]:
    """Merged (start, end) intervals covered by `payments`, both ends inclusive."""
    intervals: list[tuple[date, date]] = []
    for p in sorted(payments, key=lambda p: (p.paid_on, p.id or 0)):
        if intervals and p.paid_on <= intervals[-1][1]:
            start, end = intervals[-1]
            intervals[-1] = (start, add_years(end, p.years))
        else:
            intervals.append((p.paid_on, add_years(p.paid_on, p.years)))
    return intervals


def expires_on(payments) -> date | None:
    intervals = coverage(payments)
    return intervals[-1][1] if intervals else None


def is_active(payments, on: date) -> bool:
    return any(start <= on <= end for start, end in coverage(payments))


@dataclass
class Status:
    active: bool
    expires_on: date | None
    days_left: int | None  # negative once expired; None if never paid
    last_paid_on: date | None

    @property
    def key(self) -> str:
        """'active' | 'soon' (< 30 days left) | 'pending' (paid, starts later) | 'expired' | 'never'"""
        if self.expires_on is None:
            return "never"
        if not self.active:
            return "pending" if self.days_left > 0 else "expired"
        return "soon" if self.days_left < 30 else "active"

    @property
    def label(self) -> str:
        return {
            "active": "Aktiv",
            "soon": "Går snart ut",
            "pending": "Börjar gälla senare",
            "expired": "Utgången",
            "never": "Aldrig betalt",
        }[self.key]


def status(payments, on: date) -> Status:
    payments = list(payments)
    exp = expires_on(payments)
    return Status(
        active=is_active(payments, on),
        expires_on=exp,
        days_left=(exp - on).days if exp else None,
        last_paid_on=max((p.paid_on for p in payments), default=None),
    )

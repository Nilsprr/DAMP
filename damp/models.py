import datetime as dt

from sqlalchemy import CheckConstraint, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from . import membership
from .extensions import db


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class AdminUser(db.Model):
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    password_hash: Mapped[str] = mapped_column(String(256))
    totp_secret: Mapped[str | None] = mapped_column(String(64))
    # Last accepted TOTP time step, so a code can't be replayed within its window.
    last_totp_step: Mapped[int | None]
    last_login_at: Mapped[dt.datetime | None]
    created_at: Mapped[dt.datetime] = mapped_column(default=utcnow)


class Member(db.Model):
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    display_name: Mapped[str | None] = mapped_column(String(60))
    ltu_id: Mapped[str | None] = mapped_column(String(32), unique=True)
    joined_on: Mapped[dt.date | None]  # None = unknown (e.g. imported players)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = mapped_column(default=utcnow)

    payments: Mapped[list["MembershipPayment"]] = relationship(
        back_populates="member", cascade="all, delete-orphan", order_by="MembershipPayment.paid_on"
    )
    results: Mapped[list["Result"]] = relationship(back_populates="member")
    manual_points: Mapped[list["ManualPoints"]] = relationship(back_populates="member")

    @property
    def public_name(self) -> str:
        return self.display_name or self.name

    def status(self, on: dt.date) -> membership.Status:
        return membership.status(self.payments, on)

    def is_active(self, on: dt.date) -> bool:
        return membership.is_active(self.payments, on)


class MembershipPayment(db.Model):
    __table_args__ = (CheckConstraint("years >= 1", name="ck_payment_years"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    member_id: Mapped[int] = mapped_column(ForeignKey("member.id", ondelete="CASCADE"))
    paid_on: Mapped[dt.date]
    years: Mapped[int] = mapped_column(default=1)
    recorded_by_id: Mapped[int | None] = mapped_column(ForeignKey("admin_user.id", ondelete="SET NULL"))
    created_at: Mapped[dt.datetime] = mapped_column(default=utcnow)

    member: Mapped[Member] = relationship(back_populates="payments")
    recorded_by: Mapped[AdminUser | None] = relationship()


class Period(db.Model):
    """A läsperiod, e.g. LP1 26/27 (start_year=2026, lp=1)."""

    __table_args__ = (
        UniqueConstraint("start_year", "lp", name="uq_period_year_lp"),
        CheckConstraint("lp BETWEEN 1 AND 4", name="ck_period_lp"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    start_year: Mapped[int]
    lp: Mapped[int]
    starts_on: Mapped[dt.date]
    ends_on: Mapped[dt.date]

    nights: Mapped[list["Night"]] = relationship(back_populates="period", order_by="Night.date")
    manual_points: Mapped[list["ManualPoints"]] = relationship(
        back_populates="period", order_by="ManualPoints.date"
    )

    @property
    def point_dates(self) -> set[dt.date]:
        """Dates with any points in this LP: nights plus manual points."""
        return {n.date for n in self.nights} | {m.date for m in self.manual_points}

    @property
    def school_year(self) -> str:
        return f"{self.start_year % 100:02d}/{(self.start_year + 1) % 100:02d}"

    @property
    def label(self) -> str:
        return f"LP{self.lp} {self.school_year}"

    def contains(self, d: dt.date) -> bool:
        return self.starts_on <= d <= self.ends_on


class Night(db.Model):
    id: Mapped[int] = mapped_column(primary_key=True)
    period_id: Mapped[int] = mapped_column(ForeignKey("period.id"))
    date: Mapped[dt.date] = mapped_column(unique=True)
    note: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[dt.datetime] = mapped_column(default=utcnow)

    period: Mapped[Period] = relationship(back_populates="nights")
    tables: Mapped[list["PokerTable"]] = relationship(
        back_populates="night", cascade="all, delete-orphan", order_by="PokerTable.table_no"
    )

    @property
    def player_count(self) -> int:
        return sum(len(t.results) for t in self.tables)


class PokerTable(db.Model):
    __table_args__ = (UniqueConstraint("night_id", "table_no", name="uq_table_night_no"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    night_id: Mapped[int] = mapped_column(ForeignKey("night.id", ondelete="CASCADE"))
    table_no: Mapped[int]

    night: Mapped[Night] = relationship(back_populates="tables")
    results: Mapped[list["Result"]] = relationship(
        back_populates="table", cascade="all, delete-orphan", order_by="Result.placement"
    )


class Result(db.Model):
    __table_args__ = (
        UniqueConstraint("table_id", "placement", name="uq_result_table_placement"),
        UniqueConstraint("table_id", "member_id", name="uq_result_table_member"),
        CheckConstraint("placement >= 1", name="ck_result_placement"),
        CheckConstraint("wipes >= 0", name="ck_result_wipes"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    table_id: Mapped[int] = mapped_column(ForeignKey("poker_table.id", ondelete="CASCADE"))
    member_id: Mapped[int] = mapped_column(ForeignKey("member.id"))
    placement: Mapped[int]
    points: Mapped[float]
    wipes: Mapped[int] = mapped_column(default=0)

    table: Mapped[PokerTable] = relationship(back_populates="results")
    member: Mapped[Member] = relationship(back_populates="results")


class ManualPoints(db.Model):
    """Points on a date without a placement, e.g. LP totals imported from a spreadsheet.

    Counted in standings and the chart (and as a night played), but not in wins,
    average placement or wipes. Not touched by recalc_points.
    """

    __tablename__ = "manual_points"

    id: Mapped[int] = mapped_column(primary_key=True)
    period_id: Mapped[int] = mapped_column(ForeignKey("period.id"))
    member_id: Mapped[int] = mapped_column(ForeignKey("member.id"))
    date: Mapped[dt.date]
    points: Mapped[float]
    note: Mapped[str | None] = mapped_column(String(200))
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("admin_user.id", ondelete="SET NULL"))
    created_at: Mapped[dt.datetime] = mapped_column(default=utcnow)

    period: Mapped[Period] = relationship(back_populates="manual_points")
    member: Mapped[Member] = relationship(back_populates="manual_points")
    created_by: Mapped[AdminUser | None] = relationship()


class NewsPost(db.Model):
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    body_md: Mapped[str] = mapped_column(Text)
    published_at: Mapped[dt.datetime] = mapped_column(default=utcnow)
    author_id: Mapped[int | None] = mapped_column(ForeignKey("admin_user.id", ondelete="SET NULL"))

    author: Mapped[AdminUser | None] = relationship()


class AuditLog(db.Model):
    id: Mapped[int] = mapped_column(primary_key=True)
    admin_id: Mapped[int | None] = mapped_column(ForeignKey("admin_user.id", ondelete="SET NULL"))
    action: Mapped[str] = mapped_column(String(64))
    detail: Mapped[str | None] = mapped_column(Text)  # JSON
    at: Mapped[dt.datetime] = mapped_column(default=utcnow)

    admin: Mapped[AdminUser | None] = relationship()

from datetime import date

import pytest
from werkzeug.security import generate_password_hash

from damp import create_app
from damp.extensions import db
from damp.models import AdminUser, Member, MembershipPayment, Period


@pytest.fixture
def app():
    app = create_app(
        {
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "WTF_CSRF_ENABLED": False,
            "RATELIMIT_ENABLED": False,
            "SECRET_KEY": "test",
        }
    )
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


def simple_points(placement, table_size, wipes=0):
    return table_size - placement + 1


@pytest.fixture(autouse=True)
def fixed_scoring(monkeypatch):
    """Mechanics tests use a fixed rule, so editing damp/scoring.py doesn't break them."""
    monkeypatch.setattr("damp.nights.points_for", simple_points)
    monkeypatch.setattr("damp.admin.api.points_for", simple_points)


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def admin(app):
    user = AdminUser(username="nils", password_hash=generate_password_hash("correct horse battery"))
    db.session.add(user)
    db.session.commit()
    return user


@pytest.fixture
def admin_client(client, admin):
    with client.session_transaction() as s:
        s["admin_id"] = admin.id
    return client


@pytest.fixture
def period(app):
    p = Period(start_year=2026, lp=1, starts_on=date(2026, 8, 31), ends_on=date(2026, 11, 1))
    db.session.add(p)
    db.session.commit()
    return p


def make_member(name, paid_on=date(2026, 8, 1), years=1, ltu_id=None):
    m = Member(name=name, ltu_id=ltu_id, joined_on=paid_on or date(2026, 1, 1))
    if paid_on:
        m.payments.append(MembershipPayment(paid_on=paid_on, years=years))
    db.session.add(m)
    db.session.commit()
    return m


@pytest.fixture
def members(app):
    return [make_member(n, ltu_id=f"{n.lower()}-1") for n in ["Anna", "Bert", "Cleo", "Dan", "Eva"]]

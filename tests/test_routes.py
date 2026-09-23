import time
from datetime import date

import pyotp
import pytest

from damp.extensions import db
from damp.models import AdminUser, Member

from .conftest import make_member

PUBLIC = ["/", "/om", "/nyheter"]


@pytest.mark.parametrize("url", PUBLIC)
def test_public_pages_render(client, url):
    assert client.get(url).status_code == 200


def test_index_with_data(client, period, members):
    from damp.nights import save_night

    save_night({"date": "2026-09-08", "period_id": period.id, "tables": [[{"member_id": m.id} for m in members]]})
    db.session.commit()
    r = client.get(f"/?lp={period.id}")
    assert r.status_code == 200
    assert "Anna" in r.text and "anna-1" not in r.text  # LTU-id never shown publicly
    assert client.get(f"/api/lp/{period.id}").json["players"][0]["name"] == "Anna"


@pytest.mark.parametrize("url", PUBLIC + ["/api/lp/1", "/nyheter/1"])
@pytest.mark.parametrize("method", ["post", "put", "delete", "patch"])
def test_public_is_read_only(client, url, method):
    assert getattr(client, method)(url).status_code == 405


def test_public_pages_set_no_cookie(client):
    assert "Set-Cookie" not in client.get("/").headers


@pytest.mark.parametrize("url", ["/admin/", "/admin/medlemmar", "/admin/kvallar/ny", "/admin/lp", "/admin/logg"])
def test_admin_requires_login(client, url):
    r = client.get(url)
    assert r.status_code == 302 and "/admin/login" in r.headers["Location"]


def test_admin_api_requires_login(client):
    assert client.get("/admin/api/members?q=a").status_code == 401
    assert client.post("/admin/api/nights", json={}).status_code == 401


def _login_password(client, pw="correct horse battery"):
    return client.post("/admin/login", data={"username": "Nils", "password": pw})


def test_wrong_password(client, admin):
    r = _login_password(client, "nope")
    assert r.status_code == 200 and "Fel användarnamn" in r.text
    with client.session_transaction() as s:
        assert "admin_id" not in s and "pending_admin" not in s


def test_password_alone_does_not_log_in(client, admin):
    r = _login_password(client)
    assert r.headers["Location"].endswith("/admin/login/aktivera")
    assert client.get("/admin/").status_code == 302


def test_enroll_then_login_with_totp(client, admin):
    _login_password(client)
    client.get("/admin/login/aktivera")
    with client.session_transaction() as s:
        secret = s["enroll_secret"]
    r = client.post("/admin/login/aktivera", data={"code": "000000" if pyotp.TOTP(secret).now() != "000000" else "111111"})
    assert "Koden stämde inte" in r.text
    r = client.post("/admin/login/aktivera", data={"code": pyotp.TOTP(secret).now()})
    assert r.status_code == 302
    assert client.get("/admin/").status_code == 200
    assert db.session.get(AdminUser, admin.id).totp_secret == secret

    # Log out, log back in: now it asks for the code, and the same code can't be replayed.
    client.post("/admin/logout")
    r = _login_password(client)
    assert r.headers["Location"].endswith("/admin/login/kod")
    r = client.post("/admin/login/kod", data={"code": pyotp.TOTP(secret).now()})
    assert "Fel kod" in r.text  # replay of the code used at enrolment
    user = db.session.get(AdminUser, admin.id)
    next_step = user.last_totp_step + 1
    code = pyotp.TOTP(secret).generate_otp(next_step)
    if next_step > int(time.time()) // 30 + 1:
        pytest.skip("clock edge")
    assert client.post("/admin/login/kod", data={"code": code}).status_code == 302
    assert client.get("/admin/").status_code == 200


def test_open_redirect_blocked(client, admin):
    client.post("/admin/login?next=https://evil.example", data={"username": "nils", "password": "correct horse battery"})
    with client.session_transaction() as s:
        assert s["pending_next"] is None


def test_member_search(admin_client, members):
    make_member("Åsa Öberg", ltu_id="asaobe-2")
    assert [m["name"] for m in admin_client.get("/admin/api/members?q=åsa").json] == ["Åsa Öberg"]
    assert [m["name"] for m in admin_client.get("/admin/api/members?q=OBE").json] == ["Åsa Öberg"]
    assert [m["name"] for m in admin_client.get("/admin/api/members?q=bert-").json] == ["Bert"]


def test_member_search_reports_status_on_date(admin_client):
    make_member("Late", paid_on=date(2026, 9, 5))
    assert admin_client.get("/admin/api/members?q=late&date=2026-09-01").json[0]["active"] is False
    assert admin_client.get("/admin/api/members?q=late&date=2026-09-08").json[0]["active"] is True


def test_points_preview(admin_client):
    r = admin_client.post("/admin/api/points-preview", json={"tables": [[0, 0, 0], [1, 0]]})
    assert r.json == {"tables": [[3, 2, 1], [2, 1]]}


def test_create_night_via_api(admin_client, period, members):
    a, b, c, *_ = members
    body = {"date": "2026-09-08", "period_id": period.id, "tables": [[{"member_id": a.id, "wipes": 1}, {"member_id": b.id}]]}
    r = admin_client.post("/admin/api/nights", json=body)
    assert r.status_code == 200 and r.json["ok"]
    r = admin_client.post(f"/admin/api/nights/{r.json['id']}", json=body | {"tables": [[{"member_id": c.id}, {"member_id": a.id}]]})
    assert r.status_code == 200
    assert admin_client.get(f"/admin/kvallar/{r.json['id']}").status_code == 200
    r = admin_client.post("/admin/api/nights", json=body)
    assert r.status_code == 400 and r.json["errors"]


def test_renew_now_makes_member_active(admin_client, period):
    m = make_member("Lapsed", paid_on=date(2025, 1, 1))
    r = admin_client.post(f"/admin/api/members/{m.id}/payments", json={"paid_on": "2026-09-08", "years": 1, "date": "2026-09-08"})
    assert r.status_code == 200 and r.json["active"] is True
    assert db.session.get(Member, m.id).is_active(date(2026, 9, 8))


def test_members_page_sorted_by_days_left(admin_client, app):
    make_member("Later", paid_on=date(2026, 9, 1))
    make_member("Sooner", paid_on=date(2026, 1, 1))
    r = admin_client.get("/admin/medlemmar?sort=utgang")
    assert r.status_code == 200
    assert r.text.index("Sooner") < r.text.index("Later")


def test_admin_pages_render(admin_client, period, members):
    for url in ["/admin/", "/admin/kvallar", "/admin/kvallar/ny", "/admin/medlemmar", f"/admin/medlemmar/{members[0].id}",
                "/admin/medlemmar/ny", "/admin/lp", "/admin/lp/ny", f"/admin/lp/{period.id}", "/admin/nyheter",
                "/admin/nyheter/ny", "/admin/logg"]:
        assert admin_client.get(url).status_code == 200, url


def test_member_create_and_payment_forms(admin_client):
    r = admin_client.post("/admin/medlemmar/ny", data={"name": "Ny Person", "ltu_id": "NYPERS-1", "joined_on": "2026-09-01", "paid_on": "2026-09-01", "years": "2"})
    assert r.status_code == 302
    m = db.session.query(Member).filter_by(ltu_id="nypers-1").one()
    assert m.status(date(2026, 9, 1)).expires_on == date(2028, 9, 1)
    r = admin_client.post("/admin/medlemmar/ny", data={"name": "Dup", "ltu_id": "nypers-1", "joined_on": "2026-09-01"})
    assert "används redan" in r.text


def test_period_overlap_rejected(admin_client, period):
    r = admin_client.post("/admin/lp/ny", data={"start_year": "2026", "lp": "2", "starts_on": "2026-10-01", "ends_on": "2026-12-01"})
    assert "överlappar" in r.text


def test_news_crud_and_markdown_is_sanitised(admin_client, client):
    r = admin_client.post("/admin/nyheter/ny", data={"title": "Hej", "body_md": "**fet** <script>alert(1)</script>", "action": "save"})
    assert r.status_code == 302
    page = client.get("/nyheter/1").text
    assert "<strong>fet</strong>" in page and "<script>alert" not in page

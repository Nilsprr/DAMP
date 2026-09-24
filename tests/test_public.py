import pytest

from damp import create_app

from .conftest import seat, write_files


@pytest.mark.parametrize("url", ["/", "/lp/lp1-26-27/", "/lp/lp4-25-26/", "/om/", "/nyheter/", "/nyheter/1/"])
def test_pages_render(client, url):
    assert client.get(url).status_code == 200


def test_front_page_shows_standings_and_lp_links(client):
    html = client.get("/lp/lp1-26-27/").get_data(as_text=True)
    assert "Anna" in html and "Topplista LP1 26/27" in html
    assert "2 bord · 5 spelare" in html
    assert '"full_name": "Cleo \\"Cleopatra\\" Carlsson"' in html or "Cleopatra" in html
    assert 'value="/lp/lp4-25-26/"' in html
    assert 'id="lp-data"' in html


@pytest.mark.parametrize("url", ["/lp/lp9-99-00/", "/nyheter/sida/1/", "/nyheter/sida/2/", "/nyheter/7/", "/admin/api-finns-inte/"])
def test_missing_pages_are_404(client, url):
    resp = client.get(url)
    assert resp.status_code == 404
    assert "Sidan finns inte" in resp.get_data(as_text=True)


@pytest.mark.parametrize("url", ["/", "/lp/lp1-26-27/", "/om/", "/nyheter/"])
def test_public_pages_are_get_only(client, url):
    assert client.post(url).status_code == 405


def test_invalid_data_shows_the_errors(data_dir, client):
    write_files(data_dir, {"tables/2026-09-08-1.json": {"players": [seat(1, 1)]}})
    resp = client.get("/")
    assert resp.status_code == 500
    assert "minst 2 spelare" in resp.get_data(as_text=True)


def test_footer_has_the_admin_padlock(client):
    html = client.get("/").get_data(as_text=True)
    assert 'data-admin-lock' in html and 'href="/admin/"' in html
    assert "/static/js/admin-lock.js" in html


def test_security_headers(client):
    resp = client.get("/")
    assert "script-src 'self'" in resp.headers["Content-Security-Policy"]
    assert resp.headers["X-Frame-Options"] == "DENY"


def test_admin_shells_render(client):
    for url in ["/admin/", "/admin/bord/", "/admin/bord/redigera/", "/admin/medlemmar/", "/admin/lp/", "/admin/manuella-poang/", "/admin/nyheter/", "/admin/historik/"]:
        html = client.get(url).get_data(as_text=True)
        assert 'type="module"' in html and "/static/admin/" in html, url
        assert 'name="robots" content="noindex"' in html


def test_published_app_has_no_admin_api(data_dir):
    client = create_app(data_dir, dev_admin=False).test_client()
    assert client.get("/admin/api/data").status_code == 404

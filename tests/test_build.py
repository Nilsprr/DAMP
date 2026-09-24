import json

import pytest

from damp.build import build, main
from damp.scoring import points_table
from damp.store import DataError

from .conftest import seat, write_files


def test_build_writes_every_page(data_dir, tmp_path):
    out = tmp_path / "dist"
    build(data_dir, out)
    for rel in [
        "index.html", "lp/lp1-26-27/index.html", "lp/lp4-25-26/index.html", "om/index.html", "nyheter/index.html",
        "nyheter/1/index.html", "404.html", "_headers", "admin/index.html", "admin/bord/index.html", "admin/bord/redigera/index.html", "admin/historik/index.html",
        "admin/medlemmar/index.html", "static/admin/core.js", "static/js/standings.js",
    ]:
        assert (out / rel).is_file(), rel
    assert "Anna" in (out / "index.html").read_text()
    assert "Sidan finns inte" in (out / "404.html").read_text()


def test_points_table_is_published(data_dir, tmp_path):
    out = tmp_path / "dist"
    build(data_dir, out)
    assert json.loads((out / "admin/poang.json").read_text()) == points_table()


def test_raw_data_is_never_published(data_dir, tmp_path):
    out = tmp_path / "dist"
    build(data_dir, out)
    published = [p.relative_to(out).as_posix() for p in out.rglob("*")]
    assert not any(p.endswith("members.json") or p.startswith("data") or p.startswith("tables") or p.startswith("history") for p in published)
    assert "annand-5" not in "".join(f.read_text(errors="ignore") for f in out.rglob("*.html"))  # LTU-ids stay private


def test_headers_file(data_dir, tmp_path):
    out = tmp_path / "dist"
    build(data_dir, out)
    headers = (out / "_headers").read_text()
    assert "Content-Security-Policy:" in headers and "/admin/*\n  Cache-Control: no-store" in headers


def test_invalid_data_is_not_built(data_dir, tmp_path, capsys):
    write_files(data_dir, {"tables/2026-09-08-1.json": {"players": [seat(1, 1)]}})
    with pytest.raises(DataError):
        build(data_dir, tmp_path / "dist")
    assert main(["--data", str(data_dir), "--out", str(tmp_path / "dist")]) == 1
    assert "minst 2 spelare" in capsys.readouterr().err
    assert not (tmp_path / "dist").exists()

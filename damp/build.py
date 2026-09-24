"""Render the whole site to static files for Cloudflare Pages.

    uv run python -m damp.build [--data data] [--out dist]

Refuses to build (exit 1) if data/ is invalid, so a bad save never reaches the
live site. Output: every public page and admin shell as <url>/index.html,
404.html, static/, admin/poang.json and _headers. data/ itself is never copied.
"""

import argparse
import shutil
import sys
from pathlib import Path

from . import ROOT, SECURITY_HEADERS, create_app
from .store import DataError, load


def _urls(app, store) -> list[str]:
    urls = ["/", "/om/", "/nyheter/", "/admin/poang.json"]
    urls += [f"/lp/{p.id}/" for p in store.periods]
    pages = max(1, -(-len(store.news) // 10))
    urls += [f"/nyheter/sida/{n}/" for n in range(2, pages + 1)]
    urls += [f"/nyheter/{post.id}/" for post in store.news]
    urls += [rule.rule for rule in app.url_map.iter_rules() if rule.endpoint.startswith("admin.") and not rule.arguments]
    return sorted(set(urls))


def _target(out: Path, url: str) -> Path:
    rel = url.lstrip("/")
    return out / rel / "index.html" if url.endswith("/") else out / rel


def headers_file() -> str:
    lines = ["/*"] + [f"  {k}: {v}" for k, v in SECURITY_HEADERS.items()]
    lines += ["", "/admin/*", "  Cache-Control: no-store", "  X-Robots-Tag: noindex", ""]
    return "\n".join(lines)


def build(data_dir: Path, out: Path) -> list[str]:
    """Build the site into `out` (replacing it). Returns the URLs rendered. Raises DataError."""
    store = load(data_dir)
    app = create_app(data_dir, dev_admin=False)
    client = app.test_client()

    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    urls = _urls(app, store)
    for url in urls:
        resp = client.get(url)
        if resp.status_code != 200:
            raise RuntimeError(f"{url} gav {resp.status_code}")
        target = _target(out, url)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(resp.data)

    resp = client.get("/finns-inte/")
    (out / "404.html").write_bytes(resp.data)
    shutil.copytree(Path(app.static_folder), out / "static")
    (out / "_headers").write_text(headers_file(), encoding="utf-8")
    return urls


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Bygg DAMP-sidan till statiska filer.")
    parser.add_argument("--data", type=Path, default=ROOT / "data")
    parser.add_argument("--out", type=Path, default=ROOT / "dist")
    args = parser.parse_args(argv)
    try:
        urls = build(args.data, args.out)
    except DataError as e:
        print("Datan i data/ är ogiltig, sidan byggdes inte:", file=sys.stderr)
        for err in e.errors:
            print(f"  - {err}", file=sys.stderr)
        return 1
    print(f"Byggde {len(urls)} sidor till {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

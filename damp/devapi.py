"""Local stand-in for the Cloudflare function: the admin API, reading and writing data/ directly.

Only registered for local development (create_app(dev_admin=True)); never part of
the published site, and there is no login. Same endpoints and responses as
functions/admin/api/[[path]].js:

    GET  /admin/api/data     -> {version, files: {path: json}, user: {email, dev}}
    POST /admin/api/save     {base, message, lps, details, changes: {path: json | null}} -> {version, rebased}
                             409 {error: "conflict", paths} if a changed file was modified since `base`
                             The change is logged in data/history/ (see damp/history.py).
    GET  /admin/api/history  -> {events: [...newest first]}

Unlike production, a save is also checked with store.from_files (422 with the
errors), so data bugs show up here instead of as a failed build.
"""

import hashlib
import json
from collections import OrderedDict

from flask import Blueprint, current_app, jsonify, request

from . import history
from .store import DATA_PATH, DataError, from_files, write_json

bp = Blueprint("devapi", __name__, url_prefix="/admin/api")

MAX_SNAPSHOTS = 50
# version -> {path: content hash}; lets a save based on an older version find what changed since.
_snapshots: "OrderedDict[str, dict[str, str]]" = OrderedDict()


def _state() -> tuple[str, dict[str, str], dict[str, str]]:
    """(version, {path: text}, {path: hash}) of the data files right now (history excluded)."""
    data_dir = current_app.config["DATA_DIR"]
    texts = {}
    for path in sorted([*data_dir.glob("*.json"), *data_dir.glob("tables/*.json")]):
        rel = path.relative_to(data_dir).as_posix()
        if DATA_PATH.match(rel):
            texts[rel] = path.read_text(encoding="utf-8")
    hashes = {p: hashlib.sha1(t.encode()).hexdigest() for p, t in texts.items()}
    version = hashlib.sha1(json.dumps(sorted(hashes.items())).encode()).hexdigest()
    _snapshots[version] = hashes
    _snapshots.move_to_end(version)
    while len(_snapshots) > MAX_SNAPSHOTS:
        _snapshots.popitem(last=False)
    return version, texts, hashes


def _parse(texts: dict[str, str]) -> dict:
    return {p: json.loads(t) for p, t in texts.items()}


@bp.get("/data")
def data():
    version, texts, _ = _state()
    try:
        files = _parse(texts)
    except ValueError as e:
        return jsonify(error=f"Ogiltig JSON i data/: {e}"), 500
    return jsonify(version=version, files=files, user={"email": "lokal utveckling", "dev": True})


@bp.post("/save")
def save():
    body = request.get_json(silent=True)  # None unless Content-Type is JSON, so plain form posts can't get here
    if not isinstance(body, dict) or not isinstance(body.get("changes"), dict) or not body["changes"]:
        return jsonify(error="Förväntade {base, message, changes}."), 400
    changes = body["changes"]
    bad = [p for p in changes if not DATA_PATH.match(p)]
    if bad:
        return jsonify(error=f"Otillåten sökväg: {', '.join(bad)}"), 400
    if any(c is not None and not isinstance(c, (dict, list)) for c in changes.values()):
        return jsonify(error="Filinnehåll ska vara ett objekt eller en lista."), 400
    try:
        event = history.make_event(body.get("message"), body.get("lps", []), body.get("details", []), by=history.local_author())
    except ValueError as e:
        return jsonify(error=str(e)), 400

    version, texts, hashes = _state()
    rebased = body.get("base") != version
    if rebased:
        before = _snapshots.get(body.get("base"))
        conflicts = sorted(p for p in changes if before is None or before.get(p) != hashes.get(p))
        if conflicts:
            return jsonify(error="conflict", paths=conflicts), 409

    files = _parse(texts)
    for p, content in changes.items():
        if content is None:
            files.pop(p, None)
        else:
            files[p] = content
    try:
        from_files(files)
    except DataError as e:
        return jsonify(error="Ogiltig data.", errors=e.errors), 422

    data_dir = current_app.config["DATA_DIR"]
    for p, content in changes.items():
        if content is None:
            (data_dir / p).unlink(missing_ok=True)
        else:
            write_json(data_dir / p, content)
    history.append(data_dir, event)
    # rebased: other files changed since `base` too, so the client's copy of them is stale.
    return jsonify(version=_state()[0], rebased=rebased)


@bp.get("/history")
def history_events():
    return jsonify(events=history.read_all(current_app.config["DATA_DIR"]))

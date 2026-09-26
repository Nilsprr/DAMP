"""The change log: data/history/<YYYY-MM>.json, one list of events per month.

Every save through the admin and every data CLI command appends an event, in the
same commit as the change it describes:

    {"at": "2026-09-24T08:38:00Z", "by": "nilsalomonsson@gmail.com",
     "message": "Nytt bord: tis 22 sep 2026, bord 2", "lps": ["lp1-26-27"],
     "details": ["1. Harald Malmström: 8 p", "2. Ludvig Ulander Jonsson: 6 p"]}

`lps` are the LPs the change touches (empty for members and news), which lets the
history page filter on an LP. The server appends events (the Cloudflare function in
production, devapi.py locally), so admins can't edit or remove them, and `by` is the
logged-in address. The site build ignores these files.

The history page also lists the commits made outside the admin (own_commits), read
straight from git, so those need no events.

The same rules for an incoming event, and for which commits to list, are in
functions/admin/api/[[path]].js.
"""

import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from .store import write_json

HISTORY_DIR = "history"
LP_ID = re.compile(r"^lp[1-4]-\d{2}-\d{2}$")
MAX_MESSAGE = 200
MAX_DETAILS = 100
MAX_DETAIL = 300
ADMIN_TRAILER = "Via DAMP-admin av "  # starts the last line of every commit the admin makes


def make_event(message, lps=(), details=(), *, by: str, at: datetime | None = None) -> dict:
    """A cleaned-up event. Raises ValueError for input that doesn't fit the format."""
    if not isinstance(message, str) or not message.strip():
        raise ValueError("Händelsen saknar beskrivning.")
    if not isinstance(lps, (list, tuple)) or not all(isinstance(lp, str) and LP_ID.match(lp) for lp in lps) or len(lps) > 10:
        raise ValueError("Ogiltiga LP i händelsen.")
    if not isinstance(details, (list, tuple)) or len(details) > MAX_DETAILS or not all(isinstance(d, str) for d in details):
        raise ValueError("Ogiltiga detaljer i händelsen.")
    at = (at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    event = {
        "at": at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "by": by,
        "message": " ".join(message.split())[:MAX_MESSAGE],
        "lps": sorted(set(lps)),
    }
    if details:
        event["details"] = [" ".join(d.split())[:MAX_DETAIL] for d in details]
    return event


def path_for(event: dict) -> str:
    return f"{HISTORY_DIR}/{event['at'][:7]}.json"


def append(data_dir: Path, event: dict) -> str:
    """Add `event` to its month's file. Returns the file's path relative to data_dir."""
    rel = path_for(event)
    path = Path(data_dir) / rel
    events = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    events.append(event)
    write_json(path, events)
    return rel


def read_all(data_dir: Path) -> list[dict]:
    """Every event, newest first (events in the same second: last appended first)."""
    events = []
    for path in sorted((Path(data_dir) / HISTORY_DIR).glob("*.json")):
        events.extend(json.loads(path.read_text(encoding="utf-8")))
    return sorted(reversed(events), key=lambda e: e["at"], reverse=True)


def own_commits(repo_dir: Path) -> list[dict]:
    """The branch's commits that weren't made through the admin, newest first, shaped like
    events plus `sha`: the subject is the message and the body's lines are the details.

    Admin commits end with ADMIN_TRAILER and are in the log already; merges are left out.
    Empty outside a git repository.
    """
    try:
        out = subprocess.run(
            ["git", "-C", str(repo_dir), "log", "--no-merges", "-z", "--format=%H%x1f%aI%x1f%ae%x1f%an%x1f%B"],
            capture_output=True, encoding="utf-8", errors="replace", timeout=10, check=True,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    commits = []
    for record in filter(None, out.split("\0")):
        sha, at, email, name, message = record.split("\x1f", 4)
        lines = message.strip().splitlines()
        if any(line.startswith(ADMIN_TRAILER) for line in lines):
            continue
        subject = lines[0] if lines and lines[0].strip() else "(inget meddelande)"
        body = [line for line in lines[1:] if line.strip()][:MAX_DETAILS]
        commits.append({"sha": sha, **make_event(subject, details=body, by=email or name, at=datetime.fromisoformat(at))})
    return commits


def local_author() -> str:
    """Who is making a change from this computer (git's user.email), for CLI events."""
    try:
        email = subprocess.run(["git", "config", "user.email"], capture_output=True, text=True, timeout=5).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        email = ""
    return email or "lokalt"

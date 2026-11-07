"""Fast start-up cache for per-game achievement counts.

Parsing every schema and stats file on every launch is wasteful. We key each
entry off (name, size, mtime) of the two source files, so Steam invalidates
the cache naturally when it touches them.
"""

import json
from pathlib import Path

from taos.config import PROGRESS_CACHE_FILE

Signature = tuple[tuple[str, int, int], ...]


def file_signature(paths):
    parts = []
    for path in paths:
        if path is None:
            continue
        try:
            stat = path.stat()
            parts.append((path.name, stat.st_size, stat.st_mtime_ns))
        except OSError:
            parts.append((path.name, -1, -1))
    return tuple(parts)


class ProgressCache:
    def __init__(self, path: Path = PROGRESS_CACHE_FILE):
        self.path = Path(path)
        self.games: dict = {}
        self._dirty = False
        self._load()

    def _load(self):
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            games = raw.get("games", {})
            if isinstance(games, dict):
                self.games = games
        except (OSError, ValueError, TypeError):
            self.games = {}

    def get(self, app_id: int, signature: Signature):
        entry = self.games.get(str(app_id))
        if not isinstance(entry, dict):
            return None
        if entry.get("sig") != [list(part) for part in signature]:
            return None
        try:
            return {
                "total": int(entry["total"]),
                "unlocked": int(entry["unlocked"]),
            }
        except (KeyError, TypeError, ValueError):
            return None

    def put(self, app_id: int, signature: Signature, total: int, unlocked: int):
        self.games[str(app_id)] = {
            "sig": [list(part) for part in signature],
            "total": int(total),
            "unlocked": int(unlocked),
        }
        self._dirty = True

    def save(self):
        if not self._dirty:
            return
        try:
            self.path.write_text(
                json.dumps({"version": 1, "games": self.games}, ensure_ascii=False),
                encoding="utf-8",
            )
            self._dirty = False
        except OSError:
            pass

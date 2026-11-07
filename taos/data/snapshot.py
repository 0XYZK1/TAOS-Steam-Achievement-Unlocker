"""Original achievement backup.

The first scan writes the per-game state to disk. From then on the file is
append-only: unlocking, locking or toggling achievements must never touch it.
The only exception is a legacy file from the old 0% reader, which was wrong
for every game and gets rebuilt once.
"""

import json
import time
from contextlib import suppress
from pathlib import Path

from taos.config import SNAPSHOT_VERSION


class SnapshotStore:
    def __init__(self, path: Path, steam_id64: str = ""):
        self.path = Path(path)
        self.steam_id64 = steam_id64 or ""
        self.data: dict[str, dict[str, bool]] = {}
        self.created_at = 0
        self.account_mismatch = False
        self.last_save_error = ""
        self.defer_writes = False
        self._dirty = False
        self._legacy = False
        self._load()

    def _load(self):
        if not self.path.exists():
            return

        with suppress(OSError):
            self.created_at = int(self.path.stat().st_mtime)

        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if not isinstance(raw, dict):
            return

        meta = raw.pop("_meta", {})
        if not isinstance(meta, dict):
            meta = {}

        version = int(meta.get("version", 1) or 1)
        created = meta.get("created_at")
        if created:
            with suppress(TypeError, ValueError):
                self.created_at = int(created)
        meta_account = str(meta.get("steam_id64") or "")
        if meta_account and self.steam_id64 and meta_account != self.steam_id64:
            self.account_mismatch = True

        for app_id, states in raw.items():
            if str(app_id).isdigit() and isinstance(states, dict):
                self.data[str(app_id)] = {str(k): bool(v) for k, v in states.items()}

        # Only v1 can be completely bogus. A v2 file with 0% everywhere might
        # be exactly what the user asked for, so leave it alone.
        if (
            version < SNAPSHOT_VERSION
            and len(self.data) >= 5
            and not any(any(s.values()) for s in self.data.values())
        ):
            self._backup_broken()
            self.data = {}
            self.created_at = int(time.time())

        self._legacy = version < SNAPSHOT_VERSION

    def _backup_broken(self):
        target = self.path.with_name(f"{self.path.stem}.broken-{int(time.time())}.json")
        with suppress(OSError):
            self.path.replace(target)

    def save(self):
        if not self.created_at:
            self.created_at = int(time.time())

        payload = {
            "_meta": {
                "version": SNAPSHOT_VERSION,
                "created_at": self.created_at,
                "steam_id64": self.steam_id64,
            }
        }
        payload.update(self.data)

        try:
            self.path.write_text(
                json.dumps(payload, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            self._dirty = False
            self.last_save_error = ""
        except OSError as exc:
            self.last_save_error = str(exc)

    def finalize_repair(self):
        self._legacy = False
        if self._dirty:
            self.save()

    def __len__(self):
        return len(self.data)

    def get(self, app_id: int) -> dict[str, bool]:
        return dict(self.data.get(str(app_id), {}))

    def needs_record(self, app_id: int) -> bool:
        key = str(app_id)
        if key not in self.data:
            return True
        # Empty entries from the old reader are worth another look.
        return self._legacy and not any(self.data[key].values())

    def record_if_new(self, app_id: int, states: dict[str, bool], *, authoritative: bool):
        if not authoritative or not states or self.account_mismatch:
            return

        key = str(app_id)
        fresh = {str(k): bool(v) for k, v in states.items()}
        current = self.data.get(key)

        if current is None:
            self.data[key] = fresh
            self._dirty = True
            if not self.defer_writes:
                self.save()
            return

        # Repair an old all-zero entry only when we now have real data.
        if self._legacy and not any(current.values()) and any(fresh.values()):
            self.data[key] = fresh
            self._dirty = True
            if not self.defer_writes:
                self.save()

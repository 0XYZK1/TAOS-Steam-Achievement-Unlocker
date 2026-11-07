"""Small JSON cache for app ids and their display names."""

import json
from pathlib import Path


class AppNamesStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.data: dict[int, str] = {}
        self._load()

    def _load(self):
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            self.data = {int(k): str(v) for k, v in raw.items()}
        except (OSError, ValueError, TypeError):
            self.data = {}

    def get(self, app_id: int, default: str = "") -> str:
        return self.data.get(app_id, default)

    def set(self, app_id: int, name: str):
        if name:
            self.data[app_id] = name

    def save(self):
        try:
            self.path.write_text(
                json.dumps(self.data, ensure_ascii=False),
                encoding="utf-8",
            )
        except OSError:
            pass

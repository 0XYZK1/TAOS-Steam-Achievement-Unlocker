import os
import sys
from pathlib import Path

FROZEN = bool(getattr(sys, "frozen", False))

BUNDLE_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
APP_DIR = Path(sys.executable).resolve().parent if FROZEN else BUNDLE_DIR
DATA_DIR = (
    Path(os.environ.get("LOCALAPPDATA", Path.home())) / "TAOS"
    if FROZEN
    else BUNDLE_DIR
)

ENTRYPOINT = APP_DIR / "main.py"

SNAPSHOT_FILE = DATA_DIR / "taos_initial_snapshot.json"
APPNAMES_CACHE_FILE = DATA_DIR / "taos_appnames_cache.json"
PROGRESS_CACHE_FILE = DATA_DIR / "taos_progress_cache.json"

# Steam internals, runtimes and test apps. Not worth showing.
EXCLUDED_APPIDS = frozenset({
    228980, 228981, 228982, 228983, 228984, 228985, 228990,
    250820, 1070560, 1391110, 1493710, 769, 7, 8,
})

STEAM_ID64_BASE = 76561197960265728

HTTP_TIMEOUT_SHORT = 5
HTTP_TIMEOUT_LONG = 8

SNAPSHOT_VERSION = 2


def snapshot_file(steam_id64: str = "") -> Path:
    """One backup per account. Mixing accounts would get ugly fast."""
    if steam_id64:
        return DATA_DIR / f"taos_initial_snapshot_{steam_id64}.json"
    return SNAPSHOT_FILE

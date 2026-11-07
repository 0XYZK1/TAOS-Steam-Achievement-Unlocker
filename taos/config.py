from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENTRYPOINT = ROOT / "main.py"

SNAPSHOT_FILE = ROOT / "taos_initial_snapshot.json"
APPNAMES_CACHE_FILE = ROOT / "taos_appnames_cache.json"
PROGRESS_CACHE_FILE = ROOT / "taos_progress_cache.json"

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
        return ROOT / f"taos_initial_snapshot_{steam_id64}.json"
    return SNAPSHOT_FILE

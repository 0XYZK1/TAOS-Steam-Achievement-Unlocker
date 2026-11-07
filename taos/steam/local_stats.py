"""Read Steam's local achievement cache.

Two details in here are easy to get wrong, and both were responsible for the
old "everything is 0%" bug:

* stats live under the top-level ``cache`` key, not under the app id;
* ``data`` is a signed 32-bit bitmask, so -2 means bits 1..31 are set.
"""

from pathlib import Path

import vdf

BitMapping = dict[tuple[int, int], str]


def stats_dir(steam_path: Path) -> Path:
    return steam_path / "appcache" / "stats"


def schema_path(steam_path: Path | None, app_id: int) -> Path | None:
    if not steam_path:
        return None
    return stats_dir(steam_path) / f"UserGameStatsSchema_{app_id}.bin"


def find_user_stats_file(
    steam_path: Path | None,
    account_id3: str,
    app_id: int,
) -> Path | None:
    if not steam_path:
        return None

    folder = stats_dir(steam_path)
    if not folder.exists():
        return None

    if account_id3:
        direct = folder / f"UserGameStats_{account_id3}_{app_id}.bin"
        if direct.exists():
            return direct

    matches = sorted(folder.glob(f"UserGameStats_*_{app_id}.bin"))
    return matches[0] if matches else None


def _icon(app_id: int, name: str) -> str:
    if not name:
        return ""
    return (
        "https://steamcdn-a.akamaihd.net/steamcommunity/public/images/apps/"
        f"{app_id}/{name}"
    )


def _localized(value, fallback: str = "") -> str:
    if isinstance(value, dict):
        return value.get("english") or next(
            (item for item in value.values() if item), fallback
        )
    return str(value) if value else fallback


def parse_schema(steam_path: Path | None, app_id: int) -> tuple[list[dict], BitMapping]:
    path = schema_path(steam_path, app_id)
    if path is None or not path.exists():
        return [], {}

    try:
        data = vdf.binary_loads(path.read_bytes())
    except Exception:
        return [], {}

    stats = data.get(str(app_id), {}).get("stats", {})
    if not isinstance(stats, dict):
        return [], {}

    achievements: list[dict] = []
    bit_mapping: BitMapping = {}

    for stat_id, stat in stats.items():
        if not isinstance(stat, dict):
            continue

        bits = stat.get("bits")
        if not isinstance(bits, dict):
            continue

        for bit_id, bit in bits.items():
            if not isinstance(bit, dict):
                continue

            api_name = str(bit.get("name") or f"ACH_{bit_id}")
            display = bit.get("display")
            if not isinstance(display, dict):
                display = {}

            icon = str(display.get("icon") or "")
            gray = str(display.get("icon_gray") or icon)

            if str(stat_id).isdigit() and str(bit_id).isdigit():
                bit_mapping[(int(stat_id), int(bit_id))] = api_name

            achievements.append({
                "id": api_name,
                "title": _localized(display.get("name"), api_name),
                "description": _localized(display.get("desc")),
                "icon": _icon(app_id, icon),
                "icon_gray": _icon(app_id, gray) or _icon(app_id, icon),
                "hidden": str(display.get("hidden", "0")) == "1",
                "unlocked": False,
            })

    return achievements, bit_mapping


def _stats_block(data: dict, app_id: int) -> dict:
    cache = data.get("cache")
    if isinstance(cache, dict):
        return cache

    app = data.get(str(app_id))
    if isinstance(app, dict):
        for key in ("stats", "cache"):
            if isinstance(app.get(key), dict):
                return app[key]

    legacy = data.get("stats")
    if isinstance(legacy, dict):
        return legacy

    if any(str(key).isdigit() for key in data):
        return data
    return {}


def _unsigned(value: int, bit: int) -> int:
    if value >= 0:
        return value
    width = max(32, bit + 1)
    return value & ((1 << width) - 1)


def read_user_states(
    steam_path: Path | None,
    account_id3: str,
    app_id: int,
    bit_mapping: BitMapping,
) -> tuple[dict[str, bool], bool]:
    """Returns the states and whether a stats file was actually found."""
    states = {name: False for name in bit_mapping.values()}
    if not bit_mapping:
        return states, False

    path = find_user_stats_file(steam_path, account_id3, app_id)
    if path is None:
        return states, False

    try:
        data = vdf.binary_loads(path.read_bytes())
    except Exception:
        return states, False

    block = _stats_block(data, app_id)
    if not block:
        return states, False

    for (stat_id, bit), api_name in bit_mapping.items():
        entry = block.get(str(stat_id))
        value = entry.get("data", entry.get("value", 0)) if isinstance(entry, dict) else entry
        if isinstance(value, int):
            states[api_name] = bool((_unsigned(value, bit) >> bit) & 1)

    return states, True

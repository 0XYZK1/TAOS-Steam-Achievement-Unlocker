"""Out-of-process Steamworks worker.

Steamworks can only be initialised once per process, and only for one app id.
Each game therefore gets its own short-lived process.
"""

import json
import os
import sys
from contextlib import suppress
from pathlib import Path

from taos.steam.live import LiveSteamStats, SteamApiError, find_steam_api_dll


def _dll_path() -> Path | None:
    explicit = os.environ.get("TAOS_STEAM_API_DLL", "").strip()
    if explicit and Path(explicit).exists():
        return Path(explicit)

    root = Path(__file__).resolve().parent.parent
    steam = os.environ.get("TAOS_STEAM_PATH", "").strip()
    return find_steam_api_dll(root, Path(steam) if steam else None)


def _apply(client: LiveSteamStats, mapping: dict[str, bool]):
    failed = []
    for achievement, unlock in mapping.items():
        ok = (
            client.set_achievement(achievement)
            if unlock
            else client.clear_achievement(achievement)
        )
        if not ok:
            failed.append(achievement)

    stored = client.store_stats()
    return failed, stored


def _result(failed: list[str], stored: bool, data):
    ok = stored and not failed
    if ok:
        message = ""
    elif failed:
        message = f"{len(failed)} Achievement(s) konnten nicht gesetzt werden."
    else:
        message = "Steam hat die Änderung nicht gespeichert."
    return {
        "status": "ok" if ok else "error",
        "mode": "LIVE",
        "message": message,
        "data": data,
        "stored": stored,
        "failed": failed,
    }


def run_steamworks_worker(app_id: int, action: str, payload: str):
    client = None
    result = {"status": "error", "message": "Unbekannter Fehler", "data": {}}

    try:
        targets = json.loads(payload) if payload else {}
        dll = _dll_path()
        if dll is None:
            raise SteamApiError("Keine steam_api64.dll gefunden.")

        client = LiveSteamStats(dll)
        client.initialize(app_id)

        if action == "get_states":
            states = {
                achievement: client.get_achievement(achievement)
                for achievement in targets
            }
            result = {"status": "ok", "mode": "LIVE", "data": states}

        elif action == "set_state":
            achievement = targets["id"]
            unlock = bool(targets["unlock"])
            failed, stored = _apply(client, {achievement: unlock})
            result = _result(failed, stored, {achievement: unlock})

        elif action == "set_bulk":
            unlock = bool(targets["unlock"])
            mapping = {
                achievement: unlock
                for achievement in targets.get("achievements", [])
            }
            failed, stored = _apply(client, mapping)
            result = _result(failed, stored, mapping)

        elif action == "set_exact_map":
            mapping = {
                achievement: bool(unlock)
                for achievement, unlock in targets.get("state_map", {}).items()
            }
            failed, stored = _apply(client, mapping)
            result = _result(failed, stored, mapping)

        else:
            result = {"status": "error", "message": f"Unbekannte Aktion: {action}"}

    except SteamApiError as exc:
        result = {"status": "error", "mode": "LIVE", "message": str(exc)}
    except Exception as exc:
        result = {
            "status": "error",
            "mode": "LIVE",
            "message": f"{type(exc).__name__}: {exc}",
        }
    finally:
        if client:
            client.close()
        with suppress(OSError):
            Path("steam_appid.txt").unlink(missing_ok=True)

    ipc_file = os.environ.get("TAOS_IPC_FILE")
    if ipc_file:
        with suppress(OSError):
            Path(ipc_file).write_text(json.dumps(result), encoding="utf-8")
    else:
        payload = "TAOS_IPC_START" + json.dumps(result) + "TAOS_IPC_END"
    os.write(1, payload.encode("utf-8"))
    sys.exit(0)

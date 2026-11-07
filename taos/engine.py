"""Game library, achievement state and the live write path."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from contextlib import suppress
from pathlib import Path

import vdf

from taos.config import (
    APPNAMES_CACHE_FILE,
    APP_DIR,
    DATA_DIR,
    ENTRYPOINT,
    PROGRESS_CACHE_FILE,
    SNAPSHOT_FILE,
    snapshot_file,
)
from taos.data.appnames import AppNamesStore
from taos.data.progress import ProgressCache, file_signature
from taos.data.snapshot import SnapshotStore
from taos.steam import local_stats, web_api
from taos.steam.library_scanner import LibraryScanner
from taos.steam.live import find_steam_api_dll
from taos.steam.paths import detect_active_user, find_steam_path, is_steam_running


class SteamLibraryEngine:
    def __init__(self, base_dir: Path | None = None):
        self.base_dir = Path(base_dir) if base_dir else APP_DIR
        self.data_dir = DATA_DIR
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.steam_path = find_steam_path()

        self.games_cache: dict[int, dict] = {}
        self.achievements_cache: dict[int, list[dict]] = {}
        self.current_states: dict[int, dict[str, bool]] = {}
        self.installed_app_ids: set[int] = set()

        self.app_names = AppNamesStore(APPNAMES_CACHE_FILE)
        self.progress_cache = ProgressCache(PROGRESS_CACHE_FILE)

        self.steam_id64, self.account_id3, self.persona_name = detect_active_user(
            self.steam_path
        )

        self.snapshot_path = snapshot_file(self.steam_id64)
        self._move_old_snapshot()
        self.snapshot = SnapshotStore(self.snapshot_path, self.steam_id64)

        self.steam_api_dll = find_steam_api_dll(self.base_dir, self.steam_path)
        self.live_mode_available = self.steam_api_dll is not None
        self.steam_running = is_steam_running()
        self.live_error = ""

        self._worker_lock = threading.Lock()
        self._scanner = LibraryScanner(self)

    def _move_old_snapshot(self):
        """Older builds used one global file. Adopt it for the current user."""
        if not self.steam_id64 or self.snapshot_path == SNAPSHOT_FILE:
            return
        if self.snapshot_path.exists() or not SNAPSHOT_FILE.exists():
            return

        owner = ""
        try:
            raw = json.loads(SNAPSHOT_FILE.read_text(encoding="utf-8"))
            meta = raw.get("_meta", {})
            if isinstance(meta, dict):
                owner = str(meta.get("steam_id64") or "")
        except (OSError, ValueError, TypeError):
            pass

        if owner and owner != self.steam_id64:
            return

        try:
            shutil.move(str(SNAPSHOT_FILE), str(self.snapshot_path))
        except OSError:
            try:
                shutil.copy2(SNAPSHOT_FILE, self.snapshot_path)
            except OSError:
                pass

    def scan_local_library(self, api_key: str = "") -> list[dict]:
        self.games_cache.clear()
        self.installed_app_ids = self._scanner.scan(api_key)
        self.app_names.save()

        self.snapshot.defer_writes = True
        try:
            for app_id in self.games_cache:
                self._scan_progress(app_id)
        finally:
            self.snapshot.defer_writes = False

        self.progress_cache.save()
        self.snapshot.finalize_repair()
        return self.sorted_games()

    def sorted_games(self) -> list[dict]:
        return sorted(
            self.games_cache.values(),
            key=lambda game: (
                game["name"].startswith("AppID //"),
                game["name"].lower(),
            ),
        )

    def register_game(self, app_id: int, name: str, installed: bool):
        name = name.strip() if name else self.app_names.get(app_id, f"AppID // {app_id}")
        image = (
            "https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/"
            f"{app_id}/header.jpg"
        )

        if app_id not in self.games_cache:
            self.games_cache[app_id] = {
                "app_id": app_id,
                "name": name,
                "installed": installed,
                "image": image,
                "achievements_loaded": False,
                "total_ach": 0,
                "unlocked_ach": 0,
            }
            return

        game = self.games_cache[app_id]
        game["installed"] = game["installed"] or installed
        if name and not name.startswith("AppID //"):
            game["name"] = name

    def read_schema_game_name(self, bin_file: Path, app_id: int) -> str:
        try:
            data = vdf.binary_loads(bin_file.read_bytes())
            name = data.get(str(app_id), {}).get("gamename", "")
        except Exception:
            return ""

        if name and not str(name).startswith("SteamWinApp"):
            return str(name)
        return ""

    def _scan_progress(self, app_id: int):
        schema = local_stats.schema_path(self.steam_path, app_id)
        if schema is None or not schema.exists():
            return

        stats_file = local_stats.find_user_stats_file(
            self.steam_path, self.account_id3, app_id
        )
        signature = file_signature([schema, stats_file])

        session = self.current_states.get(app_id) or {}
        cached = self.progress_cache.get(app_id, signature)
        if cached and not session and not self.snapshot.needs_record(app_id):
            self._set_progress(app_id, cached["total"], cached["unlocked"], True)
            return

        achievements, mapping = local_stats.parse_schema(self.steam_path, app_id)
        if not achievements:
            return

        states, found = local_stats.read_user_states(
            self.steam_path, self.account_id3, app_id, mapping
        )
        if not found:
            # No stats file means "unknown", not "0%".
            return

        self.snapshot.record_if_new(app_id, states, authoritative=True)

        visible = session or states
        if not session:
            self.current_states[app_id] = states

        total = len(achievements)
        unlocked = sum(1 for achievement in achievements if visible.get(achievement["id"]))
        self._set_progress(app_id, total, unlocked, True)

        local_unlocked = sum(
            1 for achievement in achievements if states.get(achievement["id"])
        )
        self.progress_cache.put(app_id, signature, total, local_unlocked)

    def _set_progress(self, app_id: int, total: int, unlocked: int, loaded: bool):
        game = self.games_cache.get(app_id)
        if not game:
            return
        game["total_ach"] = int(total)
        game["unlocked_ach"] = int(unlocked)
        game["achievements_loaded"] = bool(loaded)

    def get_achievements_for_game(
        self,
        app_id: int,
        api_key: str = "",
        read_states: bool = True,
        force_refresh: bool = False,
    ) -> list[dict]:
        schema, mapping = local_stats.parse_schema(self.steam_path, app_id)
        states: dict[str, bool] = {}
        authoritative = False

        if not schema:
            if api_key:
                schema = web_api.fetch_schema(app_id, api_key)
            if not schema:
                schema, states = web_api.fetch_community_achievements(
                    app_id, self.steam_id64
                )
                authoritative = bool(states)
                if states:
                    self.current_states[app_id] = dict(states)

        if schema and read_states:
            ids = [achievement["id"] for achievement in schema]
            result = self._call_worker(app_id, "get_states", ids)
            live = result.get("data") if result.get("status") == "ok" else None

            if result.get("status") == "error":
                self.live_error = result.get("message", "Live-Abfrage fehlgeschlagen")

            if isinstance(live, dict) and live:
                states = {str(key): bool(value) for key, value in live.items()}
                authoritative = True
                self.live_mode_available = True
                self.live_error = ""
            else:
                if not states:
                    session = None if force_refresh else self.current_states.get(app_id)
                    if session:
                        states = dict(session)
                    else:
                        local, found = local_stats.read_user_states(
                            self.steam_path, self.account_id3, app_id, mapping
                        )
                        states = local
                        authoritative = found

                    if not authoritative:
                        online = web_api.fetch_player_states(
                            app_id, api_key, self.steam_id64
                        )
                        if not online:
                            _, online = web_api.fetch_community_achievements(
                                app_id, self.steam_id64
                            )
                        if online:
                            states = dict(online)
                            authoritative = True

        if authoritative:
            self.current_states[app_id] = dict(states)
            self.snapshot.record_if_new(app_id, states, authoritative=True)

        unlocked = 0
        for achievement in schema:
            achievement["unlocked"] = bool(states.get(achievement["id"], False))
            if achievement["unlocked"]:
                unlocked += 1

        self.achievements_cache[app_id] = schema
        if app_id in self.games_cache:
            game = self.games_cache[app_id]
            game["total_ach"] = len(schema)
            game["unlocked_ach"] = unlocked
            game["achievements_loaded"] = bool(schema)

        return schema

    def _ensure_snapshot(self, app_id: int, api_key: str = "") -> bool:
        if self.snapshot.account_mismatch or self.snapshot.last_save_error:
            return False
        if not self.snapshot.needs_record(app_id):
            return bool(self.snapshot.get(app_id))

        achievements = self.get_achievements_for_game(
            app_id,
            api_key,
            read_states=True,
            force_refresh=True,
        )
        if self.snapshot.last_save_error:
            return False
        return not achievements or bool(self.snapshot.get(app_id))

    def add_game_manually(self, query: str, api_key: str = ""):
        query = query.strip()
        if not query:
            return None

        if query.isdigit():
            app_id, name = int(query), ""
        else:
            app_id, name = web_api.search_store_game(query)

        if app_id <= 0:
            return None

        if not name:
            name = web_api.fetch_store_name(app_id) or f"AppID // {app_id}"

        return self.add_game_by_id(app_id, name, api_key)

    def add_game_by_id(self, app_id: int, name: str = "", api_key: str = ""):
        app_id = int(app_id)
        if app_id <= 0:
            return None

        if app_id not in self.games_cache:
            name = (
                name.strip()
                or self.app_names.get(app_id)
                or web_api.fetch_store_name(app_id)
                or f"AppID // {app_id}"
            )
            self.app_names.set(app_id, name)
            self.app_names.save()
            self.register_game(app_id, name, app_id in self.installed_app_ids)
        elif name.strip():
            # Local manifests sometimes use internal names like "snow".
            self.games_cache[app_id]["name"] = name.strip()
            self.app_names.set(app_id, name.strip())
            self.app_names.save()

        self.get_achievements_for_game(app_id, api_key)
        return self.games_cache.get(app_id)

    def search_games(self, query: str, limit: int = 12) -> list[dict]:
        query = query.strip()
        if not query:
            return []

        needle = query.casefold()
        results = []
        seen = set()

        for game in sorted(self.games_cache.values(), key=lambda g: g["name"].lower()):
            matches_name = needle in game["name"].casefold()
            matches_id = query.isdigit() and str(game["app_id"]).startswith(query)
            if not (matches_name or matches_id):
                continue
            results.append({
                **game,
                "in_library": True,
                "installed": game["app_id"] in self.installed_app_ids or game["installed"],
            })
            seen.add(game["app_id"])
            if len(results) >= limit:
                return results

        for item in web_api.search_store_games(query, limit=limit):
            app_id = item["app_id"]
            if app_id in seen:
                continue

            store_name = item.get("name", f"AppID // {app_id}")
            existing = self.games_cache.get(app_id)
            if existing:
                results.append({
                    **existing,
                    "name": store_name or existing["name"],
                    "image": item.get("image") or existing["image"],
                    "installed": app_id in self.installed_app_ids or existing["installed"],
                    "in_library": True,
                })
            else:
                total, unlocked, loaded = self._local_progress(app_id)
                results.append({
                    "app_id": app_id,
                    "name": store_name,
                    "image": item.get("image") or (
                        "https://shared.akamai.steamstatic.com/store_item_assets/"
                        f"steam/apps/{app_id}/header.jpg"
                    ),
                    "installed": app_id in self.installed_app_ids,
                    "in_library": False,
                    "total_ach": total,
                    "unlocked_ach": unlocked,
                    "achievements_loaded": loaded,
                })

            seen.add(app_id)
            if len(results) >= limit:
                break

        return results

    def _local_progress(self, app_id: int):
        schema = local_stats.schema_path(self.steam_path, app_id)
        if schema is None or not schema.exists():
            return 0, 0, False

        stats_file = local_stats.find_user_stats_file(
            self.steam_path, self.account_id3, app_id
        )
        signature = file_signature([schema, stats_file])
        cached = self.progress_cache.get(app_id, signature)
        if cached:
            return cached["total"], cached["unlocked"], True

        achievements, mapping = local_stats.parse_schema(self.steam_path, app_id)
        if not achievements:
            return 0, 0, False

        states, found = local_stats.read_user_states(
            self.steam_path, self.account_id3, app_id, mapping
        )
        if not found:
            return len(achievements), 0, False

        total = len(achievements)
        unlocked = sum(1 for achievement in achievements if states.get(achievement["id"]))
        self.progress_cache.put(app_id, signature, total, unlocked)
        return total, unlocked, True

    def set_single_achievement(
        self,
        app_id: int,
        ach_id: str,
        unlock: bool,
        api_key: str = "",
    ) -> dict:
        if not self._ensure_snapshot(app_id, api_key):
            return self._backup_refusal(app_id)

        result = self._call_worker(
            app_id, "set_state", {"id": ach_id, "unlock": unlock}
        )
        if result.get("status") != "ok":
            self.live_error = result.get("message", "Schreiben in Steam fehlgeschlagen")
            return {
                "status": "error",
                "message": self.live_error,
                "live": False,
                "game_summary": self.games_cache.get(app_id, {}),
            }

        self.live_error = ""
        self.live_mode_available = True
        self.current_states.setdefault(app_id, {})[ach_id] = unlock

        if app_id in self.achievements_cache:
            unlocked = 0
            for achievement in self.achievements_cache[app_id]:
                if achievement["id"] == ach_id:
                    achievement["unlocked"] = unlock
                if achievement["unlocked"]:
                    unlocked += 1
            if app_id in self.games_cache:
                self.games_cache[app_id]["unlocked_ach"] = unlocked

        return {
            "status": "ok",
            "live": True,
            "app_id": app_id,
            "ach_id": ach_id,
            "unlocked": unlock,
            "game_summary": self.games_cache.get(app_id, {}),
        }

    def set_bulk_game(self, app_id: int, unlock: bool, api_key: str = "") -> dict:
        if not self._ensure_snapshot(app_id, api_key):
            return self._backup_refusal(app_id, self.achievements_cache.get(app_id, []))

        if app_id not in self.achievements_cache:
            self.get_achievements_for_game(app_id, api_key, read_states=False)

        achievements = self.achievements_cache.get(app_id, [])
        ids = [achievement["id"] for achievement in achievements]

        result = self._call_worker(
            app_id, "set_bulk", {"unlock": unlock, "achievements": ids}
        )
        if result.get("status") != "ok":
            self.live_error = result.get("message", "Schreiben in Steam fehlgeschlagen")
            return {
                "status": "error",
                "message": self.live_error,
                "live": False,
                "achievements": achievements,
                "game_summary": self.games_cache.get(app_id, {}),
            }

        self.live_error = ""
        self.live_mode_available = True
        self.current_states[app_id] = {achievement_id: unlock for achievement_id in ids}

        for achievement in achievements:
            achievement["unlocked"] = unlock

        if app_id in self.games_cache:
            game = self.games_cache[app_id]
            game["total_ach"] = len(achievements)
            game["unlocked_ach"] = len(achievements) if unlock else 0
            game["achievements_loaded"] = True

        return {
            "status": "ok",
            "live": True,
            "app_id": app_id,
            "unlocked": unlock,
            "achievements": achievements,
            "game_summary": self.games_cache.get(app_id, {}),
        }

    def restore_game_to_snapshot(self, app_id: int, api_key: str = "") -> dict:
        if app_id not in self.achievements_cache:
            self.get_achievements_for_game(app_id, api_key, read_states=False)

        achievements = self.achievements_cache.get(app_id, [])
        saved = self.snapshot.get(app_id)

        if self.snapshot.account_mismatch:
            return self._error(
                app_id, "Das Backup gehört zu einem anderen Steam-Account.", achievements
            )
        if self.snapshot.last_save_error:
            message = (
                "Das Original-Backup konnte nicht gespeichert werden. "
                "Bitte prüfe die Schreibrechte des TAOS-Ordners."
            )
            return self._error(app_id, message, achievements)
        if not saved:
            if achievements:
                message = (
                    "Für dieses Spiel existiert noch kein Original-Backup. "
                    "Lade das Spiel zuerst, damit der aktuelle Stand gesichert wird."
                )
                return self._error(app_id, message, achievements)
            return {
                "status": "ok",
                "live": False,
                "message": "Dieses Spiel hat keine Achievements.",
                "app_id": app_id,
                "achievements": achievements,
                "game_summary": self.games_cache.get(app_id, {}),
            }

        result = self._call_worker(app_id, "set_exact_map", {"state_map": saved})
        if result.get("status") != "ok":
            self.live_error = result.get("message", "Schreiben in Steam fehlgeschlagen")
            return self._error(app_id, self.live_error, achievements)

        self.live_error = ""
        self.live_mode_available = True
        self.current_states[app_id] = dict(saved)

        unlocked = 0
        for achievement in achievements:
            state = bool(saved.get(achievement["id"], achievement["unlocked"]))
            achievement["unlocked"] = state
            if state:
                unlocked += 1

        if app_id in self.games_cache:
            game = self.games_cache[app_id]
            game["total_ach"] = len(achievements)
            game["unlocked_ach"] = unlocked
            game["achievements_loaded"] = True

        return {
            "status": "ok",
            "live": True,
            "app_id": app_id,
            "achievements": achievements,
            "game_summary": self.games_cache.get(app_id, {}),
        }

    def _backup_refusal(self, app_id: int, achievements=None) -> dict:
        return {
            "status": "error",
            "message": (
                "Konnte den Original-Stand nicht sichern. Der Schreibvorgang "
                "wurde abgebrochen, damit das Backup nicht verloren geht."
            ),
            "live": False,
            "achievements": achievements or self.achievements_cache.get(app_id, []),
            "game_summary": self.games_cache.get(app_id, {}),
        }

    def _error(self, app_id: int, message: str, achievements: list[dict]) -> dict:
        self.live_error = message
        return {
            "status": "error",
            "message": message,
            "live": False,
            "achievements": achievements,
            "game_summary": self.games_cache.get(app_id, {}),
        }

    def _call_worker(self, app_id: int, action: str, payload) -> dict:
        if self.steam_api_dll is None:
            return {
                "status": "error",
                "message": (
                    "Keine steam_api64.dll gefunden. Installiere ein Steam-Spiel "
                    "oder lege die DLL unter assets/ ab."
                ),
            }

        if getattr(sys, "frozen", False):
            command = [sys.executable, "--taos-worker", str(app_id), action, json.dumps(payload)]
        else:
            command = [
                sys.executable,
                str(ENTRYPOINT),
                "--taos-worker",
                str(app_id),
                action,
                json.dumps(payload),
            ]
        timeout = 30 if action in ("set_bulk", "set_exact_map") else 15
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

        fd, ipc_path = tempfile.mkstemp(prefix="taos_ipc_", suffix=".json")
        os.close(fd)

        env = os.environ.copy()
        env["TAOS_STEAM_API_DLL"] = str(self.steam_api_dll)
        env["TAOS_IPC_FILE"] = ipc_path
        if self.steam_path:
            env["TAOS_STEAM_PATH"] = str(self.steam_path)

        try:
            with self._worker_lock:
                process = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=timeout,
                    creationflags=flags,
                    cwd=str(self.data_dir),
                    env=env,
                )

            raw = ""
            with suppress(OSError):
                raw = Path(ipc_path).read_text(encoding="utf-8").strip()

            if raw:
                try:
                    return json.loads(raw)
                except ValueError:
                    pass

            output = process.stdout or ""
            if "TAOS_IPC_START" in output and "TAOS_IPC_END" in output:
                raw = output.split("TAOS_IPC_START", 1)[1].split("TAOS_IPC_END", 1)[0]
                try:
                    return json.loads(raw)
                except ValueError:
                    pass
        except (OSError, subprocess.SubprocessError) as exc:
            return {"status": "error", "message": str(exc)}
        finally:
            with suppress(OSError):
                Path(ipc_path).unlink()

        return {
            "status": "error",
            "message": (
                "Der Steamworks-Worker hat keine gültige Antwort geliefert. "
                f"stderr: {(process.stderr or '').strip()[:300]}"
            ),
        }

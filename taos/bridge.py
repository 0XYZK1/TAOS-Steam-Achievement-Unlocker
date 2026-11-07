"""pywebview bridge. All methods here are callable from JavaScript."""

import json
import threading
import time

from taos.engine import SteamLibraryEngine
from taos.steam.paths import is_steam_running


class TaosBridgeApi:
    def __init__(self):
        self.engine = SteamLibraryEngine()
        self._window = None
        self.api_key = ""
        self._maximized = False

    def set_window(self, window):
        self._window = window

    def window_minimize(self):
        if self._window:
            self._window.minimize()

    def window_toggle_maximize(self):
        if not self._window:
            return False
        if self._maximized:
            self._window.restore()
        else:
            self._window.maximize()
        self._maximized = not self._maximized
        return self._maximized

    def window_close(self):
        if self._window:
            self._window.destroy()

    def _games(self):
        return self.engine.sorted_games()

    def initialize_system(self):
        self.engine.steam_running = is_steam_running()
        games = self.engine.scan_local_library(self.api_key)
        snapshot = self.engine.snapshot
        return {
            "games": games,
            "user": f"{self.engine.persona_name} ({self.engine.steam_id64})",
            "live_dll": self.engine.live_mode_available,
            "steam_running": self.engine.steam_running,
            "snapshot_count": len(snapshot),
            "backup_created_at": snapshot.created_at,
            "backup_account_mismatch": snapshot.account_mismatch,
            "backup_error": snapshot.last_save_error,
        }

    def set_api_key(self, key: str):
        self.api_key = key.strip()
        return {"status": "ok", "games": self.engine.scan_local_library(self.api_key)}

    def add_missing_game(self, query: str):
        game = self.engine.add_game_manually(query, self.api_key)
        return {
            "status": "ok" if game else "not_found",
            "game": game,
            "games": self._games(),
        }

    def search_games(self, query: str):
        return {"status": "ok", "results": self.engine.search_games(query)}

    def add_game_from_search(self, app_id: int, name: str = ""):
        game = self.engine.add_game_by_id(int(app_id), name, self.api_key)
        return {
            "status": "ok" if game else "not_found",
            "game": game,
            "games": self._games(),
        }

    def load_game_details(self, app_id: int):
        app_id = int(app_id)
        achievements = self.engine.get_achievements_for_game(app_id, self.api_key)
        return {
            "game": self.engine.games_cache.get(app_id, {}),
            "achievements": achievements,
            "live_dll": self.engine.live_mode_available,
            "live_error": self.engine.live_error,
        }

    def toggle_achievement(self, app_id: int, ach_id: str, unlock: bool):
        return self.engine.set_single_achievement(
            int(app_id), str(ach_id), bool(unlock), self.api_key
        )

    def bulk_game_action(self, app_id: int, unlock: bool):
        return self.engine.set_bulk_game(int(app_id), bool(unlock), self.api_key)

    def reset_single_game_to_original(self, app_id: int):
        return self.engine.restore_game_to_snapshot(int(app_id), self.api_key)

    def global_master_action(self, mode: str):
        threading.Thread(target=self._run_global, args=(mode,), daemon=True).start()
        return {"status": "started", "total_games": len(self.engine.games_cache)}

    def _run_global(self, mode: str):
        games = list(self.engine.games_cache)
        errors = []

        for index, app_id in enumerate(games, 1):
            name = self.engine.games_cache[app_id]["name"]

            if self._window:
                payload = json.dumps({
                    "current": index,
                    "total": len(games),
                    "app_id": app_id,
                    "game_name": name,
                    "mode": mode,
                })
                self._window.evaluate_js(f"window.TAOS_UI.onGlobalProgress({payload});")

            if mode == "unlock_all":
                result = self.engine.set_bulk_game(app_id, True, self.api_key)
            elif mode == "lock_all":
                result = self.engine.set_bulk_game(app_id, False, self.api_key)
            elif mode == "restore_original":
                result = self.engine.restore_game_to_snapshot(app_id, self.api_key)
            else:
                result = {"status": "error", "message": f"Unknown mode: {mode}"}

            if result.get("status") != "ok":
                errors.append({
                    "app_id": app_id,
                    "game_name": name,
                    "message": result.get("message", "Unknown error"),
                })

            time.sleep(0.03)

        if self._window:
            done = json.dumps({
                "mode": mode,
                "games": self._games(),
                "errors": errors,
            })
            self._window.evaluate_js(f"window.TAOS_UI.onGlobalComplete({done});")

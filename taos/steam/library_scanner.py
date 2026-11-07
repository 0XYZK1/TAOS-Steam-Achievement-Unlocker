"""Build the game list from installed manifests, caches and Steam's APIs."""

import re
from pathlib import Path

import vdf

from taos.config import EXCLUDED_APPIDS
from taos.steam import web_api


class LibraryScanner:
    def __init__(self, engine):
        self.engine = engine

    def scan(self, api_key: str = "") -> set[int]:
        installed = self._installed_games()

        if api_key and self.engine.steam_id64:
            for game in web_api.fetch_owned_games(api_key, self.engine.steam_id64):
                self._register(game["appid"], game["name"], installed)

        if self.engine.steam_id64:
            for game in web_api.fetch_community_games(self.engine.steam_id64):
                self._register(game["appid"], game["name"], installed)

        self._local_caches(installed)
        self._fill_missing_names()
        return installed

    def _folders(self) -> list[Path]:
        steam = self.engine.steam_path
        if not steam:
            return []

        folders = [steam]
        library_file = steam / "steamapps" / "libraryfolders.vdf"
        if not library_file.exists():
            return folders

        try:
            with open(library_file, "r", encoding="utf-8", errors="ignore") as fp:
                data = vdf.load(fp)
        except Exception:
            return folders

        for value in data.get("libraryfolders", {}).values():
            path = value.get("path") if isinstance(value, dict) else value
            if path and Path(path).is_absolute():
                candidate = Path(path)
                if candidate not in folders:
                    folders.append(candidate)
        return folders

    def _installed_games(self) -> set[int]:
        installed = set()

        for folder in self._folders():
            steamapps = folder / "steamapps"
            if not steamapps.exists():
                continue

            for manifest in steamapps.glob("appmanifest_*.acf"):
                try:
                    with open(manifest, "r", encoding="utf-8", errors="ignore") as fp:
                        state = vdf.load(fp).get("AppState", {})
                    app_id = int(state.get("appid", 0))
                    name = state.get("name", "")
                except Exception:
                    continue

                if app_id <= 0 or app_id in EXCLUDED_APPIDS:
                    continue
                installed.add(app_id)
                self._register(app_id, name, installed, overwrite=False)

        return installed

    def _local_caches(self, installed: set[int]):
        steam = self.engine.steam_path
        if not steam or not steam.exists():
            return

        stats = steam / "appcache" / "stats"
        if stats.exists():
            for schema in stats.glob("UserGameStatsSchema_*.bin"):
                match = re.search(r"UserGameStatsSchema_(\d+)\.bin", schema.name)
                if not match:
                    continue
                app_id = int(match.group(1))
                if app_id <= 0 or app_id in EXCLUDED_APPIDS:
                    continue
                name = self.engine.read_schema_game_name(schema, app_id)
                self._register(app_id, name, installed, overwrite=False)

        userdata = steam / "userdata"
        if not userdata.exists():
            return

        configs = list(userdata.glob("*/config/localconfig.vdf"))
        configs += list(userdata.glob("*/7/remote/sharedconfig.vdf"))

        for config_path in configs:
            try:
                with open(config_path, "r", encoding="utf-8", errors="ignore") as fp:
                    config = vdf.load(fp)
            except Exception:
                continue

            store = (
                config.get("UserLocalConfigStore")
                or config.get("userlocalconfigstore")
                or config.get("UserRoamingConfigStore")
                or config.get("userroamingconfigstore")
                or {}
            )
            software = store.get("Software") or store.get("software") or {}
            valve = software.get("Valve") or software.get("valve") or {}
            steam_cfg = valve.get("Steam") or valve.get("steam") or {}
            apps = steam_cfg.get("apps") or steam_cfg.get("Apps") or {}

            for app_id in apps:
                if not str(app_id).isdigit():
                    continue
                app_id = int(app_id)
                if app_id <= 0 or app_id in EXCLUDED_APPIDS:
                    continue

                schema = stats / f"UserGameStatsSchema_{app_id}.bin"
                if self.engine.app_names.get(app_id) or schema.exists():
                    self._register(
                        app_id,
                        self.engine.app_names.get(app_id),
                        installed,
                        overwrite=False,
                    )

    def _register(self, app_id: int, name: str, installed: set[int], overwrite=True):
        if app_id <= 0 or app_id in EXCLUDED_APPIDS:
            return

        current = self.engine.app_names.get(app_id)
        if name and (overwrite or not current or current.startswith("AppID //")):
            self.engine.app_names.set(app_id, name)

        self.engine.register_game(
            app_id,
            self.engine.app_names.get(app_id, name),
            installed=app_id in installed,
        )

    def _fill_missing_names(self):
        missing = [
            app_id
            for app_id, game in self.engine.games_cache.items()
            if game["name"].startswith("AppID //")
        ]
        if not missing:
            return

        for app_id, name in web_api.resolve_app_names(missing).items():
            self.engine.app_names.set(app_id, name)
            if app_id in self.engine.games_cache:
                self.engine.games_cache[app_id]["name"] = name

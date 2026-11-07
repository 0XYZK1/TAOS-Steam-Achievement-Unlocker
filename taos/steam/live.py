"""Thin ctypes wrapper around Steam's flat API.

We never bundle the DLL. Instead we look for a copy that already ships with
one of the user's games, which keeps the repository clean and avoids adding a
binary to git. Steam has to be running; that is the only hard requirement.
"""

import ctypes
import os
import struct
import time
from contextlib import suppress
from pathlib import Path

import vdf


class SteamApiError(RuntimeError):
    pass


_REQUIRED = (
    "SteamAPI_Shutdown",
    "SteamAPI_RunCallbacks",
    "SteamAPI_ISteamUserStats_SetAchievement",
    "SteamAPI_ISteamUserStats_ClearAchievement",
    "SteamAPI_ISteamUserStats_StoreStats",
)

_STATS_GETTERS = (
    "SteamAPI_SteamUserStats_v013",
    "SteamAPI_SteamUserStats_v012",
    "SteamAPI_SteamUserStats_v011",
    "SteamAPI_SteamUserStats",
)

_IS_64BIT = ctypes.sizeof(ctypes.c_void_p) == 8


def _library_roots(steam_path: Path):
    yield steam_path

    library_file = steam_path / "steamapps" / "libraryfolders.vdf"
    if not library_file.exists():
        return

    try:
        with open(library_file, "r", encoding="utf-8", errors="ignore") as fp:
            folders = vdf.load(fp).get("libraryfolders", {})
    except Exception:
        return

    for value in folders.values():
        if isinstance(value, dict) and value.get("path"):
            yield Path(value["path"])
        elif isinstance(value, str) and Path(value).is_absolute():
            yield Path(value)


def _candidates(steam_path: Path | None):
    dll_name = "steam_api64.dll" if _IS_64BIT else "steam_api.dll"
    if not steam_path:
        return

    for root in _library_roots(steam_path):
        common = root / "steamapps" / "common"
        if not common.exists():
            continue
        for pattern in (f"*/{dll_name}", f"*/*/{dll_name}", f"*/*/*/{dll_name}"):
            yield from common.glob(pattern)


def _pe_exports(path: Path) -> set[str]:
    """Read the export names without loading a game DLL into our process."""
    data = path.read_bytes()
    if len(data) < 0x40 or data[:2] != b"MZ":
        return set()

    pe = struct.unpack_from("<I", data, 0x3C)[0]
    if data[pe:pe + 4] != b"PE\0\0":
        return set()

    coff = pe + 4
    machine = struct.unpack_from("<H", data, coff)[0]
    if (machine == 0x8664) != _IS_64BIT:
        return set()

    sections_count = struct.unpack_from("<H", data, coff + 2)[0]
    optional_size = struct.unpack_from("<H", data, coff + 16)[0]
    optional = coff + 20
    magic = struct.unpack_from("<H", data, optional)[0]
    if magic == 0x20B:
        dirs = optional + 112
    elif magic == 0x10B:
        dirs = optional + 96
    else:
        return set()

    export_rva, _ = struct.unpack_from("<II", data, dirs)
    if not export_rva:
        return set()

    sections = []
    entry = optional + optional_size
    for _ in range(sections_count):
        vsize, vaddr, rawsize, rawptr = struct.unpack_from("<IIII", data, entry + 8)
        sections.append((vaddr, max(vsize, rawsize), rawptr))
        entry += 40

    def offset(rva):
        for vaddr, size, rawptr in sections:
            if vaddr <= rva < vaddr + size:
                return rawptr + (rva - vaddr)
        return None

    export_offset = offset(export_rva)
    if export_offset is None:
        return set()

    name_count = struct.unpack_from("<I", data, export_offset + 24)[0]
    names_rva = struct.unpack_from("<I", data, export_offset + 32)[0]
    names_offset = offset(names_rva)
    if names_offset is None:
        return set()

    names = set()
    for index in range(name_count):
        name_rva = struct.unpack_from("<I", data, names_offset + index * 4)[0]
        name_offset = offset(name_rva)
        if name_offset is None:
            continue
        end = data.find(b"\0", name_offset)
        if end != -1:
            names.add(data[name_offset:end].decode("ascii", "ignore"))
    return names


def _looks_usable(path: Path) -> bool:
    try:
        exports = _pe_exports(path)
    except OSError:
        return False

    return (
        all(name in exports for name in _REQUIRED)
        and any(name in exports for name in _STATS_GETTERS)
        and ("SteamAPI_InitFlat" in exports or "SteamAPI_Init" in exports)
        and "SteamAPI_ISteamUserStats_RequestCurrentStats" in exports
    )


def find_steam_api_dll(
    base_dir: Path | None = None,
    steam_path: Path | None = None,
) -> Path | None:
    dll_name = "steam_api64.dll" if _IS_64BIT else "steam_api.dll"

    if base_dir:
        for direct in (base_dir / dll_name, base_dir / "assets" / dll_name):
            if direct.exists() and _looks_usable(direct):
                return direct

    for candidate in _candidates(steam_path):
        if _looks_usable(candidate):
            return candidate
    return None


class LiveSteamStats:
    def __init__(self, dll_path: Path):
        self.dll_path = Path(dll_path)
        self._dll = ctypes.WinDLL(str(self.dll_path))
        self._stats = None
        self._initialized = False
        self._bind()

    def _bind(self):
        dll = self._dll

        def fn(name, restype, argtypes):
            func = getattr(dll, name)
            func.restype = restype
            func.argtypes = argtypes
            return func

        self._init_flat = None
        self._init_legacy = None
        if hasattr(dll, "SteamAPI_InitFlat"):
            self._init_flat = fn("SteamAPI_InitFlat", ctypes.c_int, [ctypes.c_char_p])
        elif hasattr(dll, "SteamAPI_Init"):
            self._init_legacy = fn("SteamAPI_Init", ctypes.c_bool, [])
        else:
            raise SteamApiError("SteamAPI_Init fehlt in der DLL")

        self._shutdown = fn("SteamAPI_Shutdown", None, [])
        self._run_callbacks = fn("SteamAPI_RunCallbacks", None, [])

        getter = None
        for name in _STATS_GETTERS:
            if hasattr(dll, name):
                getter = fn(name, ctypes.c_void_p, [])
                break
        if getter is None:
            raise SteamApiError("ISteamUserStats-Schnittstelle fehlt in der DLL")
        self._get_user_stats = getter

        self._request_stats = None
        if hasattr(dll, "SteamAPI_ISteamUserStats_RequestCurrentStats"):
            self._request_stats = fn(
                "SteamAPI_ISteamUserStats_RequestCurrentStats",
                ctypes.c_bool,
                [ctypes.c_void_p],
            )

        # Note: GetAchievement takes an out-parameter. The bool return value
        # only says whether the call itself worked.
        self._get_achievement = fn(
            "SteamAPI_ISteamUserStats_GetAchievement",
            ctypes.c_bool,
            [ctypes.c_void_p, ctypes.c_char_p, ctypes.POINTER(ctypes.c_bool)],
        )
        self._set_achievement = fn(
            "SteamAPI_ISteamUserStats_SetAchievement",
            ctypes.c_bool,
            [ctypes.c_void_p, ctypes.c_char_p],
        )
        self._clear_achievement = fn(
            "SteamAPI_ISteamUserStats_ClearAchievement",
            ctypes.c_bool,
            [ctypes.c_void_p, ctypes.c_char_p],
        )
        self._store_stats = fn(
            "SteamAPI_ISteamUserStats_StoreStats",
            ctypes.c_bool,
            [ctypes.c_void_p],
        )

        self._get_num_achievements = None
        if hasattr(dll, "SteamAPI_ISteamUserStats_GetNumAchievements"):
            self._get_num_achievements = fn(
                "SteamAPI_ISteamUserStats_GetNumAchievements",
                ctypes.c_uint32,
                [ctypes.c_void_p],
            )

    def initialize(self, app_id: int):
        os.environ["SteamAppId"] = str(app_id)
        os.environ["SteamGameId"] = str(app_id)
        with suppress(OSError):
            Path("steam_appid.txt").write_text(str(app_id), encoding="utf-8")

        if self._init_flat is not None:
            error = ctypes.create_string_buffer(1024)
            code = self._init_flat(error)
            if code != 0:
                message = error.value.decode("utf-8", errors="ignore")
                raise SteamApiError(message or f"SteamAPI_InitFlat fehlgeschlagen (Code {code})")
        elif not self._init_legacy():
            raise SteamApiError("SteamAPI_Init fehlgeschlagen. Läuft Steam?")

        self._initialized = True
        self._stats = self._get_user_stats()
        if not self._stats:
            raise SteamApiError("Steamworks lieferte keine UserStats-Schnittstelle")

        if self._request_stats is not None:
            self._request_stats(self._stats)
            self.pump(0.8)

    def close(self):
        if self._initialized:
            with suppress(Exception):
                self._shutdown()
            self._initialized = False

    def pump(self, seconds: float):
        deadline = time.monotonic() + max(0.0, seconds)
        while time.monotonic() < deadline:
            with suppress(Exception):
                self._run_callbacks()
            time.sleep(0.05)

    def get_achievement(self, api_name: str) -> bool:
        if not self._stats:
            return False
        achieved = ctypes.c_bool(False)
        try:
            called = self._get_achievement(
                self._stats, api_name.encode("utf-8"), ctypes.byref(achieved)
            )
        except Exception:
            return False
        return bool(achieved.value) if called else False

    def set_achievement(self, api_name: str) -> bool:
        return self._write(self._set_achievement, api_name)

    def clear_achievement(self, api_name: str) -> bool:
        return self._write(self._clear_achievement, api_name)

    def _write(self, func, api_name: str) -> bool:
        if not self._stats:
            return False
        encoded = api_name.encode("utf-8")
        for _ in range(3):
            if func(self._stats, encoded):
                return True
            self.pump(0.25)
        return False

    def store_stats(self) -> bool:
        if not self._stats:
            return False

        stored = False
        for _ in range(3):
            stored = bool(self._store_stats(self._stats))
            self.pump(0.35)
            if stored:
                break

        self.pump(0.6)
        return stored

    def num_achievements(self) -> int:
        if not self._stats or self._get_num_achievements is None:
            return 0
        return int(self._get_num_achievements(self._stats))

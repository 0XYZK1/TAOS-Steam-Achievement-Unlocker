"""Locate Steam and figure out which account is active."""

import ctypes
import re
import sys
from pathlib import Path

from taos.config import STEAM_ID64_BASE

if sys.platform == "win32":
    import winreg


def find_steam_path() -> Path | None:
    if sys.platform == "win32":
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam")
            value, _ = winreg.QueryValueEx(key, "SteamPath")
            winreg.CloseKey(key)
            path = Path(value)
            if path.exists():
                return path
        except OSError:
            pass

    for path in (
        Path("C:/Program Files (x86)/Steam"),
        Path("C:/Program Files/Steam"),
        Path.home() / ".steam" / "steam",
        Path.home() / ".local" / "share" / "Steam",
    ):
        if path.exists():
            return path
    return None


def _active_account_id() -> str:
    if sys.platform != "win32":
        return ""
    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam\ActiveProcess"
        )
        value, _ = winreg.QueryValueEx(key, "ActiveUser")
        winreg.CloseKey(key)
    except OSError:
        return ""
    return str(int(value)) if value else ""


def _read_login_users(steam_path: Path) -> dict[str, dict[str, str]]:
    login_file = steam_path / "config" / "loginusers.vdf"
    if not login_file.exists():
        return {}

    try:
        text = login_file.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return {}

    users = {}
    for match in re.finditer(r'"(\d{17})"\s*\{(.*?)\n\s*\}', text, re.S):
        steam_id, block = match.group(1), match.group(2)
        persona = re.search(r'"PersonaName"\s*"([^"]*)"', block)
        recent = re.search(r'"MostRecent"\s*"([^"]*)"', block)
        users[steam_id] = {
            "PersonaName": persona.group(1) if persona else "STEAM USER",
            "MostRecent": recent.group(1) if recent else "0",
        }
    return users


def detect_active_user(steam_path: Path | None) -> tuple[str, str, str]:
    """Returns (steam_id64, account_id3, persona_name)."""
    if not steam_path:
        return "", "", "STEAM USER"

    users = _read_login_users(steam_path)
    active_id = _active_account_id()
    steam_id = ""
    persona = "STEAM USER"

    for sid, info in users.items():
        matches_active = bool(active_id) and str(int(sid) - STEAM_ID64_BASE) == active_id
        if not steam_id or matches_active or info.get("MostRecent") == "1":
            steam_id = sid
            persona = info.get("PersonaName", "STEAM USER")
            if matches_active:
                break

    if not steam_id and active_id:
        steam_id = str(int(active_id) + STEAM_ID64_BASE)

    account_id = ""
    if steam_id.isdigit():
        account_id = str(int(steam_id) - STEAM_ID64_BASE)
    return steam_id, account_id, persona


def is_steam_running() -> bool:
    if sys.platform != "win32":
        return False

    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam\ActiveProcess"
        )
        pid, _ = winreg.QueryValueEx(key, "pid")
        winreg.CloseKey(key)
    except OSError:
        return False

    if not pid:
        return False

    handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, int(pid))
    if not handle:
        return False
    ctypes.windll.kernel32.CloseHandle(handle)
    return True

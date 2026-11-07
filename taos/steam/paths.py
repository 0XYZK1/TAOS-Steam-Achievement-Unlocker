"""Locate Steam and figure out which account is active."""

import subprocess
import sys
from contextlib import suppress
from pathlib import Path

import vdf

from taos.config import STEAM_ID64_BASE

if sys.platform == "win32":
    import winreg


def find_steam_path() -> Path | None:
    if sys.platform == "win32":
        with suppress(OSError):
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam")
            value, _ = winreg.QueryValueEx(key, "SteamPath")
            winreg.CloseKey(key)
            path = Path(value)
            if path.exists():
                return path

    for path in (
        Path("C:/Program Files (x86)/Steam"),
        Path("C:/Program Files/Steam"),
        Path.home() / ".steam" / "steam",
        Path.home() / ".local" / "share" / "Steam",
    ):
        if path.exists():
            return path
    return None


def detect_active_user(steam_path: Path | None) -> tuple[str, str, str]:
    """Returns (steam_id64, account_id3, persona_name)."""
    if not steam_path:
        return "", "", "STEAM USER"

    steam_id = ""
    persona = "STEAM USER"
    login_file = steam_path / "config" / "loginusers.vdf"

    if login_file.exists():
        try:
            with open(login_file, "r", encoding="utf-8", errors="ignore") as fp:
                users = vdf.load(fp).get("users", {})
        except Exception:
            users = {}

        for sid, info in users.items():
            recent = str(info.get("MostRecent", "0")) == "1"
            if not steam_id or recent:
                steam_id = str(sid)
                persona = info.get("PersonaName", "STEAM USER")
                if recent:
                    break

    account_id = ""
    if steam_id.isdigit():
        account_id = str(int(steam_id) - STEAM_ID64_BASE)
    return steam_id, account_id, persona


def is_steam_running() -> bool:
    if sys.platform != "win32":
        return False

    try:
        output = subprocess.check_output(
            ["tasklist", "/FI", "IMAGENAME eq steam.exe", "/NH"],
            text=True,
            errors="replace",
            timeout=5,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return "steam.exe" in output.lower()

<div align="center">

# TAOS

*A T A O S Production.*  
*The Art of Software.*

[![Latest Release](https://img.shields.io/github/v/release/0XYZK1/TAOS-Steam-Achievement-Unlocker?style=flat-square&label=latest%20release&color=black)](https://github.com/0XYZK1/TAOS-Steam-Achievement-Unlocker/releases/latest)
[![Version](https://img.shields.io/badge/V1.0.0-black?style=flat-square)](https://github.com/0XYZK1/TAOS-Steam-Achievement-Unlocker/releases)
[![License](https://img.shields.io/badge/LICENSE-black?style=flat-square)](LICENSE)
[![Custom](https://img.shields.io/badge/CUSTOM-black?style=flat-square)](LICENSE)

</div>

---

A minimalist Steam achievement manager for Windows. TAOS reads the real local
progress from Steam's cache and writes changes back through Steamworks. No web
login, no API key, no browser automation.

---

## ✦ QUICKSTART

1. Download the latest `TAOS.exe` from [Releases](https://github.com/0XYZK1/TAOS-Steam-Achievement-Unlocker/releases/latest).
2. Run it. Python is not required.
3. Keep Steam running and close the game while changing achievements.
4. Pick a game, toggle what you need, done.

---

## ✦ WHAT IT DOES

- Reads your actual Steam library and achievement state
- Unlocks or locks achievements individually or per game
- Creates an original backup per Steam account on first launch
- Restores that backup exactly, including mixed states
- Searches games by partial name and shows live progress
- Writes through the same Steamworks path SAM uses

---

## ✦ BACKUP

The first full scan stores the current state in:

```
%LOCALAPPDATA%\TAOS\taos_initial_snapshot_<SteamID64>.json
```

That file is never touched by normal unlock, lock or toggle operations. Before
the first write to a game without a backup, TAOS reads and saves the current
state first.

`Reset to Original` really means reset. Achievements earned after the backup
will be removed too. The confirmation dialog says so.

---

## ✦ BUILD FROM SOURCE

```powershell
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python main.py
```

To build the executable:

```powershell
.venv\Scripts\pip install pyinstaller
.venv\Scripts\python -m PyInstaller --onefile --windowed --name TAOS ^
  --add-data "html.html;." --collect-all webview --collect-all clr_loader ^
  --collect-all pythonnet main.py
```

---

## ✦ NOTES

- Windows 10/11 only.
- Steam must be running. The game should be closed while writing.
- The required `steam_api64.dll` is located automatically in your installed
  Steam games. It is not bundled with TAOS.
- Achievements added by later DLC are not part of the original backup.
- Unlocking achievements may violate Steam or game rules. Use at your own risk.

---

<div align="center">

**TAOS**  
*Design. Code. Silence.*

© 2026 Dox / Xyk

</div>

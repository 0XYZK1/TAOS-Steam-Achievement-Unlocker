"""Application entry point for the pywebview window."""

import os
import sys
from pathlib import Path

import webview

from taos.bridge import TaosBridgeApi
from taos.config import APP_DIR, BUNDLE_DIR, DATA_DIR


def _log(message: str):
    if not os.environ.get("TAOS_DEBUG"):
        return
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with open(DATA_DIR / "taos_start.log", "a", encoding="utf-8") as fp:
            fp.write(message + "\n")
    except OSError:
        pass


def _html() -> Path:
    for candidate in (
        BUNDLE_DIR / "html.html",
        APP_DIR / "html.html",
        BUNDLE_DIR / "taos" / "ui" / "html.html",
        BUNDLE_DIR / "assets" / "html.html",
        BUNDLE_DIR / "assets" / "index.html",
    ):
        if candidate.exists():
            return candidate
    raise FileNotFoundError("html.html not found")


def main():
    _log("app start")
    api = TaosBridgeApi()
    _log("engine ready")

    try:
        page = _html()
    except FileNotFoundError as exc:
        print(f"[TAOS] {exc}")
        sys.exit(1)
    _log(f"html={page}")

    window = webview.create_window(
        title="TAOS — Steam Achievement Manager",
        url=str(page.resolve()),
        js_api=api,
        width=1420,
        height=880,
        min_size=(1100, 700),
        background_color="#050505",
        frameless=True,
        easy_drag=False,
    )
    _log("window created")
    api.set_window(window)
    _log("starting webview")
    webview.start(debug=False)
    _log("webview returned")

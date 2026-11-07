"""Application entry point for the pywebview window."""

import sys
from pathlib import Path

import webview

from taos.bridge import TaosBridgeApi
from taos.config import ROOT


def _html() -> Path:
    for candidate in (
        ROOT / "html.html",
        ROOT / "taos" / "ui" / "html.html",
        ROOT / "assets" / "html.html",
        ROOT / "assets" / "index.html",
    ):
        if candidate.exists():
            return candidate
    raise FileNotFoundError("html.html not found")


def main():
    api = TaosBridgeApi()

    try:
        page = _html()
    except FileNotFoundError as exc:
        print(f"[TAOS] {exc}")
        sys.exit(1)

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
    api.set_window(window)
    webview.start(debug=False)

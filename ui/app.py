from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication

from .main_window import MainWindow
from .theme import application_stylesheet


def _register_application_fonts() -> None:
    if os.name != "nt":
        return
    for font_path in (
        Path(r"C:\Windows\Fonts\segoeui.ttf"),
        Path(r"C:\Windows\Fonts\segoeuib.ttf"),
        Path(r"C:\Windows\Fonts\bahnschrift.ttf"),
        Path(r"C:\Windows\Fonts\CascadiaMono.ttf"),
        Path(r"C:\Windows\Fonts\YuGothM.ttc"),
        Path(r"C:\Windows\Fonts\msyh.ttc"),
        Path(r"C:\Windows\Fonts\malgun.ttf"),
    ):
        if font_path.is_file():
            QFontDatabase.addApplicationFont(str(font_path))


def create_application(argv: list[str] | None = None) -> QApplication:
    app = QApplication.instance() or QApplication(argv or sys.argv)
    _register_application_fonts()
    app.setApplicationName("eFootball Sider Studio")
    app.setOrganizationName("Toriga Modding")
    app.setStyle("Fusion")
    app.setFont(QFont("Segoe UI", 10))
    app.setStyleSheet(application_stylesheet())
    return app


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="eFootball Sider desktop studio")
    parser.add_argument("--screenshot", type=Path, help="Render the default window to a PNG and exit")
    parser.add_argument("--page", default="overview", help="Page to render with --screenshot")
    parser.add_argument("--width", type=int, default=1440)
    parser.add_argument("--height", type=int, default=900)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.screenshot:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    app = create_application([sys.argv[0], *(argv or [])])
    window = MainWindow()
    window.resize(args.width, args.height)
    window.select_page(args.page)
    window.show()

    if args.screenshot:
        args.screenshot.parent.mkdir(parents=True, exist_ok=True)

        started = time.monotonic()

        def capture_when_ready() -> None:
            page = window._stack.currentWidget()
            ready_check = getattr(page, "is_ready_for_capture", None)
            ready = ready_check() if callable(ready_check) else True
            if not ready and time.monotonic() - started < 15:
                QTimer.singleShot(100, capture_when_ready)
                return
            window.grab().save(str(args.screenshot), "PNG")
            app.quit()

        QTimer.singleShot(100, capture_when_ready)

    return app.exec()

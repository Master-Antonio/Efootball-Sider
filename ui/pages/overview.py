from __future__ import annotations

import qtawesome as qta
from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QMessageBox,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from ..context import AppContext
from ..models import Column, DictTableModel
from ..widgets.common import Metric, MetricStrip, PageSection, StatusBanner
from ..workers import TaskWorker


class OverviewPage(QWidget):
    status_message = Signal(str)

    def __init__(self, context: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("PageBody")
        self.context = context

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 28)
        layout.setSpacing(16)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        self.sync_button = QPushButton("Sync Sider")
        self.sync_button.setProperty("role", "primary")
        self.sync_button.setIcon(qta.icon("fa6s.arrows-rotate", color="#FFFFFF"))
        self.sync_button.clicked.connect(self._sync)
        launch = QPushButton("Launch eFootball")
        launch.setIcon(qta.icon("fa6s.play", color="#17201C"))
        launch.clicked.connect(self._launch)
        open_game = QPushButton("Open game folder")
        open_game.setIcon(qta.icon("fa6s.folder-open", color="#17201C"))
        open_game.clicked.connect(lambda: self._open(self.context.paths.game_bin))
        refresh = QPushButton("Refresh")
        refresh.setIcon(qta.icon("fa6s.rotate", color="#17201C"))
        refresh.clicked.connect(self.refresh)
        actions.addWidget(self.sync_button)
        actions.addWidget(launch)
        actions.addWidget(open_game)
        actions.addStretch(1)
        actions.addWidget(refresh)
        layout.addLayout(actions)

        self.metrics = MetricStrip(tuple())
        layout.addWidget(self.metrics)
        self.banner = StatusBanner()
        layout.addWidget(self.banner)

        readiness = PageSection("Workspace readiness", "Checks that affect the next run")
        self.readiness_model = DictTableModel(
            (
                Column("check", "CHECK"),
                Column("state", "STATE"),
                Column("detail", "DETAIL"),
            )
        )
        table = QTableView()
        table.setModel(self.readiness_model)
        table.setAlternatingRowColors(True)
        table.verticalHeader().hide()
        table.horizontalHeader().setStretchLastSection(True)
        table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        table.setMinimumHeight(260)
        readiness.layout.addWidget(table)
        layout.addWidget(readiness, 1)

        self.refresh()

    def refresh(self) -> None:
        status = self.context.game.status()
        self.metrics.set_metrics(
            (
                Metric(
                    "Game",
                    "Running" if status.running else "Offline",
                    "success" if status.running else "neutral",
                ),
                Metric(
                    "Native core",
                    "Hash current" if status.dll_current else "Sync needed",
                    "success" if status.dll_current else "warning",
                ),
                Metric(
                    "Live database",
                    "dt870 detected" if status.live_cpk_found else "Missing",
                    "success" if status.live_cpk_found else "error",
                ),
                Metric("Mod packages", f"{status.mod_count} installed"),
            )
        )
        checks = (
            ("Game installation", status.installed, str(self.context.paths.game_bin)),
            (
                "Proxy DLL",
                status.dll_current,
                "Installed and current" if status.dll_current else "Release build differs from game copy",
            ),
            ("Configuration", status.config_installed, str(self.context.paths.game_bin / "sider.ini")),
            ("Live database CPK", status.live_cpk_found, str(self.context.paths.live_database_cpk)),
        )
        self.readiness_model.set_records(
            [
                {"check": name, "state": "Ready" if ready else "Action needed", "detail": detail}
                for name, ready, detail in checks
            ]
        )
        if status.running:
            self.banner.set_message(
                f"eFootball is running as PID {status.pid}. Close it before syncing files.", "warning"
            )
        elif all(ready for _, ready, _ in checks):
            self.banner.set_message("Workspace and installed native core are aligned.", "success")
        else:
            self.banner.set_message("One or more workspace checks need attention.", "warning")

    def _sync(self) -> None:
        self.sync_button.setEnabled(False)
        self.banner.set_message("Syncing native core, config and mod packages...", "info")
        worker = TaskWorker(self.context.game.sync)
        worker.signals.result.connect(lambda _status: self._sync_done())
        worker.signals.error.connect(self._show_error)
        worker.signals.finished.connect(lambda: self.sync_button.setEnabled(True))
        self.context.start_worker(worker)

    def _sync_done(self) -> None:
        self.status_message.emit("Sider synchronized")
        self.refresh()

    def _launch(self) -> None:
        try:
            self.context.game.launch()
            self.status_message.emit("Launch request sent to Steam")
        except OSError as exc:
            self._show_error(str(exc))

    def _open(self, path) -> None:
        try:
            self.context.game.open_path(path)
        except (FileNotFoundError, OSError) as exc:
            self._show_error(str(exc))

    def _show_error(self, detail: str) -> None:
        message = detail.strip().splitlines()[-1] if detail.strip() else "Unknown error"
        self.banner.set_message(message, "error")
        QMessageBox.critical(self, "Operation failed", message)

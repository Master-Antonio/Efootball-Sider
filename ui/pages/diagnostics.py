from __future__ import annotations

import qtawesome as qta
from PySide6.QtGui import QFont, QGuiApplication
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from ..context import AppContext
from ..models import Column, DictTableModel
from ..widgets.common import Metric, MetricStrip, PageSection, StatusBanner


class DiagnosticsPage(QWidget):
    def __init__(self, context: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("PageBody")
        self.context = context
        self._raw_log = ""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 22, 28, 28)
        layout.setSpacing(14)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        refresh = QPushButton("Run checks")
        refresh.setProperty("role", "primary")
        refresh.setIcon(qta.icon("fa6s.stethoscope", color="#FFFFFF"))
        refresh.clicked.connect(self.refresh)
        copy = QPushButton("Copy log")
        copy.setIcon(qta.icon("fa6s.copy", color="#17201C"))
        copy.clicked.connect(lambda: QGuiApplication.clipboard().setText(self.log.toPlainText()))
        open_log = QPushButton("Open log folder")
        open_log.setIcon(qta.icon("fa6s.folder-open", color="#17201C"))
        open_log.clicked.connect(self._open_log_folder)
        toolbar.addWidget(refresh)
        toolbar.addWidget(copy)
        toolbar.addWidget(open_log)
        toolbar.addStretch(1)
        self.scope = QComboBox()
        self.scope.addItems(("All entries", "Warnings", "Camera", "LiveCPK"))
        self.scope.currentIndexChanged.connect(self._apply_log_filter)
        toolbar.addWidget(self.scope)
        self.log_search = QLineEdit()
        self.log_search.setPlaceholderText("Search native log")
        self.log_search.setClearButtonEnabled(True)
        self.log_search.setFixedWidth(240)
        self.log_search.textChanged.connect(self._apply_log_filter)
        toolbar.addWidget(self.log_search)
        self.wrap = QCheckBox("Wrap")
        self.wrap.toggled.connect(self._set_wrap)
        toolbar.addWidget(self.wrap)
        layout.addLayout(toolbar)
        self.banner = StatusBanner()
        layout.addWidget(self.banner)
        self.metrics = MetricStrip(tuple())
        layout.addWidget(self.metrics)

        checks = PageSection("Health checks", "Ground truth from files and process state")
        self.check_model = DictTableModel(
            (
                Column("check", "CHECK"),
                Column("state", "STATE"),
                Column("detail", "DETAIL"),
            )
        )
        table = QTableView()
        table.setModel(self.check_model)
        table.setAlternatingRowColors(True)
        table.verticalHeader().hide()
        table.horizontalHeader().setStretchLastSection(True)
        table.setMaximumHeight(215)
        checks.layout.addWidget(table)
        layout.addWidget(checks)

        logs = PageSection("Native log", "Latest entries from sider_rust.log")
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.log.setFont(QFont("Cascadia Mono", 9))
        logs.layout.addWidget(self.log, 1)
        layout.addWidget(logs, 1)
        self.refresh()

    def refresh(self) -> None:
        status = self.context.game.status()
        log_text = self.context.game.read_log_tail(350)
        self._raw_log = log_text
        self._apply_log_filter()
        camera_state = "Active" if "[CAMERA DETOUR]" in log_text else "Unverified"
        livecpk_state = "Active" if "Hook detour CreateFileW" in log_text else "No telemetry"
        checks = (
            ("Game path", status.installed, str(self.context.paths.game_bin)),
            (
                "Proxy DLL hash",
                status.dll_current,
                "Current" if status.dll_current else "Build and installed DLL differ",
            ),
            ("Live database", status.live_cpk_found, str(self.context.paths.live_database_cpk)),
            ("Camera detour", camera_state == "Active", camera_state),
            ("LiveCPK hook", livecpk_state == "Active", livecpk_state),
        )
        self.check_model.set_records(
            [
                {"check": name, "state": "Pass" if passed else "Review", "detail": detail}
                for name, passed, detail in checks
            ]
        )
        passed = sum(value for _, value, _ in checks)
        self.metrics.set_metrics(
            (
                Metric(
                    "Checks passed",
                    f"{passed}/{len(checks)}",
                    "success" if passed == len(checks) else "warning",
                ),
                Metric("Camera", camera_state, "success" if camera_state == "Active" else "warning"),
                Metric("LiveCPK", livecpk_state, "success" if livecpk_state == "Active" else "warning"),
                Metric("Game", "Running" if status.running else "Offline"),
            )
        )
        if passed == len(checks):
            self.banner.set_message("All runtime checks pass.", "success")
        else:
            remaining = len(checks) - passed
            noun = "check needs" if remaining == 1 else "checks need"
            self.banner.set_message(f"{remaining} {noun} review.", "warning")

    def _apply_log_filter(self, _value=None) -> None:
        lines = self._raw_log.splitlines()
        scope = self.scope.currentText() if hasattr(self, "scope") else "All entries"
        if scope == "Warnings":
            lines = [line for line in lines if any(token in line.upper() for token in ("WARN", "ERROR"))]
        elif scope == "Camera":
            lines = [line for line in lines if "CAMERA" in line.upper()]
        elif scope == "LiveCPK":
            lines = [line for line in lines if "LIVECPK" in line.upper()]
        query = self.log_search.text().strip().casefold() if hasattr(self, "log_search") else ""
        if query:
            lines = [line for line in lines if query in line.casefold()]
        self.log.setPlainText("\n".join(lines) if lines else "No log lines match the current filter.")

    def _set_wrap(self, enabled: bool) -> None:
        mode = QPlainTextEdit.LineWrapMode.WidgetWidth if enabled else QPlainTextEdit.LineWrapMode.NoWrap
        self.log.setLineWrapMode(mode)

    def _open_log_folder(self) -> None:
        try:
            self.context.game.open_path(self.context.paths.rust_log.parent)
        except (FileNotFoundError, OSError) as exc:
            self.banner.set_message(str(exc), "error")

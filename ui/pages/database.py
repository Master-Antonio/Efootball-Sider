from __future__ import annotations

from pathlib import Path

import qtawesome as qta
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTabBar,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from ..context import AppContext
from ..models import Column, DictTableModel, TypedSortFilterProxyModel
from ..services.database import DatabaseBundle
from ..widgets.common import Metric, MetricStrip, PageSection, PathField, StatusBanner
from ..workers import TaskWorker

TABLES = ("players", "assignments", "teams")
TABLE_COLUMNS = {
    "players": (
        Column("player_id", "PLAYER ID", monospace=True),
        Column("display_name", "NAME"),
        Column("nationality_id", "NATION ID", monospace=True),
        Column("height_cm", "HEIGHT"),
        Column("weight_kg", "WEIGHT"),
        Column("position_id", "POSITION ID"),
        Column("layout", "LAYOUT"),
    ),
    "assignments": (
        Column("team_id", "TEAM ID", monospace=True),
        Column("player_id", "PLAYER ID", monospace=True),
        Column("shirt_number", "SHIRT"),
        Column("sort_key", "ORDER"),
        Column("role_flags", "ROLE FLAGS", formatter=lambda value: f"0x{int(value):04X}", monospace=True),
        Column("is_captain", "CAPTAIN"),
        Column("record_id", "RECORD ID", monospace=True),
    ),
    "teams": (
        Column("team_id", "TEAM ID", monospace=True),
        Column("offset", "OFFSET", monospace=True),
        Column("hex", "HEADER", monospace=True),
    ),
}


class DatabasePage(QWidget):
    status_message = Signal(str)

    def __init__(self, context: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("PageBody")
        self.context = context
        self.bundle: DatabaseBundle | None = None
        self.current_records: list[dict] = []
        self.current_columns: tuple[str, ...] = tuple()
        self._table_loading = False
        self._pending_tab_index: int | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 22, 28, 28)
        layout.setSpacing(14)

        source_row = QHBoxLayout()
        source_row.setSpacing(8)
        source_copy = QVBoxLayout()
        source_copy.setSpacing(2)
        self.source_label = QLabel(f"Live database archive · {context.paths.live_database_cpk.name}")
        self.source_label.setObjectName("FieldLabel")
        source_meta = QLabel("dt870 has priority over the base dt200 layer")
        source_meta.setObjectName("SectionMeta")
        source_copy.addWidget(self.source_label)
        source_copy.addWidget(source_meta)
        source_row.addLayout(source_copy)
        self.source = PathField(str(context.paths.live_database_cpk))
        self.source.browse.clicked.connect(self._browse_source)
        source_row.addWidget(self.source, 1)
        self.extract_button = QPushButton("Extract and validate")
        self.extract_button.setProperty("role", "primary")
        self.extract_button.setIcon(qta.icon("fa6s.file-export", color="#FFFFFF"))
        self.extract_button.clicked.connect(self.extract)
        source_row.addWidget(self.extract_button)
        layout.addLayout(source_row)

        self.progress = QProgressBar()
        self.progress.setRange(0, 3)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(5)
        self.progress.hide()
        layout.addWidget(self.progress)
        self.banner = StatusBanner()
        layout.addWidget(self.banner)
        self.metrics = MetricStrip(
            (
                Metric("Players", "--"),
                Metric("Assignments", "--"),
                Metric("Squads", "--"),
                Metric("Teams", "--"),
            )
        )
        layout.addWidget(self.metrics)

        section = PageSection()
        tools = QHBoxLayout()
        tools.setSpacing(8)
        self.tabs = QTabBar()
        self.tabs.setExpanding(False)
        self.tabs.addTab("Players")
        self.tabs.addTab("Assignments")
        self.tabs.addTab("Teams")
        self.tabs.currentChanged.connect(self._load_table)
        tools.addWidget(self.tabs)
        tools.addStretch(1)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search players")
        self.search.setClearButtonEnabled(True)
        self.search.setFixedWidth(260)
        self.search.textChanged.connect(self._set_filter)
        tools.addWidget(self.search)
        self.export_button = QPushButton("Export all CSV")
        self.export_button.setIcon(qta.icon("fa6s.download", color="#17201C"))
        self.export_button.setEnabled(False)
        self.export_button.clicked.connect(self.export_csv)
        tools.addWidget(self.export_button)
        section.layout.addLayout(tools)

        self.model = DictTableModel(TABLE_COLUMNS["players"])
        self.proxy = TypedSortFilterProxyModel(self)
        self.proxy.setSourceModel(self.model)
        self.proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.proxy.setFilterKeyColumn(-1)
        self.table = QTableView()
        self.table.setModel(self.proxy)
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(True)
        self.table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableView.SelectionMode.SingleSelection)
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setMinimumHeight(380)
        section.layout.addWidget(self.table, 1)
        layout.addWidget(section, 1)

        existing = self.context.database.load_bundle()
        if existing:
            self._bundle_ready(existing, load_table=False)
        else:
            self.banner.set_message("Extract the live CPK to populate verified database views.", "info")

    def _browse_source(self) -> None:
        selected, _ = QFileDialog.getOpenFileName(
            self,
            "Choose eFootball database CPK",
            self.source.path(),
            "CRI archives (*.cpk);;All files (*)",
        )
        if selected:
            self.source.set_path(selected)
            self.source_label.setText(f"Live database archive · {Path(selected).name}")

    def extract(self) -> None:
        source = Path(self.source.path())
        output = self.context.paths.database_workspace / "live"
        self.extract_button.setEnabled(False)
        self.progress.setValue(0)
        self.progress.show()
        self.banner.set_message("Reading CPK entries...", "info")
        self.status_message.emit("Extracting and validating live database...")
        worker = TaskWorker(
            self.context.database.extract_bundle,
            source,
            output,
            progress=None,
        )
        worker.signals.progress.connect(self._on_progress)
        worker.signals.result.connect(self._bundle_ready)
        worker.signals.error.connect(self._show_error)
        worker.signals.finished.connect(self._extract_finished)
        self.context.start_worker(worker)

    def _on_progress(self, current: int, total: int, name: str) -> None:
        self.progress.setRange(0, total)
        self.progress.setValue(current)
        self.banner.set_message(f"Processing {name}", "info")

    def _extract_finished(self) -> None:
        self.extract_button.setEnabled(True)
        self.progress.hide()

    def _bundle_ready(self, bundle: DatabaseBundle, load_table: bool = True) -> None:
        self.bundle = bundle
        manifest = bundle.manifest
        self.metrics.set_metrics(
            (
                Metric("Players", f"{manifest['player']['record_count']:,}", "success"),
                Metric("Assignments", f"{manifest['assignment']['record_count']:,}", "success"),
                Metric("Squads", f"{manifest['assignment']['team_count']:,}", "success"),
                Metric("Teams", f"{manifest['team']['record_count']:,}", "success"),
            )
        )
        warning_count = manifest["assignment"].get("warning_count", 0)
        if warning_count:
            self.banner.set_message(
                f"Validated with {warning_count} source-data warning. No file was modified.",
                "warning",
            )
        else:
            self.banner.set_message("WESYS containers and cross-table references are valid.", "success")
        self.status_message.emit("Live database extracted and validated")
        if load_table:
            self._load_table(self.tabs.currentIndex())

    def _load_table(self, index: int) -> None:
        if self.bundle is None or not 0 <= index < len(TABLES):
            return
        if self._table_loading:
            self._pending_tab_index = index
            return
        kind = TABLES[index]
        self._table_loading = True
        self.search.setPlaceholderText(f"Search {kind}")
        self.table.setEnabled(False)
        self.banner.set_message(f"Loading {kind}...", "info")
        self.status_message.emit(f"Loading {kind} records...")
        worker = TaskWorker(self.context.database.load_records, self.bundle, kind)
        worker.signals.result.connect(lambda result, table_kind=kind: self._records_ready(table_kind, result))
        worker.signals.error.connect(self._show_error)
        worker.signals.finished.connect(self._table_load_finished)
        self.context.start_worker(worker)

    def _table_load_finished(self) -> None:
        self._table_loading = False
        self.table.setEnabled(True)
        if self._pending_tab_index is not None:
            pending = self._pending_tab_index
            self._pending_tab_index = None
            self._load_table(pending)

    def _records_ready(self, kind: str, result: tuple[list[dict], tuple[str, ...]]) -> None:
        if kind != TABLES[self.tabs.currentIndex()]:
            return
        records, columns = result
        self.current_records = records
        self.current_columns = columns
        self.model = DictTableModel(TABLE_COLUMNS[kind], records)
        self.proxy.setSourceModel(self.model)
        self.export_button.setEnabled(bool(records))
        self.export_button.setText(f"Export all {len(records):,}")
        self.export_button.setToolTip("Export the complete unfiltered table to CSV")
        self._configure_columns(kind)
        self.table.sortByColumn(0, Qt.SortOrder.AscendingOrder)
        self.banner.set_message(f"Showing {len(records):,} {kind} records.", "success")
        self.status_message.emit(f"Loaded {len(records):,} {kind} records")

    def is_ready_for_capture(self) -> bool:
        return self.bundle is None or self.model.rowCount() > 0

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if self.bundle is not None and self.model.rowCount() == 0:
            self._load_table(self.tabs.currentIndex())

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if self.current_records:
            self._configure_columns(TABLES[self.tabs.currentIndex()])

    def _configure_columns(self, kind: str) -> None:
        if self.current_records:
            count = len(self.current_records)
            self.export_button.setText(f"Export all {count:,}" if self.width() >= 1_000 else "Export all")
            self.export_button.setToolTip(f"Export all {count:,} unfiltered records to CSV")
        header = self.table.horizontalHeader()
        for column in range(self.model.columnCount()):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
            self.table.setColumnHidden(column, False)
        if kind == "players":
            header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
            layout_column = self.model.columnCount() - 1
            self.table.setColumnHidden(layout_column, self.width() < 1_000)
            if not self.table.isColumnHidden(layout_column):
                header.setSectionResizeMode(layout_column, QHeaderView.ResizeMode.Stretch)
        elif self.model.columnCount():
            header.setSectionResizeMode(self.model.columnCount() - 1, QHeaderView.ResizeMode.Stretch)

    def _set_filter(self, value: str) -> None:
        self.proxy.setFilterFixedString(value)
        QTimer.singleShot(0, self._show_filter_count)

    def _show_filter_count(self) -> None:
        if not self.current_records:
            return
        visible = self.proxy.rowCount()
        total = len(self.current_records)
        kind = TABLES[self.tabs.currentIndex()]
        if visible == total:
            self.banner.set_message(f"Showing all {total:,} {kind} records.", "success")
        else:
            self.banner.set_message(f"Showing {visible:,} of {total:,} {kind} records.", "info")

    def export_csv(self) -> None:
        if not self.current_records:
            return
        kind = TABLES[self.tabs.currentIndex()]
        selected, _ = QFileDialog.getSaveFileName(
            self,
            "Export database table",
            str(self.context.paths.database_workspace / f"{kind}.csv"),
            "CSV files (*.csv)",
        )
        if not selected:
            return
        self.export_button.setEnabled(False)
        worker = TaskWorker(
            self.context.database.export_csv,
            self.current_records,
            self.current_columns,
            Path(selected),
        )
        worker.signals.result.connect(
            lambda _result: self.banner.set_message(f"Exported {kind} to {selected}", "success")
        )
        worker.signals.error.connect(self._show_error)
        worker.signals.finished.connect(lambda: self.export_button.setEnabled(True))
        self.context.start_worker(worker)

    def _show_error(self, detail: str) -> None:
        message = detail.strip().splitlines()[-1] if detail.strip() else "Unknown error"
        self.banner.set_message(message, "error")
        QMessageBox.critical(self, "Database operation failed", message)

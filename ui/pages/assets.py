from __future__ import annotations

import re
from pathlib import Path

import qtawesome as qta
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from ..context import AppContext
from ..models import Column, DictTableModel, TypedSortFilterProxyModel, format_bytes
from ..widgets.common import EmptyState, Metric, MetricStrip, PageSection, StatusBanner
from ..workers import TaskWorker


class AssetsPage(QWidget):
    status_message = Signal(str)

    def __init__(self, context: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("PageBody")
        self.context = context
        self._running = False
        self._scan_busy = False
        self._seen: set[tuple[int, str]] = set()
        self._records: list[dict] = []
        self._game_running = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 22, 28, 28)
        layout.setSpacing(14)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        self.start_button = QPushButton("Start discovery")
        self.start_button.setProperty("role", "primary")
        self.start_button.setIcon(qta.icon("fa6s.satellite-dish", color="#FFFFFF"))
        self.start_button.clicked.connect(self._primary_action)
        self.stop_button = QPushButton("Stop")
        self.stop_button.setIcon(qta.icon("fa6s.stop", color="#17201C"))
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self.stop)
        self.clear_button = QPushButton("Clear")
        self.clear_button.setIcon(qta.icon("fa6s.eraser", color="#17201C"))
        self.clear_button.setEnabled(False)
        self.clear_button.clicked.connect(self.clear)
        toolbar.addWidget(self.start_button)
        toolbar.addWidget(self.stop_button)
        toolbar.addWidget(self.clear_button)
        toolbar.addStretch(1)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Filter paths, types or addresses")
        self.search.setClearButtonEnabled(True)
        self.search.setFixedWidth(300)
        toolbar.addWidget(self.search)
        layout.addLayout(toolbar)

        self.banner = StatusBanner(
            "Discovery reads asset references from game memory. It does not modify the process.",
            "info",
        )
        layout.addWidget(self.banner)
        self.metrics = MetricStrip(tuple())
        layout.addWidget(self.metrics)

        section = PageSection()
        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.model = DictTableModel(
            (
                Column("category", "TYPE"),
                Column("address", "ADDRESS", formatter=lambda value: f"0x{int(value):012X}", monospace=True),
                Column("path", "ASSET PATH"),
                Column("region_size", "REGION", formatter=format_bytes),
            )
        )
        self.proxy = TypedSortFilterProxyModel(self)
        self.proxy.setSourceModel(self.model)
        self.proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.proxy.setFilterKeyColumn(-1)
        self.search.textChanged.connect(self.proxy.setFilterFixedString)
        self.table = QTableView()
        self.table.setModel(self.proxy)
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(True)
        self.table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableView.SelectionMode.SingleSelection)
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.selectionModel().selectionChanged.connect(self._selection_changed)
        splitter.addWidget(self.table)

        details = QWidget()
        details_layout = QVBoxLayout(details)
        details_layout.setContentsMargins(18, 8, 4, 8)
        details_layout.setSpacing(8)
        heading = QLabel("Selected asset")
        heading.setObjectName("SectionTitle")
        self.detail_type = QLabel("No selection")
        self.detail_type.setObjectName("DetailValue")
        self.detail_address = QLabel("--")
        self.detail_address.setObjectName("MonoValue")
        self.detail_path = QLabel("Select a discovered reference")
        self.detail_path.setObjectName("DetailText")
        self.detail_path.setWordWrap(True)
        self.package_button = QPushButton("Create mod package")
        self.package_button.setIcon(qta.icon("fa6s.box-open", color="#17201C"))
        self.package_button.setEnabled(False)
        self.package_button.clicked.connect(self._create_package)
        details_layout.addWidget(heading)
        details_layout.addWidget(self.detail_type)
        details_layout.addWidget(self.detail_address)
        details_layout.addWidget(self.detail_path)
        details_layout.addStretch(1)
        details_layout.addWidget(self.package_button)
        splitter.addWidget(details)
        splitter.setSizes((820, 300))
        self.content_stack = QStackedWidget()
        empty = QWidget()
        empty_layout = QVBoxLayout(empty)
        empty_layout.addStretch(1)
        empty_layout.addWidget(
            EmptyState(
                "No asset references yet",
                "Launch eFootball and enter a match, then start read-only discovery.",
                "fa6s.satellite-dish",
            )
        )
        self.empty_action = QPushButton("Start discovery")
        self.empty_action.setProperty("role", "primary")
        self.empty_action.clicked.connect(self._primary_action)
        empty_layout.addWidget(self.empty_action, alignment=Qt.AlignmentFlag.AlignHCenter)
        empty_layout.addStretch(1)
        self.content_stack.addWidget(empty)
        self.content_stack.addWidget(splitter)
        section.layout.addWidget(self.content_stack, 1)
        layout.addWidget(section, 1)

        self._timer = QTimer(self)
        self._timer.setInterval(240)
        self._timer.timeout.connect(self._scan_once)
        self._refresh_metrics()
        self.refresh()

    def refresh(self) -> None:
        self._game_running = self.context.game.status().running
        if self._game_running:
            label = "Start discovery"
            icon = "fa6s.satellite-dish"
        else:
            label = "Launch eFootball"
            icon = "fa6s.play"
        self.start_button.setText(label)
        self.start_button.setIcon(qta.icon(icon, color="#FFFFFF"))
        self.empty_action.setText(label)
        if not self._running:
            self.banner.set_message(
                "Discovery reads asset references from game memory. It does not modify the process."
                if self._game_running
                else "eFootball is offline. Launch the game before attaching read-only discovery.",
                "info",
            )

    def _primary_action(self) -> None:
        self.refresh()
        if self._game_running:
            self.start()
            return
        try:
            self.context.game.launch()
            self.banner.set_message(
                "Launch request sent to Steam. Start discovery after the game opens.", "success"
            )
            self.status_message.emit("Launch request sent to Steam")
        except OSError as exc:
            self.banner.set_message(str(exc), "error")

    def start(self) -> None:
        try:
            pid = self.context.memory.attach()
        except (OSError, PermissionError, RuntimeError) as exc:
            self.banner.set_message(str(exc), "error")
            return
        self._running = True
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.banner.set_message(f"Attached read-only to eFootball PID {pid}.", "success")
        self.status_message.emit(f"Asset discovery attached to PID {pid}")
        self._timer.start()
        self._scan_once()

    def stop(self) -> None:
        self._timer.stop()
        self._running = False
        self.context.memory.detach()
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.banner.set_message("Discovery stopped. Captured references remain available.", "info")
        self._refresh_metrics()

    def clear(self) -> None:
        self._seen.clear()
        self._records.clear()
        self.model.set_records([])
        self.content_stack.setCurrentIndex(0)
        self.clear_button.setEnabled(False)
        self._refresh_metrics()

    def _scan_once(self) -> None:
        if not self._running or self._scan_busy:
            return
        self._scan_busy = True
        worker = TaskWorker(self.context.memory.scan, 48, 100)
        worker.signals.result.connect(self._append_hits)
        worker.signals.error.connect(
            lambda detail: self.banner.set_message(detail.strip().splitlines()[-1], "error")
        )
        worker.signals.finished.connect(lambda: setattr(self, "_scan_busy", False))
        self.context.start_worker(worker)

    def _append_hits(self, hits) -> None:
        added = 0
        for hit in hits:
            signature = (hit.address, hit.path.lower())
            if signature in self._seen:
                continue
            self._seen.add(signature)
            self._records.append(
                {
                    "category": hit.category,
                    "address": hit.address,
                    "path": hit.path,
                    "region_size": hit.region_size,
                }
            )
            added += 1
        if added:
            self.model.set_records(self._records)
            self.content_stack.setCurrentIndex(1)
            self.clear_button.setEnabled(True)
            self.banner.set_message(f"Captured {added} new references.", "success")
            self._refresh_metrics()

    def _refresh_metrics(self) -> None:
        categories = {record["category"] for record in self._records}
        containers = sum(record["category"] == "Container" for record in self._records)
        databases = sum(record["category"] == "Database" for record in self._records)
        self.metrics.set_metrics(
            (
                Metric("References", f"{len(self._records):,}"),
                Metric("Asset types", str(len(categories))),
                Metric("Containers", str(containers)),
                Metric("Databases", str(databases)),
            )
        )

    def _selection_changed(self, _selected=None, _deselected=None) -> None:
        indexes = self.table.selectionModel().selectedRows()
        if not indexes:
            self.package_button.setEnabled(False)
            return
        source_index = self.proxy.mapToSource(indexes[0])
        record = self.model.record(source_index.row())
        if not record:
            return
        self.detail_type.setText(record["category"])
        self.detail_address.setText(f"0x{record['address']:012X}")
        self.detail_path.setText(record["path"])
        self.package_button.setEnabled(True)
        self.package_button.setProperty("asset_path", record["path"])

    def _create_package(self) -> None:
        asset_path = self.package_button.property("asset_path")
        if not asset_path:
            return
        base_name = Path(str(asset_path).replace("\\", "/")).stem
        folder = "Mod_" + (re.sub(r"[^A-Za-z0-9_]+", "_", base_name).strip("_") or "Asset")
        destination = self.context.paths.content / folder
        if destination.exists():
            QMessageBox.warning(self, "Package exists", f"{folder} already exists in content.")
            return
        destination.mkdir(parents=True)
        (destination / "mod.ini").write_text(
            "\n".join(
                (
                    "[MOD]",
                    f'name = "{folder.replace("_", " ")}"',
                    'category = "Asset override"',
                    'author = "Modder"',
                    'version = "1.0"',
                    "",
                    "[OVERRIDES]",
                    f'target_asset = "{asset_path}"',
                    "",
                )
            ),
            encoding="utf-8",
        )
        self.banner.set_message(
            f"Created {folder}. Add cooked files using the target virtual path.", "success"
        )
        self.status_message.emit(f"Created mod package {folder}")

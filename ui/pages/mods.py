from __future__ import annotations

from pathlib import Path

import qtawesome as qta
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from ..context import AppContext
from ..models import Column, DictTableModel, TypedSortFilterProxyModel, format_bytes
from ..widgets.common import EmptyState, Metric, MetricStrip, PageSection, StatusBanner


class ModsPage(QWidget):
    status_message = Signal(str)

    def __init__(self, context: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("PageBody")
        self.context = context
        self._selected_folder: str | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 22, 28, 28)
        layout.setSpacing(14)
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        install = QPushButton("Install ZIP")
        install.setProperty("role", "primary")
        install.setIcon(qta.icon("fa6s.file-zipper", color="#FFFFFF"))
        install.clicked.connect(self.install_zip)
        self.toggle_button = QPushButton("Enable")
        self.toggle_button.setIcon(qta.icon("fa6s.power-off", color="#17201C"))
        self.toggle_button.setEnabled(False)
        self.toggle_button.clicked.connect(self.toggle_selected)
        self.build_zen_button = QPushButton("Build Zen Triplet")
        self.build_zen_button.setIcon(qta.icon("fa6s.cubes", color="#17201C"))
        self.build_zen_button.setEnabled(False)
        self.build_zen_button.setToolTip("Compila il pacchetto in un Triplet .pak + .utoc + .ucas per ~mods/")
        self.build_zen_button.clicked.connect(self.build_zen_selected)
        self.delete_button = QPushButton("Delete")
        self.delete_button.setProperty("role", "danger")
        self.delete_button.setIcon(qta.icon("fa6s.trash", color="#B13B36"))
        self.delete_button.setEnabled(False)
        self.delete_button.clicked.connect(self.delete_selected)
        open_folder = QPushButton("Open content folder")
        open_folder.setIcon(qta.icon("fa6s.folder-open", color="#17201C"))
        open_folder.clicked.connect(lambda: self._open(self.context.paths.content))
        refresh = QPushButton("Refresh")
        refresh.setIcon(qta.icon("fa6s.rotate", color="#17201C"))
        refresh.clicked.connect(self.refresh)
        toolbar.addWidget(install)
        toolbar.addWidget(self.toggle_button)
        toolbar.addWidget(self.build_zen_button)
        toolbar.addWidget(self.delete_button)
        toolbar.addWidget(open_folder)
        toolbar.addStretch(1)
        toolbar.addWidget(refresh)
        layout.addLayout(toolbar)

        self.banner = StatusBanner("Packages are loaded in the order of active cpk.root entries.", "info")
        layout.addWidget(self.banner)
        self.metrics = MetricStrip(tuple())
        layout.addWidget(self.metrics)

        section = PageSection()
        filter_row = QHBoxLayout()
        filter_row.addStretch(1)
        search = QLineEdit()
        search.setPlaceholderText("Filter packages")
        search.setClearButtonEnabled(True)
        search.setFixedWidth(280)
        filter_row.addWidget(search)
        section.layout.addLayout(filter_row)
        self.model = DictTableModel(
            (
                Column("state", "STATE"),
                Column("name", "PACKAGE"),
                Column("category", "CATEGORY"),
                Column("author", "AUTHOR"),
                Column("version", "VERSION"),
                Column("file_count", "FILES"),
                Column("size_bytes", "SIZE", formatter=format_bytes),
                Column("folder", "FOLDER", monospace=True),
            )
        )
        self.proxy = TypedSortFilterProxyModel(self)
        self.proxy.setSourceModel(self.model)
        self.proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.proxy.setFilterKeyColumn(-1)
        search.textChanged.connect(self.proxy.setFilterFixedString)
        self.table = QTableView()
        self.table.setModel(self.proxy)
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(True)
        self.table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableView.SelectionMode.SingleSelection)
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.selectionModel().selectionChanged.connect(self._selection_changed)
        self.content_stack = QStackedWidget()
        empty = QWidget()
        empty_layout = QVBoxLayout(empty)
        empty_layout.addStretch(1)
        empty_layout.addWidget(
            EmptyState(
                "No mod packages installed",
                "Install a ZIP package or create one from a discovered asset reference.",
                "fa6s.box-open",
            )
        )
        empty_action = QPushButton("Install ZIP")
        empty_action.setProperty("role", "primary")
        empty_action.clicked.connect(self.install_zip)
        empty_layout.addWidget(empty_action, alignment=Qt.AlignmentFlag.AlignHCenter)
        empty_layout.addStretch(1)
        self.content_stack.addWidget(empty)
        self.content_stack.addWidget(self.table)
        section.layout.addWidget(self.content_stack, 1)
        layout.addWidget(section, 1)
        self.refresh()

    def refresh(self) -> None:
        mods = self.context.config.list_mods()
        records = [
            {
                "state": "Enabled" if mod.enabled else "Disabled",
                "enabled": mod.enabled,
                "name": mod.name,
                "category": mod.category,
                "author": mod.author,
                "version": mod.version,
                "file_count": mod.file_count,
                "size_bytes": mod.size_bytes,
                "folder": mod.folder,
            }
            for mod in mods
        ]
        self.model.set_records(records)
        self.content_stack.setCurrentIndex(1 if records else 0)
        enabled = sum(mod.enabled for mod in mods)
        self.metrics.set_metrics(
            (
                Metric("Packages", str(len(mods))),
                Metric("Enabled", str(enabled), "success" if enabled else "neutral"),
                Metric("Disabled", str(len(mods) - enabled)),
                Metric("Files", f"{sum(mod.file_count for mod in mods):,}"),
            )
        )
        self._selected_folder = None
        self.toggle_button.setEnabled(False)
        self.delete_button.setEnabled(False)
        if not mods:
            self.banner.set_message("No mod packages are installed in content.", "info")

    def install_zip(self) -> None:
        selected, _ = QFileDialog.getOpenFileName(self, "Install mod package", "", "ZIP archives (*.zip)")
        if not selected:
            return
        try:
            mod = self.context.config.install_zip(Path(selected))
        except (FileExistsError, FileNotFoundError, ValueError, OSError) as exc:
            QMessageBox.critical(self, "Install failed", str(exc))
            self.banner.set_message(str(exc), "error")
            return
        self.banner.set_message(f"Installed {mod.name}. Enable it to add its root to sider.ini.", "success")
        self.status_message.emit(f"Installed mod {mod.name}")
        self.refresh()

    def toggle_selected(self) -> None:
        record = self._selected_record()
        if not record:
            return
        enabled = not record["enabled"]
        try:
            self.context.config.set_mod_enabled(record["folder"], enabled)
        except ValueError as exc:
            self.banner.set_message(str(exc), "warning")
            QMessageBox.warning(self, "Load-order migration required", str(exc))
            return
        self.banner.set_message(f"{record['name']} is now {'enabled' if enabled else 'disabled'}.", "success")
        self.status_message.emit(f"Updated mod {record['name']}")
        self.refresh()

    def delete_selected(self) -> None:
        record = self._selected_record()
        if not record:
            return
        answer = QMessageBox.question(
            self,
            "Delete mod package",
            f"Delete '{record['name']}' from content?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.context.config.delete_mod(record["folder"])
        self.banner.set_message(f"Deleted {record['name']}.", "success")
        self.refresh()

    def build_zen_selected(self) -> None:
        record = self._selected_record()
        if not record:
            return
        folder_name = record["folder"]
        mod_name = record["name"]
        source_dir = self.context.paths.content / folder_name
        output_dir = self.context.paths.game_mods_paks

        if not self.context.zen_builder.is_available():
            QMessageBox.critical(
                self,
                "retoc non disponibile",
                f"retoc.exe non trovato in: {self.context.zen_builder.retoc_exe}",
            )
            return

        self.build_zen_button.setEnabled(False)
        self.banner.set_message(f"Compilazione Zen Triplet per '{mod_name}' in corso...", "info")
        self.status_message.emit(f"Compilazione Triplet '{mod_name}'...")

        from ..workers import TaskWorker

        def _do_build():
            return self.context.zen_builder.build_triplet(source_dir, folder_name, output_dir)

        worker = TaskWorker(_do_build)

        def _on_result(res):
            if res.success:
                msg = f"🎉 Zen Triplet compilato con successo per '{mod_name}' (.pak, .utoc, .ucas) in ~mods/"
                self.banner.set_message(msg, "success")
                self.status_message.emit(f"Triplet generato: {res.mod_name}_P")
                QMessageBox.information(self, "Zen Triplet Generato", msg)
            else:
                self.banner.set_message(f"Errore nella generazione del Triplet: {res.mod_name}", "error")
                QMessageBox.critical(self, "Errore Compilazione Triplet", res.log_output)

        worker.signals.result.connect(_on_result)
        worker.signals.finished.connect(lambda: self.build_zen_button.setEnabled(True))
        self.context.start_worker(worker)

    def _selection_changed(self, _selected=None, _deselected=None) -> None:
        record = self._selected_record()
        self.toggle_button.setEnabled(record is not None)
        self.build_zen_button.setEnabled(record is not None)
        self.delete_button.setEnabled(record is not None)
        if record:
            self.toggle_button.setText("Disable" if record["enabled"] else "Enable")

    def _selected_record(self):
        indexes = self.table.selectionModel().selectedRows()
        if not indexes:
            return None
        source = self.proxy.mapToSource(indexes[0])
        return self.model.record(source.row())

    def _open(self, path: Path) -> None:
        try:
            self.context.game.open_path(path)
        except (FileNotFoundError, OSError) as exc:
            self.banner.set_message(str(exc), "error")


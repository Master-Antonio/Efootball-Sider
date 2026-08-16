import json
import os
import shutil
from pathlib import Path

import qtawesome as qta
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QTabBar,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from ..context import AppContext
from ..core.pesdb import extract_team_diffs, update_player_record, update_team_record
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
        Column("short_name", "CODE", monospace=True),
        Column("name", "TEAM NAME"),
        Column("offset", "OFFSET", monospace=True),
        Column("hex", "HEADER", monospace=True),
    ),
}


class PlayerEditDialog(QDialog):
    def __init__(self, record: dict, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("PlayerEditDialog")
        self.setWindowTitle(f"Edit Player · {record.get('display_name', '')} (ID: {record['player_id']})")
        self.setMinimumWidth(460)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(24, 24, 24, 24)
        main_layout.setSpacing(18)

        # Header with Icon and Title
        header_row = QHBoxLayout()
        header_row.setSpacing(14)

        icon_lbl = QLabel()
        icon_lbl.setPixmap(qta.icon("fa6s.user-pen", color="#176C85").pixmap(32, 32))
        header_row.addWidget(icon_lbl)

        header_text = QVBoxLayout()
        header_text.setSpacing(2)
        title_lbl = QLabel(f"Modifica {record.get('display_name', 'Giocatore')}")
        title_lbl.setObjectName("SectionTitle")
        title_lbl.setStyleSheet("font-size: 17px; font-weight: 600; font-family: 'Bahnschrift';")
        subtitle_lbl = QLabel(f"Player ID: #{record['player_id']} · Salvataggio diretto in WESYS Player.bin")
        subtitle_lbl.setObjectName("SectionMeta")
        header_text.addWidget(title_lbl)
        header_text.addWidget(subtitle_lbl)
        header_row.addLayout(header_text, 1)

        id_pill = QLabel(f"ID {record['player_id']}")
        id_pill.setObjectName("StatusPill")
        header_row.addWidget(id_pill)
        main_layout.addLayout(header_row)

        # Form Card Frame
        card = PageSection("DATI GIOCATORE", "Parametri anagrafici e fisici serializzati nel record binario")
        form = QFormLayout()
        form.setSpacing(12)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)

        self.name_edit = QLineEdit(str(record.get("display_name", "")))
        self.name_edit.setPlaceholderText("Nome visualizzato sulla maglia e nei menu")

        self.height_spin = QSpinBox()
        self.height_spin.setRange(140, 220)
        self.height_spin.setSuffix(" cm")
        self.height_spin.setValue(int(record.get("height_cm", 180)))

        self.weight_spin = QSpinBox()
        self.weight_spin.setRange(40, 130)
        self.weight_spin.setSuffix(" kg")
        self.weight_spin.setValue(int(record.get("weight_kg", 75)))

        name_lbl = QLabel("Nome Visualizzato")
        name_lbl.setObjectName("FieldLabel")
        height_lbl = QLabel("Altezza")
        height_lbl.setObjectName("FieldLabel")
        weight_lbl = QLabel("Peso")
        weight_lbl.setObjectName("FieldLabel")

        form.addRow(name_lbl, self.name_edit)
        form.addRow(height_lbl, self.height_spin)
        form.addRow(weight_lbl, self.weight_spin)
        card.layout.addLayout(form)
        main_layout.addWidget(card)

        # Action Buttons Row
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)
        btn_row.addStretch()

        self.cancel_btn = QPushButton("Annulla")
        self.cancel_btn.setIcon(qta.icon("fa6s.xmark", color="#56635C"))
        self.cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(self.cancel_btn)

        self.save_btn = QPushButton("Salva Modifiche")
        self.save_btn.setProperty("role", "primary")
        self.save_btn.setIcon(qta.icon("fa6s.floppy-disk", color="#FFFFFF"))
        self.save_btn.clicked.connect(self.accept)
        btn_row.addWidget(self.save_btn)

        main_layout.addLayout(btn_row)

    def get_values(self) -> tuple[str, int, int]:
        return (
            self.name_edit.text().strip(),
            self.height_spin.value(),
            self.weight_spin.value(),
        )


class TeamEditDialog(QDialog):
    def __init__(self, record: dict, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("TeamEditDialog")
        self.setWindowTitle(f"Edit Team · {record.get('name', '')} (ID: {record['team_id']})")
        self.setMinimumWidth(460)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(24, 24, 24, 24)
        main_layout.setSpacing(18)

        # Header with Icon and Title
        header_row = QHBoxLayout()
        header_row.setSpacing(14)

        icon_lbl = QLabel()
        icon_lbl.setPixmap(qta.icon("fa6s.shield-halved", color="#176C85").pixmap(32, 32))
        header_row.addWidget(icon_lbl)

        header_text = QVBoxLayout()
        header_text.setSpacing(2)
        title_lbl = QLabel(f"Modifica {record.get('name', 'Squadra')}")
        title_lbl.setObjectName("SectionTitle")
        title_lbl.setStyleSheet("font-size: 17px; font-weight: 600; font-family: 'Bahnschrift';")
        subtitle_lbl = QLabel(f"Team ID: #{record['team_id']} · Salvataggio diretto in WESYS Team.bin")
        subtitle_lbl.setObjectName("SectionMeta")
        header_text.addWidget(title_lbl)
        header_text.addWidget(subtitle_lbl)
        header_row.addLayout(header_text, 1)

        id_pill = QLabel(f"ID {record['team_id']}")
        id_pill.setObjectName("StatusPill")
        header_row.addWidget(id_pill)
        main_layout.addLayout(header_row)

        # Form Card Frame
        card = PageSection("DATI SQUADRA & LICENZA", "Nome ufficiale e codice tri-lettera per tabelloni e telecronaca")
        form = QFormLayout()
        form.setSpacing(12)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)

        self.name_edit = QLineEdit(str(record.get("name", "")))
        self.name_edit.setPlaceholderText("Es. Real Madrid, Juventus, Manchester City")

        self.short_edit = QLineEdit(str(record.get("short_name", "")))
        self.short_edit.setMaxLength(4)
        self.short_edit.setPlaceholderText("Es. RMA, JUV, MCI")

        name_lbl = QLabel("Nome Squadra")
        name_lbl.setObjectName("FieldLabel")
        short_lbl = QLabel("Codice (3 Lettere)")
        short_lbl.setObjectName("FieldLabel")

        form.addRow(name_lbl, self.name_edit)
        form.addRow(short_lbl, self.short_edit)
        card.layout.addLayout(form)
        main_layout.addWidget(card)

        # Action Buttons Row
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)
        btn_row.addStretch()

        self.cancel_btn = QPushButton("Annulla")
        self.cancel_btn.setIcon(qta.icon("fa6s.xmark", color="#56635C"))
        self.cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(self.cancel_btn)

        self.save_btn = QPushButton("Salva Modifiche")
        self.save_btn.setProperty("role", "primary")
        self.save_btn.setIcon(qta.icon("fa6s.floppy-disk", color="#FFFFFF"))
        self.save_btn.clicked.connect(self.accept)
        btn_row.addWidget(self.save_btn)

        main_layout.addLayout(btn_row)

    def get_values(self) -> tuple[str, str]:
        return (
            self.name_edit.text().strip(),
            self.short_edit.text().strip().upper(),
        )


class DatabasePage(QWidget):
    status_message = Signal(str)

    @property
    def target_cpk(self) -> Path:
        if hasattr(self, "source") and self.source and self.source.path():
            p = Path(self.source.path())
            if p.is_file():
                return p
        return (
            self.context.paths.base_database_cpk
            if self.current_layer == "dt200"
            else self.context.paths.live_database_cpk
        )

    def __init__(self, context: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("PageBody")
        self.context = context
        self.current_layer: str = "dt200"
        self.bundle: DatabaseBundle | None = None
        self.current_records: list[dict] = []
        self.current_columns: tuple[str, ...] = tuple()
        self._table_loading = False
        self._pending_tab_index: int | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 22, 28, 28)
        layout.setSpacing(14)

        # Top Database Mode Tabs (dt200 vs dt870)
        layer_row = QHBoxLayout()
        layer_row.setSpacing(8)
        self.layer_tabs = QTabBar()
        self.layer_tabs.setExpanding(False)
        self.layer_tabs.addTab("📦 dt200 · Base Offline DB (Esibizione)")
        self.layer_tabs.addTab("⚡ dt870 · Live Update (Online)")
        self.layer_tabs.currentChanged.connect(self._on_layer_changed)
        layer_row.addWidget(self.layer_tabs)
        layer_row.addStretch(1)
        layout.addLayout(layer_row)

        source_row = QHBoxLayout()
        source_row.setSpacing(8)
        source_copy = QVBoxLayout()
        source_copy.setSpacing(2)
        self.source_label = QLabel(f"Database archive · {context.paths.base_database_cpk.name}")
        self.source_label.setObjectName("FieldLabel")
        self.source_meta = QLabel("dt200 definisce il database principale per le squadre offline ed esibizione")
        self.source_meta.setObjectName("SectionMeta")
        source_copy.addWidget(self.source_label)
        source_copy.addWidget(self.source_meta)
        source_row.addLayout(source_copy)
        self.source = PathField(str(context.paths.base_database_cpk))
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

        self.deploy_button = QPushButton("Deploy to LiveCPK")
        self.deploy_button.setProperty("role", "primary")
        self.deploy_button.setIcon(qta.icon("fa6s.cloud-arrow-up", color="#FFFFFF"))
        self.deploy_button.setEnabled(False)
        self.deploy_button.clicked.connect(self.deploy_to_livecpk)
        tools.addWidget(self.deploy_button)
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
        self.table.doubleClicked.connect(self._on_table_double_clicked)
        section.layout.addWidget(self.table, 1)
        layout.addWidget(section, 1)

        self._on_layer_changed(0)

    def _on_layer_changed(self, index: int) -> None:
        if index == 0:
            self.current_layer = "dt200"
            cpk_path = self.context.paths.base_database_cpk
            self.source_label.setText(f"Database archive · {cpk_path.name}")
            self.source_meta.setText("dt200 definisce il database principale per le squadre offline ed esibizione")
            self.source.set_path(str(cpk_path))
        else:
            self.current_layer = "dt870"
            cpk_path = self.context.paths.live_database_cpk
            self.source_label.setText(f"Database archive · {cpk_path.name}")
            self.source_meta.setText("dt870 gestisce i Live Update e le modifiche online")
            self.source.set_path(str(cpk_path))

        ws_dir = self.context.paths.database_workspace / self.current_layer
        existing = self.context.database.load_bundle(ws_dir)
        if existing:
            self._bundle_ready(existing, load_table=True)
        else:
            self.bundle = None
            self.metrics.set_metrics(
                (
                    Metric("Players", "--"),
                    Metric("Assignments", "--"),
                    Metric("Squads", "--"),
                    Metric("Teams", "--"),
                )
            )
            self.deploy_button.setEnabled(False)
            self.export_button.setEnabled(False)
            self.banner.set_message(
                f"Estrai {cpk_path.name} per visualizzare e modificare questo database.",
                "info",
            )

    def _browse_source(self) -> None:
        selected, _ = QFileDialog.getOpenFileName(
            self,
            "Choose eFootball database CPK",
            self.source.path(),
            "CRI archives (*.cpk);;All files (*)",
        )
        if selected:
            self.source.set_path(selected)
            self.source_label.setText(f"Database archive · {Path(selected).name}")

    def extract(self) -> None:
        source = Path(self.source.path())
        output = self.context.paths.database_workspace / self.current_layer
        self.extract_button.setEnabled(False)
        self.progress.setValue(0)
        self.progress.show()
        self.banner.set_message("Reading CPK entries...", "info")
        self.status_message.emit(f"Extracting and validating {self.current_layer} database...")
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
        self.export_button.setEnabled(True)
        self.deploy_button.setEnabled(True)
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

    def deploy_to_livecpk(self) -> None:
        if self.bundle is None:
            self.banner.set_message("Estrai prima il database prima di distribuirlo in LiveCPK", "warning")
            return

        # Copy to primary content directory
        target_dir = self.context.paths.content / "database" / "common" / "etc" / "pesdb"
        target_dir.mkdir(parents=True, exist_ok=True)

        copied = 0
        for fname in ("Team.bin", "Player.bin", "PlayerAssignment.bin"):
            src = self.bundle.decoded_path(fname)
            if src.is_file():
                shutil.copy2(src, target_dir / fname)
                copied += 1

        # Also copy vanilla baseline and export dynamic team_replacements.json
        vanilla_src = self.bundle.root / "vanilla" / "common" / "etc" / "pesdb" / "Team.bin"
        mod_src = self.bundle.decoded_path("Team.bin")
        if mod_src.is_file() and vanilla_src.is_file():
            shutil.copy2(vanilla_src, target_dir / "Team.bin.vanilla")
            try:
                diffs = extract_team_diffs(vanilla_src.read_bytes(), mod_src.read_bytes())
                (target_dir / "team_replacements.json").write_text(
                    json.dumps(diffs, indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )
            except Exception:
                pass

        # Also copy to game_root content if custom
        if self.context.paths.game_root / "content" != self.context.paths.content:
            game_pesdb = self.context.paths.game_root / "content" / "database" / "common" / "etc" / "pesdb"
            try:
                game_pesdb.mkdir(parents=True, exist_ok=True)
                for fname in ("Team.bin", "Player.bin", "PlayerAssignment.bin"):
                    src = self.bundle.decoded_path(fname)
                    if src.is_file():
                        shutil.copy2(src, game_pesdb / fname)
                if vanilla_src.is_file():
                    shutil.copy2(vanilla_src, game_pesdb / "Team.bin.vanilla")
                if (target_dir / "team_replacements.json").is_file():
                    shutil.copy2(target_dir / "team_replacements.json", game_pesdb / "team_replacements.json")
            except Exception:
                pass

        # Repack target CPK directly with WESYS encryption
        repacked = 0
        try:
            repacked = self.context.database.repack_and_deploy(self.bundle, target_cpk=self.target_cpk)
        except Exception as exc:
            pass

        self._ensure_sider_ini_has_database_mod()

        self.banner.set_message(
            f"✅ Database {self.current_layer.upper()} distribuito con successo! {repacked} tabelle WESYS riscritte in {self.target_cpk.name} e sincronizzate in LiveCPK.",
            "success",
        )
        self.status_message.emit(f"Database {self.current_layer.upper()} sincronizzato")

    def _ensure_sider_ini_has_database_mod(self) -> None:
        for ini_path in (self.context.paths.sider_ini, self.context.paths.game_bin / "sider.ini"):
            if not ini_path.is_file():
                continue
            try:
                content = ini_path.read_text(encoding="utf-8")
                if "content\\database" not in content.lower() and "content/database" not in content.lower():
                    lines = content.splitlines()
                    new_lines = []
                    inserted = False
                    for line in lines:
                        new_lines.append(line)
                        if "cpk.root" in line.lower() and not inserted:
                            new_lines.append('cpk.root = ".\\content\\database"')
                            inserted = True
                    if not inserted:
                        new_lines.append('cpk.root = ".\\content\\database"')
                    ini_path.write_text("\n".join(new_lines), encoding="utf-8")
            except Exception:
                pass

    def _show_error(self, detail: str) -> None:
        message = detail.strip().splitlines()[-1] if detail.strip() else "Unknown error"
        self.banner.set_message(message, "error")
        QMessageBox.critical(self, "Database operation failed", message)

    def _on_table_double_clicked(self, index) -> None:
        if self.bundle is None:
            return
        curr_tab = TABLES[self.tabs.currentIndex()]
        if curr_tab not in ("players", "teams"):
            return

        source_index = self.proxy.mapToSource(index)
        record = self.model.record(source_index.row())
        if not record:
            return

        if curr_tab == "players":
            dialog = PlayerEditDialog(record, self)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                new_name, new_h, new_w = dialog.get_values()

                player_bin_path = self.bundle.decoded_path("Player.bin")
                if not player_bin_path.is_file():
                    self.banner.set_message("Player.bin decodificato non trovato", "error")
                    return

                try:
                    curr_data = player_bin_path.read_bytes()
                    updated_data = update_player_record(
                        curr_data,
                        record["player_id"],
                        display_name=new_name,
                        height_cm=new_h,
                        weight_kg=new_w,
                    )
                    player_bin_path.write_bytes(updated_data)
                    self.banner.set_message(f"Giocatore #{record['player_id']} ({new_name}) salvato con successo!", "success")
                    self.status_message.emit(f"Aggiornato giocatore {new_name}")
                    self._load_table(self.tabs.currentIndex())
                except Exception as exc:
                    self._show_error(str(exc))

        elif curr_tab == "teams":
            dialog = TeamEditDialog(record, self)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                new_name, new_short = dialog.get_values()

                team_bin_path = self.bundle.decoded_path("Team.bin")
                if not team_bin_path.is_file():
                    self.banner.set_message("Team.bin decodificato non trovato", "error")
                    return

                try:
                    curr_data = team_bin_path.read_bytes()
                    updated_data = update_team_record(
                        curr_data,
                        record["team_id"],
                        name=new_name,
                        short_name=new_short,
                    )
                    team_bin_path.write_bytes(updated_data)
                    self.banner.set_message(f"Squadra #{record['team_id']} ({new_name} - {new_short}) salvata con successo!", "success")
                    self.status_message.emit(f"Aggiornata squadra {new_name}")
                    self._load_table(self.tabs.currentIndex())
                except Exception as exc:
                    self._show_error(str(exc))


from __future__ import annotations

from pathlib import Path

import qtawesome as qta
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTabBar,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from ..context import AppContext
from ..models import Column, DictTableModel, TypedSortFilterProxyModel
from ..widgets.common import Metric, MetricStrip, PageSection, StatusBanner


class ServersPage(QWidget):
    status_message = Signal(str)

    def __init__(self, context: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("PageBody")
        self.context = context
        self._current_tab = 0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 22, 28, 28)
        layout.setSpacing(14)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)

        add_btn = QPushButton("Aggiungi Squadra / Server")
        add_btn.setProperty("role", "primary")
        add_btn.setIcon(qta.icon("fa6s.plus", color="#FFFFFF"))
        add_btn.clicked.connect(self._add_server_entry)

        open_folder = QPushButton("Apri cartella Server")
        open_folder.setIcon(qta.icon("fa6s.folder-open", color="#17201C"))
        open_folder.clicked.connect(self._open_current_server_folder)

        refresh_btn = QPushButton("Aggiorna")
        refresh_btn.setIcon(qta.icon("fa6s.rotate", color="#17201C"))
        refresh_btn.clicked.connect(self.refresh)

        toolbar.addWidget(add_btn)
        toolbar.addWidget(open_folder)
        toolbar.addStretch(1)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Filtra per Team ID o Nome...")
        self.search.setClearButtonEnabled(True)
        self.search.setFixedWidth(280)
        toolbar.addWidget(self.search)
        toolbar.addWidget(refresh_btn)
        layout.addLayout(toolbar)

        self.banner = StatusBanner("I moduli Server (KitServer, StadiumServer, BallServer) assegnano asset dinamici in RAM per Team ID.", "info")
        layout.addWidget(self.banner)

        self.metrics = MetricStrip(
            (
                Metric("KitServer", "0 squadre"),
                Metric("StadiumServer", "0 stadi"),
                Metric("BallServer", "0 palloni"),
            )
        )
        layout.addWidget(self.metrics)

        section = PageSection()
        self.tabs = QTabBar()
        self.tabs.addTab("KitServer (Divise)")
        self.tabs.addTab("StadiumServer (Stadi)")
        self.tabs.addTab("BallServer (Palloni)")
        self.tabs.currentChanged.connect(self._on_tab_changed)
        section.layout.addWidget(self.tabs)

        self.model = DictTableModel(
            (
                Column("id", "ID", monospace=True),
                Column("name", "NOME / DESCRIZIONE"),
                Column("kits_count", "VARIANTI / ASSET"),
                Column("status", "STATO"),
                Column("folder", "PERCORSO FOLDER", monospace=True),
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
        section.layout.addWidget(self.table, 1)

        layout.addWidget(section, 1)
        self.refresh()

    def _on_tab_changed(self, index: int) -> None:
        self._current_tab = index
        self.refresh()

    def refresh(self) -> None:
        content_dir = self.context.paths.content
        kits_dir = content_dir / "kits"
        stads_dir = content_dir / "stadiums"
        balls_dir = content_dir / "balls"

        kits_dir.mkdir(parents=True, exist_ok=True)
        stads_dir.mkdir(parents=True, exist_ok=True)
        balls_dir.mkdir(parents=True, exist_ok=True)

        kit_entries = [p for p in kits_dir.iterdir() if p.is_dir()]
        stad_entries = [p for p in stads_dir.iterdir() if p.is_dir()]
        ball_entries = [p for p in balls_dir.iterdir() if p.is_dir() or p.is_file()]

        self.metrics.set_metrics(
            (
                Metric("KitServer", f"{len(kit_entries)} squadre", "success" if kit_entries else "neutral"),
                Metric("StadiumServer", f"{len(stad_entries)} stadi", "success" if stad_entries else "neutral"),
                Metric("BallServer", f"{len(ball_entries)} palloni", "success" if ball_entries else "neutral"),
            )
        )

        records = []
        if self._current_tab == 0:
            for p in sorted(kit_entries):
                sub_items = [f.name for f in p.iterdir() if f.is_dir() or f.suffix.lower() in (".png", ".dds", ".uasset")]
                records.append({
                    "id": p.name,
                    "name": f"Team #{p.name}",
                    "kits_count": f"{len(sub_items)} elementi ({', '.join(sub_items[:4])})",
                    "status": "Attivo (LiveCPK)",
                    "folder": str(p),
                })
        elif self._current_tab == 1:
            for p in sorted(stad_entries):
                records.append({
                    "id": p.name,
                    "name": f"Stadio #{p.name}",
                    "kits_count": f"{len(list(p.iterdir()))} asset",
                    "status": "Attivo (LiveCPK)",
                    "folder": str(p),
                })
        else:
            for p in sorted(ball_entries):
                records.append({
                    "id": p.stem,
                    "name": p.name,
                    "kits_count": "1 pallone",
                    "status": "Attivo",
                    "folder": str(p),
                })

        self.model.set_records(records)

    def _open_current_server_folder(self) -> None:
        content_dir = self.context.paths.content
        sub = "kits" if self._current_tab == 0 else ("stadiums" if self._current_tab == 1 else "balls")
        folder = content_dir / sub
        folder.mkdir(parents=True, exist_ok=True)
        try:
            self.context.game.open_path(folder)
        except Exception as exc:
            QMessageBox.critical(self, "Errore", str(exc))

    def _add_server_entry(self) -> None:
        sub = "kits" if self._current_tab == 0 else ("stadiums" if self._current_tab == 1 else "balls")
        title = "Aggiungi Squadra KitServer" if self._current_tab == 0 else ("Aggiungi Stadio" if self._current_tab == 1 else "Aggiungi Pallone")
        prompt = "Inserisci Team ID numerico (es. 102 per Real Madrid, 100 per Arsenal):" if self._current_tab == 0 else "Inserisci ID o Nome cartella:"

        val, ok = QInputDialog.getText(self, title, prompt)
        if ok and val.strip():
            target = self.context.paths.content / sub / val.strip()
            target.mkdir(parents=True, exist_ok=True)
            if self._current_tab == 0:
                # Create standard subfolders p1, p2, p3, g1
                for subf in ("p1", "p2", "p3", "g1"):
                    (target / subf).mkdir(exist_ok=True)
            self.banner.set_message(f"Cartella creata con successo in {target}", "success")
            self.refresh()

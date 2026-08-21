from __future__ import annotations

import os
import shutil
from pathlib import Path

import qtawesome as qta
from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QFileDialog,
    QHBoxLayout,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from ..context import AppContext
from ..services.paths import auto_detect_game_root
from ..widgets.common import Metric, MetricStrip, PageSection, PathField, StatusBanner


class SettingsPage(QWidget):
    status_message = Signal(str)

    def __init__(self, context: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("PageBody")
        self.context = context

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 22, 28, 28)
        layout.setSpacing(16)

        self.banner = StatusBanner()
        layout.addWidget(self.banner)

        # 1. Game Status Metrics
        self.metrics = MetricStrip(
            (
                Metric("eFootball Executable", "--"),
                Metric("CPK Archives", "--"),
                Metric("Sider DLL Status", "--"),
                Metric("Active Content", "--"),
            )
        )
        layout.addWidget(self.metrics)

        # 2. Game Installation Path Card
        game_section = PageSection(
            "PERCORSO DI INSTALLAZIONE GIOCO",
            "Cartella principale di eFootball contenente gli eseguibili Win64 e gli archivi CPK",
        )
        game_form = QVBoxLayout()
        game_form.setSpacing(10)

        game_path_row = QHBoxLayout()
        game_path_row.setSpacing(8)
        self.game_path_field = PathField(str(self.context.paths.game_root))
        self.game_path_field.browse.clicked.connect(self._browse_game_dir)
        game_path_row.addWidget(self.game_path_field, 1)

        self.autodetect_btn = QPushButton("Rileva da Steam")
        self.autodetect_btn.setIcon(qta.icon("fa6s.wand-magic-sparkles", color="#17201C"))
        self.autodetect_btn.clicked.connect(self._autodetect_game)
        game_path_row.addWidget(self.autodetect_btn)

        self.open_game_btn = QPushButton("Apri Cartella")
        self.open_game_btn.setIcon(qta.icon("fa6s.folder-open", color="#17201C"))
        self.open_game_btn.clicked.connect(self._open_game_folder)
        game_path_row.addWidget(self.open_game_btn)
        game_form.addLayout(game_path_row)

        # DLL Management buttons
        dll_btn_row = QHBoxLayout()
        dll_btn_row.setSpacing(10)

        self.install_dll_btn = QPushButton("Installa / Aggiorna Sider dxgi.dll nel Gioco")
        self.install_dll_btn.setProperty("role", "primary")
        self.install_dll_btn.setIcon(qta.icon("fa6s.download", color="#FFFFFF"))
        self.install_dll_btn.clicked.connect(self._install_sider_dll)
        dll_btn_row.addWidget(self.install_dll_btn)

        self.uninstall_dll_btn = QPushButton("Rimuovi Sider dal Gioco")
        self.uninstall_dll_btn.setIcon(qta.icon("fa6s.trash", color="#56635C"))
        self.uninstall_dll_btn.clicked.connect(self._uninstall_sider_dll)
        dll_btn_row.addWidget(self.uninstall_dll_btn)
        dll_btn_row.addStretch(1)

        game_form.addLayout(dll_btn_row)
        game_section.layout.addLayout(game_form)
        layout.addWidget(game_section)

        # 3. Content & Mods Location Card
        content_section = PageSection(
            "POSIZIONE CARTELLA MODS (CONTENT)",
            "Configura dove risiedono i pacchetti mod (database, maglie, stadi, palloni)",
        )
        content_form = QVBoxLayout()
        content_form.setSpacing(10)

        self.content_group = QButtonGroup(self)
        self.radio_game_content = QRadioButton(
            "Cartella di Gioco (Steam): <GameRoot>/content (Consigliato per modifiche dirette)"
        )
        self.radio_sider_content = QRadioButton(
            "Workspace Sider Studio: <SiderRoot>/content (Isolato da aggiornamenti Steam)"
        )
        self.radio_custom_content = QRadioButton("Percorso Personalizzato...")

        self.content_group.addButton(self.radio_game_content, 0)
        self.content_group.addButton(self.radio_sider_content, 1)
        self.content_group.addButton(self.radio_custom_content, 2)

        self.radio_game_content.toggled.connect(self._on_content_mode_changed)
        self.radio_sider_content.toggled.connect(self._on_content_mode_changed)
        self.radio_custom_content.toggled.connect(self._on_content_mode_changed)

        content_form.addWidget(self.radio_game_content)
        content_form.addWidget(self.radio_sider_content)
        content_form.addWidget(self.radio_custom_content)

        content_path_row = QHBoxLayout()
        content_path_row.setSpacing(8)
        self.content_path_field = PathField(str(self.context.paths.content))
        self.content_path_field.browse.clicked.connect(self._browse_content_dir)
        content_path_row.addWidget(self.content_path_field, 1)

        self.open_content_btn = QPushButton("Apri Content")
        self.open_content_btn.setIcon(qta.icon("fa6s.folder-open", color="#17201C"))
        self.open_content_btn.clicked.connect(self._open_content_folder)
        content_path_row.addWidget(self.open_content_btn)
        content_form.addLayout(content_path_row)

        content_section.layout.addLayout(content_form)
        layout.addWidget(content_section)

        # 4. Save & Apply Row
        save_row = QHBoxLayout()
        save_row.setSpacing(10)
        save_row.addStretch(1)

        self.save_btn = QPushButton("Salva e Applica Configurazione")
        self.save_btn.setProperty("role", "primary")
        self.save_btn.setIcon(qta.icon("fa6s.floppy-disk", color="#FFFFFF"))
        self.save_btn.clicked.connect(self._save_configuration)
        save_row.addWidget(self.save_btn)
        layout.addLayout(save_row)

        layout.addStretch(1)

        # Initial state load
        self._load_current_state()

    def _load_current_state(self) -> None:
        curr_content = str(self.context.paths.content).lower()
        game_content = str(self.context.paths.game_content).lower()
        repo_content = str(self.context.paths.repository / "content").lower()

        if curr_content == game_content:
            self.radio_game_content.setChecked(True)
        elif curr_content == repo_content:
            self.radio_sider_content.setChecked(True)
        else:
            self.radio_custom_content.setChecked(True)

        self._refresh_metrics()

    def _refresh_metrics(self) -> None:
        exe_valid = self.context.paths.game_exe.is_file()
        cpk_count = (
            len(list(self.context.paths.game_cpk.glob("*.cpk")))
            if self.context.paths.game_cpk.is_dir()
            else 0
        )
        dll_installed = self.context.paths.is_dll_installed()
        content_exists = self.context.paths.content.is_dir()

        self.metrics.set_metrics(
            (
                Metric(
                    "eFootball Executable",
                    "Rilevato (Win64)" if exe_valid else "Non trovato",
                    "success" if exe_valid else "danger",
                ),
                Metric(
                    "CPK Archives",
                    f"{cpk_count} archivi" if cpk_count else "Non trovati",
                    "success" if cpk_count else "warning",
                ),
                Metric(
                    "Sider DLL Status",
                    "Installata (dxgi.dll)" if dll_installed else "Non presente",
                    "success" if dll_installed else "warning",
                ),
                Metric(
                    "Active Content",
                    "Attiva" if content_exists else "Da creare",
                    "success" if content_exists else "warning",
                ),
            )
        )

        if exe_valid and dll_installed:
            self.banner.set_message("Ambiente di gioco e Sider configurati correttamente.", "success")
        elif exe_valid:
            self.banner.set_message(
                "eFootball rilevato. Installa o aggiorna la DLL dxgi.dll per attivare Sider.", "info"
            )
        else:
            self.banner.set_message(
                "Seleziona la cartella di installazione corretta di eFootball.", "warning"
            )

    def _on_content_mode_changed(self) -> None:
        if self.radio_game_content.isChecked():
            target = self.context.paths.game_root / "content"
            self.content_path_field.set_path(str(target))
            self.content_path_field.setEnabled(False)
        elif self.radio_sider_content.isChecked():
            target = self.context.paths.repository / "content"
            self.content_path_field.set_path(str(target))
            self.content_path_field.setEnabled(False)
        else:
            self.content_path_field.setEnabled(True)

    def _browse_game_dir(self) -> None:
        selected = QFileDialog.getExistingDirectory(
            self,
            "Seleziona la cartella di installazione di eFootball",
            self.game_path_field.path(),
        )
        if selected:
            self.game_path_field.set_path(selected)
            self._update_temporary_game_root(Path(selected))

    def _browse_content_dir(self) -> None:
        selected = QFileDialog.getExistingDirectory(
            self,
            "Seleziona la cartella Content per le Mod",
            self.content_path_field.path(),
        )
        if selected:
            self.content_path_field.set_path(selected)

    def _autodetect_game(self) -> None:
        detected = auto_detect_game_root()
        if detected:
            self.game_path_field.set_path(str(detected))
            self._update_temporary_game_root(detected)
            self.banner.set_message(f"eFootball rilevato automaticamente: {detected}", "success")
        else:
            self.banner.set_message(
                "Nessuna installazione Steam di eFootball rilevata automaticamente.", "warning"
            )

    def _update_temporary_game_root(self, new_root: Path) -> None:
        self.context.paths.game_root = new_root
        if self.radio_game_content.isChecked():
            self.content_path_field.set_path(str(new_root / "content"))
        self._refresh_metrics()

    def _open_game_folder(self) -> None:
        path = Path(self.game_path_field.path())
        if path.is_dir():
            os.startfile(str(path))

    def _open_content_folder(self) -> None:
        path = Path(self.content_path_field.path())
        path.mkdir(parents=True, exist_ok=True)
        os.startfile(str(path))

    def _install_sider_dll(self) -> None:
        src = self.context.paths.built_dll
        if not src.is_file():
            src = self.context.paths.root_dll
        if not src.is_file():
            self.banner.set_message("File dxgi.dll compilato non trovato.", "error")
            return

        dst_dir = self.context.paths.game_bin
        dst_dir.mkdir(parents=True, exist_ok=True)
        dst = dst_dir / "dxgi.dll"

        try:
            shutil.copy2(src, dst)
            # Also ensure sider.ini is in game bin
            if self.context.paths.sider_ini.is_file():
                shutil.copy2(self.context.paths.sider_ini, dst_dir / "sider.ini")
            self.banner.set_message(
                f"✅ Sider dxgi.dll e sider.ini installati con successo in {dst_dir}!", "success"
            )
            self._refresh_metrics()
        except Exception as exc:
            self.banner.set_message(f"Errore durante l'installazione della DLL: {exc}", "error")

    def _uninstall_sider_dll(self) -> None:
        dst = self.context.paths.game_dll
        if dst.is_file():
            try:
                dst.unlink()
                self.banner.set_message("Sider dxgi.dll rimosso dal gioco.", "info")
                self._refresh_metrics()
            except Exception as exc:
                self.banner.set_message(f"Impossibile rimuovere dxgi.dll: {exc}", "error")
        else:
            self.banner.set_message("Nessuna DLL Sider presente nel gioco.", "info")

    def _save_configuration(self) -> None:
        game_root = Path(self.game_path_field.path())
        content_root = Path(self.content_path_field.path())

        if not (game_root / "eFootball" / "Binaries" / "Win64" / "eFootball.exe").is_file():
            ans = QMessageBox.question(
                self,
                "Conferma Percorso Gioco",
                "Non è stato trovato 'eFootball.exe' nel percorso specificato. Vuoi salvare comunque?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if ans != QMessageBox.StandardButton.Yes:
                return

        self.context.paths.game_root = game_root
        self.context.paths.custom_content = content_root
        self.context.paths.save_settings(game_root=game_root, content_root=content_root)
        self.context.paths.ensure_workspace()

        self.banner.set_message("✅ Impostazioni e percorsi salvati con successo!", "success")
        self.status_message.emit("Configurazione salvata con successo")
        self._refresh_metrics()

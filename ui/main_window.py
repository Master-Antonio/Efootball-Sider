from __future__ import annotations

from dataclasses import dataclass

import qtawesome as qta
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from .context import AppContext
from .pages.assets import AssetsPage
from .pages.camera import CameraPage
from .pages.database import DatabasePage
from .pages.diagnostics import DiagnosticsPage
from .pages.mods import ModsPage
from .pages.overview import OverviewPage
from .pages.servers import ServersPage
from .pages.settings import SettingsPage


@dataclass(frozen=True)
class NavigationItem:
    title: str
    subtitle: str
    icon: str


NAVIGATION = (
    NavigationItem("Overview", "Runtime and workspace", "fa6s.gauge-high"),
    NavigationItem("Assets", "Discovery and overrides", "fa6s.cubes"),
    NavigationItem("Database", "Players, teams and squads", "fa6s.database"),
    NavigationItem("Mods", "Packages and load order", "fa6s.box-archive"),
    NavigationItem("Servers", "Kit, Stadium & Ball servers", "fa6s.shirt"),
    NavigationItem("Camera", "Match camera profiles", "fa6s.video"),
    NavigationItem("Diagnostics", "Logs and health checks", "fa6s.stethoscope"),
    NavigationItem("Settings", "Game paths and configuration", "fa6s.gear"),
)


class PlaceholderPage(QWidget):
    def __init__(self, item: NavigationItem, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("PageBody")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 28, 32, 32)
        layout.setSpacing(20)

        section = QFrame()
        section.setObjectName("PageSection")
        section_layout = QVBoxLayout(section)
        section_layout.setContentsMargins(20, 18, 20, 20)
        section_layout.setSpacing(6)

        title = QLabel(item.title)
        title.setObjectName("SectionTitle")
        description = QLabel(item.subtitle)
        description.setObjectName("SectionMeta")
        section_layout.addWidget(title)
        section_layout.addWidget(description)
        section_layout.addStretch(1)

        layout.addWidget(section, 1)


class MainWindow(QMainWindow):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.context = AppContext.create()
        self.setWindowTitle("eFootball Sider Studio")
        self.resize(1440, 900)
        self.setMinimumSize(1080, 700)

        self._page_title = QLabel()
        self._page_subtitle = QLabel()
        self._stack = QStackedWidget()
        self._nav_group = QButtonGroup(self)
        self._nav_group.setExclusive(True)
        self._runtime_status = QLabel()

        self.setStatusBar(self._build_status_bar())
        self.setCentralWidget(self._build_shell())
        self._install_shortcuts()
        self._select_page(0)
        self.refresh_runtime_status()

    def _build_shell(self) -> QWidget:
        canvas = QWidget()
        canvas.setObjectName("AppCanvas")
        shell = QHBoxLayout(canvas)
        shell.setContentsMargins(0, 0, 0, 0)
        shell.setSpacing(0)
        shell.addWidget(self._build_sidebar())
        shell.addWidget(self._build_workspace(), 1)
        return canvas

    def _build_sidebar(self) -> QWidget:
        sidebar = QWidget()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(236)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(0, 24, 0, 18)
        layout.setSpacing(4)

        brand_row = QHBoxLayout()
        brand_row.setContentsMargins(18, 0, 14, 22)
        brand_row.setSpacing(10)
        brand_icon = QLabel()
        brand_icon.setPixmap(qta.icon("fa6s.futbol", color="#C9EB63").pixmap(28, 28))
        brand_icon.setAccessibleName("eFootball Sider")
        brand_copy = QVBoxLayout()
        brand_copy.setSpacing(0)
        wordmark = QLabel("SIDER STUDIO")
        wordmark.setObjectName("Wordmark")
        edition = QLabel("eFootball 2027 toolkit")
        edition.setObjectName("Edition")
        brand_copy.addWidget(wordmark)
        brand_copy.addWidget(edition)
        brand_row.addWidget(brand_icon)
        brand_row.addLayout(brand_copy, 1)
        layout.addLayout(brand_row)

        for index, item in enumerate(NAVIGATION):
            button = QPushButton(item.title)
            button.setObjectName("NavButton")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setIcon(qta.icon(item.icon, color="#D6E0DA", color_active="#C9EB63"))
            button.setToolTip(item.subtitle)
            button.setAccessibleDescription(item.subtitle)
            button.clicked.connect(lambda _checked=False, page=index: self._select_page(page))
            self._nav_group.addButton(button, index)
            layout.addWidget(button)

        layout.addStretch(1)
        divider = QFrame()
        divider.setObjectName("SidebarDivider")
        layout.addWidget(divider)
        status = QLabel("Local workspace")
        status.setObjectName("SidebarStatus")
        status.setContentsMargins(18, 10, 18, 0)
        layout.addWidget(status)
        return sidebar

    def _build_workspace(self) -> QWidget:
        workspace = QWidget()
        workspace_layout = QVBoxLayout(workspace)
        workspace_layout.setContentsMargins(0, 0, 0, 0)
        workspace_layout.setSpacing(0)
        workspace_layout.addWidget(self._build_top_bar())

        overview = OverviewPage(self.context)
        overview.status_message.connect(lambda message: self._show_page_status(0, message))
        self._stack.addWidget(overview)
        assets = AssetsPage(self.context)
        assets.status_message.connect(lambda message: self._show_page_status(1, message))
        self._stack.addWidget(assets)
        database = DatabasePage(self.context)
        database.status_message.connect(lambda message: self._show_page_status(2, message))
        self._stack.addWidget(database)
        mods = ModsPage(self.context)
        mods.status_message.connect(lambda message: self._show_page_status(3, message))
        self._stack.addWidget(mods)
        servers = ServersPage(self.context)
        servers.status_message.connect(lambda message: self._show_page_status(4, message))
        self._stack.addWidget(servers)
        camera = CameraPage(self.context)
        camera.status_message.connect(lambda message: self._show_page_status(5, message))
        camera.navigate_requested.connect(self.select_page)
        self._stack.addWidget(camera)
        self._stack.addWidget(DiagnosticsPage(self.context))
        settings = SettingsPage(self.context)
        settings.status_message.connect(lambda message: self._show_page_status(7, message))
        self._stack.addWidget(settings)
        workspace_layout.addWidget(self._stack, 1)
        return workspace

    def _build_top_bar(self) -> QWidget:
        top_bar = QFrame()
        top_bar.setObjectName("TopBar")
        top_bar.setFixedHeight(86)
        layout = QHBoxLayout(top_bar)
        layout.setContentsMargins(32, 14, 28, 14)
        layout.setSpacing(16)

        copy = QVBoxLayout()
        copy.setSpacing(2)
        self._page_title.setObjectName("PageTitle")
        self._page_subtitle.setObjectName("PageSubtitle")
        copy.addWidget(self._page_title)
        copy.addWidget(self._page_subtitle)
        layout.addLayout(copy, 1)

        self._runtime_status.setObjectName("StatusPill")
        self._runtime_status.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        layout.addWidget(self._runtime_status)

        refresh = QPushButton()
        refresh.setIcon(qta.icon("fa6s.rotate", color="#17201C"))
        refresh.setToolTip("Refresh workspace status")
        refresh.setAccessibleName("Refresh workspace status")
        refresh.setFixedSize(44, 44)
        refresh.clicked.connect(self.refresh_runtime_status)
        layout.addWidget(refresh)
        return top_bar

    def _build_status_bar(self) -> QStatusBar:
        status_bar = QStatusBar()
        status_bar.showMessage("Ready")
        return status_bar

    def _install_shortcuts(self) -> None:
        for index in range(len(NAVIGATION)):
            shortcut = QShortcut(QKeySequence(f"Ctrl+{index + 1}"), self)
            shortcut.activated.connect(lambda page=index: self._select_page(page))

    def _select_page(self, index: int) -> None:
        item = NAVIGATION[index]
        self._stack.setCurrentIndex(index)
        self._page_title.setText(item.title)
        self._page_subtitle.setText(item.subtitle)
        button = self._nav_group.button(index)
        if button is not None:
            button.setChecked(True)
        self.statusBar().showMessage("Ready")

    def select_page(self, name: str) -> None:
        normalized = name.strip().lower()
        index = next(
            (index for index, item in enumerate(NAVIGATION) if item.title.lower() == normalized),
            None,
        )
        if index is None:
            raise ValueError(f"Unknown page: {name}")
        self._select_page(index)

    def refresh_runtime_status(self) -> None:
        status = self.context.game.status()
        if status.running:
            self._runtime_status.setText(f"Game running / PID {status.pid}")
            self._runtime_status.setProperty("tone", "success")
        else:
            self._runtime_status.setText("Game offline")
            self._runtime_status.setProperty("tone", "neutral")
        self._runtime_status.style().unpolish(self._runtime_status)
        self._runtime_status.style().polish(self._runtime_status)
        page = self._stack.currentWidget()
        refresh = getattr(page, "refresh", None)
        if callable(refresh):
            refresh()

    def _show_page_status(self, index: int, message: str) -> None:
        if self._stack.currentIndex() == index:
            self.statusBar().showMessage(message)

    def closeEvent(self, event) -> None:  # noqa: N802
        self.context.memory.close()
        super().closeEvent(event)

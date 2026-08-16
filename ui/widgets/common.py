from __future__ import annotations

from dataclasses import dataclass

import qtawesome as qta
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


class PageSection(QFrame):
    def __init__(self, title: str = "", meta: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("PageSection")
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(18, 16, 18, 18)
        self.layout.setSpacing(12)
        if title:
            header = QHBoxLayout()
            header.setSpacing(10)
            copy = QVBoxLayout()
            copy.setSpacing(1)
            title_label = QLabel(title)
            title_label.setObjectName("SectionTitle")
            copy.addWidget(title_label)
            if meta:
                meta_label = QLabel(meta)
                meta_label.setObjectName("SectionMeta")
                copy.addWidget(meta_label)
            header.addLayout(copy, 1)
            self.layout.addLayout(header)


@dataclass(frozen=True)
class Metric:
    label: str
    value: str
    tone: str = "neutral"


class MetricStrip(QFrame):
    def __init__(self, metrics: tuple[Metric, ...], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("MetricStrip")
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(18, 12, 18, 12)
        self._layout.setSpacing(0)
        self._value_labels: list[QLabel] = []
        self.set_metrics(metrics)

    def set_metrics(self, metrics: tuple[Metric, ...]) -> None:
        while self._layout.count():
            item = self._layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._value_labels.clear()
        for index, metric in enumerate(metrics):
            cell = QWidget()
            cell_layout = QVBoxLayout(cell)
            cell_layout.setContentsMargins(12, 2, 20, 2)
            cell_layout.setSpacing(1)
            value = QLabel(metric.value)
            value.setObjectName("MetricValue")
            value.setProperty("tone", metric.tone)
            label = QLabel(metric.label)
            label.setObjectName("MetricLabel")
            cell_layout.addWidget(value)
            cell_layout.addWidget(label)
            self._layout.addWidget(cell, 1)
            self._value_labels.append(value)
            if index < len(metrics) - 1:
                divider = QFrame()
                divider.setObjectName("MetricDivider")
                divider.setFixedWidth(1)
                self._layout.addWidget(divider)


class StatusBanner(QFrame):
    def __init__(self, text: str = "", tone: str = "info", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("StatusBanner")
        self.setProperty("tone", tone)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(8)
        self.icon = QLabel()
        self.label = QLabel(text)
        self.label.setObjectName("BannerText")
        self.label.setWordWrap(False)
        layout.addWidget(self.icon)
        layout.addWidget(self.label, 1)
        self.set_message(text, tone)

    def set_message(self, text: str, tone: str = "info") -> None:
        icons = {
            "info": "fa6s.circle-info",
            "success": "fa6s.circle-check",
            "warning": "fa6s.triangle-exclamation",
            "error": "fa6s.circle-xmark",
        }
        colors = {"info": "#176C85", "success": "#287A52", "warning": "#A96200", "error": "#B13B36"}
        self.setProperty("tone", tone)
        self.style().unpolish(self)
        self.style().polish(self)
        self.icon.setPixmap(
            qta.icon(icons.get(tone, icons["info"]), color=colors.get(tone, colors["info"])).pixmap(16, 16)
        )
        self.label.setText(text)
        self.setVisible(bool(text))


class EmptyState(QWidget):
    def __init__(
        self, title: str, detail: str, icon: str = "fa6s.inbox", parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setMinimumHeight(150)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 36, 24, 36)
        layout.setSpacing(6)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        symbol = QLabel()
        symbol.setPixmap(qta.icon(icon, color="#7A8780").pixmap(32, 32))
        symbol.setAlignment(Qt.AlignmentFlag.AlignCenter)
        heading = QLabel(title)
        heading.setObjectName("EmptyTitle")
        heading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        copy = QLabel(detail)
        copy.setObjectName("EmptyDetail")
        copy.setAlignment(Qt.AlignmentFlag.AlignCenter)
        copy.setWordWrap(True)
        copy.setMinimumHeight(42)
        layout.addWidget(symbol)
        layout.addWidget(heading)
        layout.addWidget(copy)


class PathField(QWidget):
    def __init__(self, value: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.edit = QLineEdit(value)
        self.edit.setToolTip(value)
        self.edit.setCursorPosition(0)
        self.edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.browse = QPushButton()
        self.browse.setIcon(qta.icon("fa6s.folder-open", color="#17201C"))
        self.browse.setToolTip("Choose a path")
        self.browse.setAccessibleName("Choose a path")
        self.browse.setFixedSize(44, 44)
        layout.addWidget(self.edit, 1)
        layout.addWidget(self.browse)

    def path(self) -> str:
        return self.edit.text().strip()

    def set_path(self, value: str) -> None:
        self.edit.setText(value)
        self.edit.setToolTip(value)
        self.edit.setCursorPosition(0)

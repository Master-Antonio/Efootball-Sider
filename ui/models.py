from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QSortFilterProxyModel, Qt
from PySide6.QtGui import QColor, QFont

Formatter = Callable[[Any], str]


def format_bytes(value: Any) -> str:
    size = float(value or 0)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


def format_value(value: Any) -> str:
    if value is None:
        return "Not decoded"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    return str(value)


@dataclass(frozen=True)
class Column:
    key: str
    label: str
    formatter: Formatter = format_value
    alignment: Qt.AlignmentFlag = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
    monospace: bool = False


class DictTableModel(QAbstractTableModel):
    def __init__(
        self,
        columns: tuple[Column, ...],
        records: list[dict[str, Any]] | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.columns = columns
        self.records = records or []
        self._mono_font = QFont("Cascadia Mono", 9)

    def rowCount(self, parent: QModelIndex | None = None) -> int:  # noqa: N802
        return 0 if parent is not None and parent.isValid() else len(self.records)

    def columnCount(self, parent: QModelIndex | None = None) -> int:  # noqa: N802
        return 0 if parent is not None and parent.isValid() else len(self.columns)

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self.records):
            return None
        column = self.columns[index.column()]
        value = self.records[index.row()].get(column.key)
        if role == Qt.ItemDataRole.DisplayRole:
            return column.formatter(value)
        if role == Qt.ItemDataRole.TextAlignmentRole:
            return column.alignment
        if role == Qt.ItemDataRole.FontRole and column.monospace:
            return self._mono_font
        if role == Qt.ItemDataRole.ForegroundRole and value is None:
            return QColor("#7A8780")
        if role == Qt.ItemDataRole.UserRole:
            return value
        return None

    def headerData(self, section: int, orientation, role=Qt.ItemDataRole.DisplayRole):  # noqa: N802
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal and 0 <= section < len(self.columns):
            return self.columns[section].label
        if orientation == Qt.Orientation.Vertical:
            return section + 1
        return None

    def sort(self, column: int, order=Qt.SortOrder.AscendingOrder) -> None:
        if not 0 <= column < len(self.columns):
            return
        self.layoutAboutToBeChanged.emit()
        key = self.columns[column].key
        reverse = order == Qt.SortOrder.DescendingOrder
        self.records.sort(
            key=lambda record: (
                record.get(key) is None,
                record.get(key).lower() if isinstance(record.get(key), str) else record.get(key),
            ),
            reverse=reverse,
        )
        self.layoutChanged.emit()

    def set_records(self, records: list[dict[str, Any]]) -> None:
        self.beginResetModel()
        self.records = records
        self.endResetModel()

    def record(self, row: int) -> dict[str, Any] | None:
        return self.records[row] if 0 <= row < len(self.records) else None


class TypedSortFilterProxyModel(QSortFilterProxyModel):
    def lessThan(self, left: QModelIndex, right: QModelIndex) -> bool:  # noqa: N802
        left_value = left.data(Qt.ItemDataRole.UserRole)
        right_value = right.data(Qt.ItemDataRole.UserRole)
        if left_value is None:
            return right_value is not None
        if right_value is None:
            return False
        if isinstance(left_value, (int, float)) and isinstance(right_value, (int, float)):
            return left_value < right_value
        return str(left_value).casefold() < str(right_value).casefold()

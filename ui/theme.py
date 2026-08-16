from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Palette:
    canvas: str = "#F2F5F3"
    surface: str = "#FFFFFF"
    surface_muted: str = "#E8EEEA"
    sidebar: str = "#17231D"
    sidebar_hover: str = "#23352B"
    ink: str = "#17201C"
    ink_secondary: str = "#56635C"
    ink_inverse: str = "#F7FAF8"
    border: str = "#CED8D2"
    border_strong: str = "#9EADA5"
    pitch: str = "#C9EB63"
    action: str = "#176C85"
    action_hover: str = "#11566B"
    success: str = "#287A52"
    warning: str = "#A96200"
    danger: str = "#B13B36"
    focus: str = "#176C85"


PALETTE = Palette()


def application_stylesheet(palette: Palette = PALETTE) -> str:
    return f"""
    * {{
        font-family: "Segoe UI", "Yu Gothic UI", "Microsoft YaHei UI", "Malgun Gothic";
        font-size: 13px;
        color: {palette.ink};
    }}
    QMainWindow, QWidget#AppCanvas, QDialog {{
        background: {palette.canvas};
        color: {palette.ink};
    }}
    QWidget#Sidebar {{
        background: {palette.sidebar};
        border: none;
    }}
    QLabel#Wordmark {{
        color: {palette.ink_inverse};
        font-family: "Bahnschrift";
        font-size: 18px;
        font-weight: 600;
    }}
    QLabel#Edition {{
        color: #AAB8B0;
        font-size: 11px;
    }}
    QPushButton#NavButton {{
        min-height: 42px;
        padding: 0 14px;
        color: #D6E0DA;
        background: transparent;
        border: none;
        border-left: 3px solid transparent;
        border-radius: 0;
        text-align: left;
        font-weight: 500;
    }}
    QPushButton#NavButton:hover {{
        background: {palette.sidebar_hover};
        color: {palette.ink_inverse};
    }}
    QPushButton#NavButton:checked {{
        background: {palette.sidebar_hover};
        color: {palette.pitch};
        border-left-color: {palette.pitch};
        font-weight: 650;
    }}
    QFrame#SidebarDivider {{
        background: #33483C;
        max-height: 1px;
    }}
    QLabel#SidebarStatus {{
        color: #B9C7BF;
        font-size: 11px;
    }}
    QFrame#TopBar {{
        background: {palette.surface};
        border-bottom: 1px solid {palette.border};
    }}
    QLabel#PageTitle {{
        font-family: "Bahnschrift";
        font-size: 23px;
        font-weight: 600;
        color: {palette.ink};
    }}
    QLabel#PageSubtitle {{
        color: {palette.ink_secondary};
        font-size: 12px;
    }}
    QLabel#StatusPill {{
        min-height: 24px;
        padding: 0 10px;
        color: {palette.ink};
        background: {palette.surface_muted};
        border: 1px solid {palette.border};
        border-radius: 4px;
        font-weight: 600;
    }}
    QLabel#StatusPill[tone="success"] {{
        color: {palette.success};
        background: #E5F2EA;
        border-color: #B5D5C2;
    }}
    QWidget#PageBody {{
        background: {palette.canvas};
    }}
    QFrame#PageSection {{
        background: {palette.surface};
        border: 1px solid {palette.border};
        border-radius: 6px;
    }}
    QLabel#SectionTitle {{
        font-family: "Bahnschrift";
        font-size: 15px;
        font-weight: 600;
    }}
    QLabel#SectionMeta {{
        color: {palette.ink_secondary};
        font-size: 11px;
    }}
    QLabel#FieldLabel {{
        font-weight: 650;
        color: {palette.ink};
    }}
    QFrame#MetricStrip {{
        background: {palette.surface};
        border: 1px solid {palette.border};
        border-radius: 6px;
    }}
    QLabel#MetricValue {{
        font-family: "Bahnschrift";
        font-size: 20px;
        font-weight: 600;
    }}
    QLabel#MetricValue[tone="success"] {{ color: {palette.success}; }}
    QLabel#MetricValue[tone="warning"] {{ color: {palette.warning}; }}
    QLabel#MetricValue[tone="error"] {{ color: {palette.danger}; }}
    QLabel#MetricLabel {{
        color: {palette.ink_secondary};
        font-size: 11px;
    }}
    QFrame#MetricDivider {{
        background: {palette.border};
        border: none;
    }}
    QFrame#StatusBanner {{
        min-height: 34px;
        background: #E6F0F3;
        border: 1px solid #B5CED7;
        border-radius: 4px;
    }}
    QFrame#StatusBanner[tone="success"] {{
        background: #E5F2EA;
        border-color: #B5D5C2;
    }}
    QFrame#StatusBanner[tone="warning"] {{
        background: #FFF1D9;
        border-color: #E4C48E;
    }}
    QFrame#StatusBanner[tone="error"] {{
        background: #F9E8E7;
        border-color: #DEB4B1;
    }}
    QLabel#BannerText {{
        color: {palette.ink};
        font-weight: 550;
    }}
    QLabel#EmptyTitle {{
        font-family: "Bahnschrift";
        font-size: 16px;
        font-weight: 600;
    }}
    QLabel#EmptyDetail {{
        color: {palette.ink_secondary};
        max-width: 420px;
    }}
    QPushButton {{
        min-height: 34px;
        padding: 0 12px;
        background: {palette.surface};
        border: 1px solid {palette.border_strong};
        border-radius: 4px;
        font-weight: 600;
    }}
    QPushButton:hover {{
        background: {palette.surface_muted};
        border-color: {palette.action};
    }}
    QPushButton:focus {{
        border: 2px solid {palette.focus};
    }}
    QPushButton[role="primary"] {{
        color: {palette.ink_inverse};
        background: {palette.action};
        border-color: {palette.action};
    }}
    QPushButton[role="primary"]:hover {{
        background: {palette.action_hover};
    }}
    QPushButton[role="danger"] {{
        color: {palette.danger};
        border-color: #D8A4A1;
    }}
    QPushButton#PresetButton:checked {{
        color: {palette.action};
        background: #E6F0F3;
        border: 2px solid {palette.action};
    }}
    QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
        min-height: 34px;
        padding: 0 9px;
        background: {palette.surface};
        border: 1px solid {palette.border_strong};
        border-radius: 4px;
        selection-background-color: {palette.action};
    }}
    QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
        border: 2px solid {palette.focus};
    }}
    QTableView, QTreeView, QListView {{
        background: {palette.surface};
        alternate-background-color: #F5F8F6;
        border: 1px solid {palette.border};
        border-radius: 4px;
        gridline-color: {palette.border};
        selection-background-color: #D9EAF0;
        selection-color: {palette.ink};
    }}
    QHeaderView::section {{
        min-height: 34px;
        padding: 0 8px;
        background: {palette.surface_muted};
        color: {palette.ink_secondary};
        border: none;
        border-right: 1px solid {palette.border};
        border-bottom: 1px solid {palette.border};
        font-size: 11px;
        font-weight: 650;
    }}
    QTabBar::tab {{
        min-height: 34px;
        padding: 0 14px;
        color: {palette.ink_secondary};
        background: transparent;
        border: none;
        border-bottom: 2px solid transparent;
        font-weight: 600;
    }}
    QTabBar::tab:hover {{
        color: {palette.ink};
        background: {palette.surface_muted};
    }}
    QTabBar::tab:selected {{
        color: {palette.action};
        border-bottom-color: {palette.action};
    }}
    QProgressBar {{
        background: {palette.border};
        border: none;
        border-radius: 2px;
    }}
    QProgressBar::chunk {{
        background: {palette.action};
        border-radius: 2px;
    }}
    QScrollBar:vertical {{
        width: 10px;
        background: transparent;
        margin: 2px;
    }}
    QScrollBar::handle:vertical {{
        min-height: 28px;
        background: {palette.border_strong};
        border-radius: 4px;
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        height: 0;
    }}
    QStatusBar {{
        min-height: 28px;
        background: {palette.surface};
        border-top: 1px solid {palette.border};
        color: {palette.ink_secondary};
    }}
    QToolTip {{
        color: {palette.ink_inverse};
        background: {palette.sidebar};
        border: 1px solid #52665B;
        padding: 5px 7px;
    }}
    """

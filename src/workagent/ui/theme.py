"""Colours, category palette and the application stylesheet (light theme)."""

from __future__ import annotations

SURFACE = "#fcfcfb"
PANEL = "#ffffff"
SIDEBAR = "#f4f3f0"
BORDER = "#e6e4df"
TEXT = "#0b0b0b"
TEXT_2 = "#52514e"
TEXT_3 = "#8a8983"
ACCENT = "#2a78d6"
ACCENT_DARK = "#1c5cab"
GOOD = "#008300"
WARN = "#c98500"
CRITICAL = "#e34948"

# Categorical slots in fixed order (validated reference palette). Identity never relies on
# colour alone: every chart using these also shows a text legend / labels.
CATEGORY_COLORS = {
    "development": "#2a78d6",
    "meeting": "#eb6834",
    "research": "#1baf7a",
    "documents": "#eda100",
    "communication": "#e87ba4",
    "design": "#008300",
    "browsing": "#4a3aa7",
    "other": "#a3a29c",       # folded: system + other
    "private": "#52514e",     # neutral, not a hue: details intentionally hidden
}
CATEGORY_LABELS = {
    "development": "Lập trình", "meeting": "Họp", "research": "Tra cứu",
    "documents": "Tài liệu", "communication": "Trao đổi", "design": "Thiết kế",
    "browsing": "Duyệt web", "other": "Khác", "private": "Riêng tư",
}
AWAY_COLOR = "#ecebe7"


def light_palette():
    """Explicit light palette so Windows dark mode doesn't bleed into unstyled surfaces."""
    from PySide6.QtGui import QColor, QPalette
    pal = QPalette()
    roles = {
        QPalette.ColorRole.Window: SURFACE, QPalette.ColorRole.WindowText: TEXT,
        QPalette.ColorRole.Base: PANEL, QPalette.ColorRole.AlternateBase: "#faf9f7",
        QPalette.ColorRole.Text: TEXT, QPalette.ColorRole.Button: PANEL,
        QPalette.ColorRole.ButtonText: TEXT, QPalette.ColorRole.Highlight: "#b7d3f6",
        QPalette.ColorRole.HighlightedText: TEXT, QPalette.ColorRole.ToolTipBase: PANEL,
        QPalette.ColorRole.ToolTipText: TEXT, QPalette.ColorRole.PlaceholderText: TEXT_3,
        QPalette.ColorRole.Mid: BORDER, QPalette.ColorRole.Midlight: SIDEBAR,
    }
    for role, color in roles.items():
        pal.setColor(role, QColor(color))
    pal.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor(TEXT_3))
    pal.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor(TEXT_3))
    return pal


def category_key(category: str) -> str:
    return category if category in CATEGORY_COLORS else "other"


STYLESHEET = f"""
QWidget {{ font-family: 'Segoe UI'; font-size: 10pt; color: {TEXT}; }}
QMainWindow, QStackedWidget > QWidget {{ background: {SURFACE}; }}
#Sidebar {{ background: {SIDEBAR}; border-right: 1px solid {BORDER}; }}
#Sidebar QListWidget {{ background: transparent; border: none; outline: none; }}
#Sidebar QListWidget::item {{ padding: 9px 14px; border-radius: 6px; margin: 1px 8px; color: {TEXT_2}; }}
#Sidebar QListWidget::item:selected {{ background: {PANEL}; color: {TEXT}; font-weight: 600; }}
#Sidebar QListWidget::item:hover:!selected {{ background: #ebeae6; }}
#AppTitle {{ font-size: 12pt; font-weight: 700; padding: 16px 16px 4px 16px; }}
#StatusLine {{ color: {TEXT_2}; padding: 0 16px 12px 16px; }}
#PageTitle {{ font-size: 16pt; font-weight: 700; }}
#Muted {{ color: {TEXT_2}; }}
#Hint {{ color: {TEXT_3}; font-size: 9pt; }}
#Error {{ color: {CRITICAL}; }}
#Card {{ background: {PANEL}; border: 1px solid {BORDER}; border-radius: 10px; }}
#CardValue {{ font-size: 18pt; font-weight: 700; }}
#CardLabel {{ color: {TEXT_2}; font-size: 9pt; }}
QPushButton {{ background: {PANEL}; border: 1px solid {BORDER}; border-radius: 6px; padding: 6px 14px; }}
QPushButton:hover {{ background: #f1f0ec; }}
QPushButton:disabled {{ color: {TEXT_3}; }}
QPushButton#Primary {{ background: {ACCENT}; color: white; border: 1px solid {ACCENT}; font-weight: 600; }}
QPushButton#Primary:hover {{ background: {ACCENT_DARK}; }}
QPushButton#Danger {{ color: {CRITICAL}; }}
QLineEdit, QPlainTextEdit, QTextEdit, QTextBrowser, QComboBox, QSpinBox, QDateEdit, QTimeEdit {{
    background: {PANEL}; border: 1px solid {BORDER}; border-radius: 6px; padding: 5px 7px;
    selection-background-color: #b7d3f6; selection-color: {TEXT};
}}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus {{ border: 1px solid {ACCENT}; }}
QTreeWidget, QTableWidget {{ background: {PANEL}; border: 1px solid {BORDER}; border-radius: 8px;
    alternate-background-color: #faf9f7; gridline-color: {BORDER}; }}
QHeaderView::section {{ background: {SIDEBAR}; border: none; border-bottom: 1px solid {BORDER};
    padding: 6px; color: {TEXT_2}; font-weight: 600; }}
QGroupBox {{ background: {PANEL}; border: 1px solid {BORDER}; border-radius: 10px; margin-top: 14px;
    padding: 14px 12px 10px 12px; font-weight: 600; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 12px; padding: 0 4px; color: {TEXT_2}; }}
QScrollArea {{ border: none; background: {SURFACE}; }}
#PageBody {{ background: {SURFACE}; }}
QListWidget {{ background: {PANEL}; border: 1px solid {BORDER}; border-radius: 8px; }}
QToolTip {{ background: {PANEL}; color: {TEXT}; border: 1px solid {BORDER}; padding: 4px; }}
QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator {{ width: 15px; height: 15px; border: 1px solid #a3a29c; border-radius: 4px; background: {PANEL}; }}
QCheckBox::indicator:checked {{ background: {ACCENT}; border: 1px solid {ACCENT}; }}
"""

"""Small native QSS theme for the v0.2 desktop shell."""

from __future__ import annotations

LIGHT_TOKENS: dict[str, str] = {
    "window": "#f6f8fb",
    "surface": "#ffffff",
    "surface_muted": "#eef2f7",
    "border": "#d5dce5",
    "text": "#182230",
    "text_muted": "#5d6b7b",
    "accent": "#2563eb",
    "accent_hover": "#1d4ed8",
    "accent_soft": "#dbeafe",
    "on_accent": "#ffffff",
    "danger": "#b42318",
    "focus": "#7aa7ff",
}


def build_stylesheet() -> str:
    """Return the shared light QSS using the shell's visual tokens."""
    t = LIGHT_TOKENS
    return f"""
    QWidget {{
        color: {t["text"]};
        font-family: "Segoe UI";
        font-size: 13px;
    }}
    QMainWindow#main-window, QWidget#main-shell {{
        background: {t["window"]};
    }}
    QFrame#app-header {{
        background: {t["surface"]};
        border: 1px solid {t["border"]};
        border-radius: 12px;
    }}
    QLabel#app-title {{
        color: {t["text"]};
        font-size: 24px;
        font-weight: 700;
    }}
    QLabel#app-subtitle {{
        color: {t["text_muted"]};
        font-size: 13px;
    }}
    QTabWidget#main-tabs::pane {{
        background: {t["surface"]};
        border: 1px solid {t["border"]};
        border-radius: 10px;
        top: -1px;
    }}
    QTabBar::tab {{
        background: {t["surface"]};
        color: {t["text_muted"]};
        padding: 10px 18px;
        margin-right: 4px;
        border: 1px solid transparent;
        border-bottom: 2px solid transparent;
    }}
    QTabBar::tab:hover {{
        color: {t["text"]};
        background: {t["surface_muted"]};
    }}
    QTabBar::tab:selected {{
        color: {t["accent"]};
        background: {t["accent_soft"]};
        border-color: {t["border"]};
        border-bottom-color: {t["accent"]};
    }}
    QPushButton {{
        background: {t["accent"]};
        color: {t["on_accent"]};
        border: 1px solid {t["accent"]};
        border-radius: 6px;
        padding: 7px 14px;
        min-height: 18px;
    }}
    QPushButton:hover {{
        background: {t["accent_hover"]};
        border-color: {t["accent_hover"]};
    }}
    QPushButton:focus, QLineEdit:focus, QComboBox:focus, QListWidget:focus {{
        border: 1px solid {t["focus"]};
    }}
    QPushButton:disabled {{
        background: {t["surface_muted"]};
        color: {t["text_muted"]};
        border-color: {t["border"]};
    }}
    QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QPlainTextEdit, QListWidget {{
        background: {t["surface"]};
        color: {t["text"]};
        border: 1px solid {t["border"]};
        border-radius: 6px;
        padding: 6px 8px;
        selection-background-color: {t["accent_soft"]};
        selection-color: {t["text"]};
    }}
    QProgressBar {{
        background: {t["surface_muted"]};
        border: 1px solid {t["border"]};
        border-radius: 5px;
        text-align: center;
    }}
    QProgressBar::chunk {{
        background: {t["accent"]};
        border-radius: 4px;
    }}
    QScrollBar:vertical {{
        background: {t["surface_muted"]};
        width: 10px;
        margin: 2px;
    }}
    QScrollBar::handle:vertical {{
        background: {t["border"]};
        min-height: 24px;
        border-radius: 4px;
    }}
    QTabWidget#main-tabs, QTabBar, QAbstractScrollArea, QScrollArea#settings-scroll,
    QScrollArea#project-scroll, QScrollArea#translation-scroll {{
        background: {t["surface"]};
    }}
    QScrollArea#settings-scroll::viewport, QScrollArea#project-scroll::viewport,
    QScrollArea#translation-scroll::viewport, QWidget#settings-page,
    QWidget#project-page, QWidget#translation-page {{
        background: {t["surface"]};
    }}
    QScrollArea#settings-scroll, QScrollArea#project-scroll,
    QScrollArea#translation-scroll {{
        border: none;
    }}
    """

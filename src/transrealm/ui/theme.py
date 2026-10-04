"""Native light theme with quiet surfaces and a clear action hierarchy."""

from __future__ import annotations

LIGHT_TOKENS: dict[str, str] = {
    "window": "#ffffff",
    "surface": "#ffffff",
    "surface_muted": "#f5f5f4",
    "border": "#e4e4e2",
    "text": "#242424",
    "text_muted": "#676767",
    "accent": "#292929",
    "accent_hover": "#454545",
    "accent_soft": "#eaeae8",
    "on_accent": "#ffffff",
    "danger": "#b42318",
    "focus": "#858585",
}


def build_stylesheet() -> str:
    """Return shared QSS; primary actions opt in via the role property."""
    t = LIGHT_TOKENS
    return f"""
    QWidget {{
        background: {t['surface']}; color: {t['text']};
        font-family: "Microsoft YaHei UI"; font-size: 13px;
    }}
    QMainWindow#main-window, QWidget#main-shell {{ background: {t['window']}; }}
    QFrame#sidebar {{
        background: {t['surface_muted']}; border-right: 1px solid {t['border']};
    }}
    QFrame#sidebar QLabel {{ background: transparent; }}
    QLabel#brand {{ font-size: 18px; font-weight: 600; }}
    QLabel#app-title, QLabel#empty-title {{ font-size: 22px; font-weight: 600; }}
    QLabel#app-subtitle, QLabel[role="muted"] {{ color: {t['text_muted']}; }}
    QFrame#app-header {{ border: none; }}
    QTabWidget::pane {{ border: none; background: {t['surface']}; }}
    QTabBar::tab {{
        background: transparent; color: {t['text_muted']};
        padding: 7px 12px; margin-right: 4px;
        border: 1px solid transparent; border-radius: 12px;
    }}
    QTabBar::tab:hover {{ background: {t['surface_muted']}; color: {t['text']}; }}
    QTabBar::tab:selected {{
        background: {t['accent_soft']}; color: {t['text']}; font-weight: 600;
    }}
    QGroupBox {{
        border: 1px solid {t['border']}; border-radius: 16px;
        margin-top: 10px; padding-top: 14px;
    }}
    QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; }}
    QPushButton, QToolButton {{
        background: {t['surface']}; color: {t['text']};
        border: 1px solid {t['border']}; border-radius: 12px;
        padding: 6px 12px; min-height: 20px;
    }}
    QPushButton:hover, QToolButton:hover {{ background: {t['surface_muted']}; }}
    QPushButton:pressed {{ background: {t['accent_soft']}; }}
    QPushButton[role="primary"] {{
        background: {t['accent']}; color: {t['on_accent']}; border-color: {t['accent']};
    }}
    QPushButton[role="primary"]:hover {{ background: {t['accent_hover']}; }}
    QPushButton[role="navigation"] {{
        text-align: left; background: transparent;
        border: 1px solid transparent; border-radius: 16px; padding: 9px 12px;
    }}
    QPushButton[role="navigation"]:hover {{ background: {t['accent_soft']}; }}
    QPushButton[role="navigation"]:checked {{
        background: {t['accent_soft']}; font-weight: 600;
    }}
    QPushButton[role="link"] {{ border-color: transparent; color: {t['text_muted']}; }}
    QPushButton[role="danger"] {{ color: {t['danger']}; }}
    QPushButton:disabled, QToolButton:disabled {{
        color: #999999; background: {t['surface_muted']}; border-color: {t['border']};
    }}
    QPushButton:focus, QLineEdit:focus, QComboBox:focus, QPlainTextEdit:focus,
    QListWidget:focus {{ border: 1px solid {t['focus']}; }}
    QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QPlainTextEdit, QListWidget {{
        background: {t['surface']}; color: {t['text']};
        border: 1px solid {t['border']}; border-radius: 12px; padding: 5px 8px;
        selection-background-color: {t['accent_soft']}; selection-color: {t['text']};
    }}
    QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{ min-height: 22px; }}
    QComboBox {{ padding-right: 28px; }}
    QComboBox::drop-down {{
        subcontrol-origin: padding; subcontrol-position: top right; width: 26px;
        background: transparent; border: none;
        border-top-right-radius: 12px; border-bottom-right-radius: 12px;
    }}
    QComboBox::down-arrow {{
        image: url(:/qt-project.org/styles/commonstyle/images/arrow-down-16.png);
        width: 12px; height: 12px;
    }}
    QSpinBox, QDoubleSpinBox {{ padding-right: 28px; }}
    QSpinBox::up-button, QDoubleSpinBox::up-button {{
        subcontrol-origin: border; subcontrol-position: top right;
        width: 20px; height: 12px; margin-top: 4px; margin-right: 5px;
        background: transparent; border: none;
    }}
    QSpinBox::down-button, QDoubleSpinBox::down-button {{
        subcontrol-origin: border; subcontrol-position: bottom right;
        width: 20px; height: 12px; margin-bottom: 4px; margin-right: 5px;
        background: transparent; border: none;
    }}
    QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{
        image: url(:/qt-project.org/styles/commonstyle/images/arrow-up-16.png);
        width: 9px; height: 9px;
    }}
    QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{
        image: url(:/qt-project.org/styles/commonstyle/images/arrow-down-16.png);
        width: 9px; height: 9px;
    }}
    QPlainTextEdit, QListWidget {{ border-radius: 16px; }}
    QPlainTextEdit#source-preview {{ background: {t['surface_muted']}; }}
    QListWidget::item {{ padding: 8px 4px; border-radius: 12px; }}
    QListWidget::item:hover {{ background: {t['surface_muted']}; }}
    QListWidget::item:selected {{ background: {t['accent_soft']}; color: {t['text']}; }}
    QProgressBar {{ background: {t['surface_muted']}; border: none; border-radius: 2px; }}
    QProgressBar::chunk {{ background: {t['accent']}; border-radius: 2px; }}
    QScrollBar:vertical {{ background: transparent; width: 8px; margin: 2px 0; }}
    QScrollBar::handle:vertical {{ background: #cececc; min-height: 24px; border-radius: 4px; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
    QScrollBar:horizontal {{ background: transparent; height: 8px; margin: 0 2px; }}
    QScrollBar::handle:horizontal {{
        background: #cececc; min-width: 24px; border-radius: 4px;
    }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
    QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
        background: transparent;
    }}
    QScrollArea {{ border: none; }}
    QSplitter::handle {{ background: transparent; width: 12px; }}
    """

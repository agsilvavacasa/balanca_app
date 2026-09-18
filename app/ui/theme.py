"""Tema escuro (QSS). Todas as cores num só lugar."""
import sys

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

C = {
    "bg": "#0E151D", "card": "#16202B", "card2": "#1C2937", "border": "#2A3B4D",
    "text": "#EAF0F6", "muted": "#8FA3B7", "accent": "#38BDF8",
    "ok": "#34D399", "warn": "#FBBF24", "error": "#F87171", "info": "#60A5FA",
    "primary": "#22C55E", "primary_hover": "#16A34A", "primary_text": "#04210F",
    "danger": "#EF4444",
}

# Windows é a plataforma-alvo (Segoe UI); no Mac de desenvolvimento cai para a fonte do sistema.
_FAMILIES = (["Segoe UI", "Arial"] if sys.platform == "win32"
             else ["Helvetica Neue", "Arial"] if sys.platform == "darwin"
             else ["DejaVu Sans", "Arial"])
FONT_FAMILY = ", ".join(f'"{f}"' for f in _FAMILIES) + ", sans-serif"


def _tone_rules() -> str:
    rules = []
    for tone, color in (("ok", C["ok"]), ("warn", C["warn"]), ("error", C["error"]),
                        ("info", C["info"]), ("muted", C["muted"])):
        rules.append(f'''
        QLabel[tone="{tone}"] {{ color: {color}; background: rgba(255,255,255,0.05);
            border: 1px solid {color}; }}
        QLabel[valueTone="{tone}"] {{ color: {color}; }}''')
    return "\n".join(rules)


STYLESHEET = f"""
* {{ font-family: {FONT_FAMILY}; color: {C["text"]}; }}
QMainWindow, QDialog, QWidget#root {{ background: {C["bg"]}; }}
QFrame#header {{ background: {C["card"]}; border-bottom: 1px solid {C["border"]}; }}
QFrame#card {{ background: {C["card"]}; border: 1px solid {C["border"]}; border-radius: 14px; }}
QFrame#inner {{ background: {C["card2"]}; border: 1px solid {C["border"]}; border-radius: 12px; }}
QLabel {{ background: transparent; border: none; }}
QLabel#appTitle {{ font-size: 20px; font-weight: 700; }}
QLabel#appSubtitle {{ font-size: 13px; color: {C["muted"]}; }}
QLabel#cardTitle {{ font-size: 12px; font-weight: 700; color: {C["muted"]}; letter-spacing: 1px; }}
QLabel#muted {{ color: {C["muted"]}; font-size: 13px; }}
QLabel#fieldLabel {{ color: {C["muted"]}; font-size: 13px; }}
QLabel#weightValue {{ font-size: 68px; font-weight: 700; }}
QLabel#moneyValue {{ font-size: 60px; font-weight: 800; color: {C["ok"]}; }}
QLabel#commandTotal {{ font-size: 34px; font-weight: 800; }}
QLabel#priceValue {{ font-size: 24px; font-weight: 600; }}
QLabel#message {{ font-size: 15px; }}
QLabel[tone] {{ border-radius: 12px; padding: 4px 12px; font-size: 13px; font-weight: 700; }}
{_tone_rules()}

QLineEdit {{ background: {C["card2"]}; border: 2px solid {C["border"]}; border-radius: 10px;
    padding: 10px 14px; font-size: 16px; selection-background-color: {C["accent"]}; }}
QLineEdit:focus {{ border-color: {C["accent"]}; }}
QLineEdit#commandInput {{ font-size: 28px; font-weight: 700; letter-spacing: 2px; padding: 12px 16px; }}

QPushButton {{ background: {C["card2"]}; border: 1px solid {C["border"]}; border-radius: 10px;
    padding: 10px 16px; font-size: 14px; font-weight: 600; }}
QPushButton:hover {{ border-color: {C["accent"]}; }}
QPushButton:pressed {{ background: {C["border"]}; }}
QPushButton:disabled {{ color: #5B6E82; background: #131C26; border-color: #1F2C3A; }}
QPushButton[kind="primary"] {{ background: {C["primary"]}; border: none; color: {C["primary_text"]};
    font-size: 20px; font-weight: 800; padding: 18px 20px; border-radius: 12px; }}
QPushButton[kind="primary"]:hover {{ background: {C["primary_hover"]}; }}
QPushButton[kind="primary"]:disabled {{ background: #1B3A2A; color: #4C7A62; }}
QPushButton[kind="danger"] {{ color: {C["error"]}; border-color: #5B2A2A; }}
QPushButton[kind="danger"]:hover {{ background: #2A1618; border-color: {C["danger"]}; }}
QPushButton[kind="danger"]:disabled {{ color: #5B6E82; background: #131C26; border-color: #1F2C3A; }}
QPushButton[kind="product"] {{ padding: 12px 18px; text-align: left; min-width: 140px; }}

QTableWidget {{ background: {C["card2"]}; border: 1px solid {C["border"]}; border-radius: 10px;
    gridline-color: transparent; font-size: 15px; outline: none; }}
QTableWidget::item {{ padding: 6px 10px; border-bottom: 1px solid #223142; }}
QTableWidget::item:selected {{ background: #23415C; color: {C["text"]}; }}
QHeaderView::section {{ background: {C["card"]}; color: {C["muted"]}; border: none;
    border-bottom: 1px solid {C["border"]}; padding: 8px 10px; font-size: 12px; font-weight: 700; }}
QTableCornerButton::section {{ background: {C["card"]}; border: none; }}

QComboBox, QSpinBox {{ background: {C["card2"]}; border: 2px solid {C["border"]}; border-radius: 8px;
    padding: 6px 10px; font-size: 14px; min-height: 22px; }}
QComboBox:focus, QSpinBox:focus {{ border-color: {C["accent"]}; }}
QComboBox QAbstractItemView {{ background: {C["card2"]}; border: 1px solid {C["border"]};
    selection-background-color: #23415C; }}
QCheckBox, QRadioButton {{ font-size: 14px; spacing: 8px; }}
QPlainTextEdit {{ background: {C["card2"]}; border: 2px solid {C["border"]}; border-radius: 10px;
    padding: 8px 10px; font-size: 13px; selection-background-color: {C["accent"]}; }}
QPlainTextEdit:focus {{ border-color: {C["accent"]}; }}
QGroupBox {{ border: 1px dashed {C["border"]}; border-radius: 12px; margin-top: 14px; padding: 14px 12px 10px 12px;
    font-weight: 700; color: {C["muted"]}; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 14px; padding: 0 6px; color: {C["warn"]}; }}
QStatusBar {{ background: {C["card"]}; color: {C["muted"]}; border-top: 1px solid {C["border"]}; }}
QStatusBar QLabel {{ color: {C["muted"]}; }}
QMessageBox {{ background: {C["card"]}; }}
/* ---- autoatendimento / autopagamento (toque) ---- */
QLabel#hero {{ font-size: 54px; font-weight: 800; }}
QLabel#heroSub {{ font-size: 24px; color: {C["muted"]}; }}
QLabel#stepTitle {{ font-size: 30px; font-weight: 800; }}
QLabel#stepHint {{ font-size: 20px; color: {C["muted"]}; }}
QLabel#bigCode {{ font-size: 84px; font-weight: 800; letter-spacing: 6px; color: {C["accent"]}; }}
QLabel#cpfDisplay {{ font-size: 44px; font-weight: 700; letter-spacing: 3px; background: {C["card2"]};
    border: 2px solid {C["border"]}; border-radius: 14px; padding: 12px 20px; }}
QLabel#bigMessage {{ font-size: 22px; }}
QFrame#tile {{ background: {C["card2"]}; border: 2px solid {C["border"]}; border-radius: 16px; }}
QFrame#tile[active="true"] {{ border-color: {C["primary"]}; background: #16302A; }}
QLabel#tileName {{ font-size: 22px; font-weight: 700; }}
QLabel#tilePrice {{ font-size: 18px; color: {C["muted"]}; }}
QLabel#tileQty {{ font-size: 34px; font-weight: 800; min-width: 56px; }}
QPushButton[kind="kiosk"] {{ font-size: 24px; font-weight: 700; padding: 22px 34px; border-radius: 16px; }}
QPushButton[kind="kioskPrimary"] {{ background: {C["primary"]}; color: {C["primary_text"]}; border: none;
    font-size: 28px; font-weight: 800; padding: 26px 40px; border-radius: 18px; }}
QPushButton[kind="kioskPrimary"]:hover {{ background: {C["primary_hover"]}; }}
QPushButton[kind="kioskPrimary"]:disabled {{ background: #1B3A2A; color: #4C7A62; }}
QPushButton[kind="key"] {{ font-size: 32px; font-weight: 700; min-width: 96px; min-height: 76px;
    border-radius: 14px; }}
QPushButton[kind="round"] {{ font-size: 34px; font-weight: 800; min-width: 64px; min-height: 64px;
    max-width: 64px; border-radius: 32px; padding: 0; }}
QPushButton[kind="method"] {{ font-size: 24px; font-weight: 700; padding: 24px 20px; border-radius: 16px;
    min-height: 60px; }}
QPushButton[kind="method"]:checked {{ background: #16302A; border: 2px solid {C["primary"]}; }}
QToolTip {{ background: {C["card2"]}; color: {C["text"]}; border: 1px solid {C["border"]}; padding: 6px; }}
"""


def apply_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    font = QFont()
    font.setFamilies(_FAMILIES)
    font.setPointSize(11)
    app.setFont(font)
    app.setStyleSheet(STYLESHEET)


def repolish(widget) -> None:
    """Reaplica o QSS depois de mudar uma property dinâmica (tone, kind...)."""
    widget.style().unpolish(widget)
    widget.style().polish(widget)

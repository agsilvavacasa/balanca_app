from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget

from .theme import repolish


class Card(QFrame):
    def __init__(self, title: str = "", parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("card")
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(20, 16, 20, 18)
        self.body.setSpacing(12)
        if title:
            label = QLabel(title.upper())
            label.setObjectName("cardTitle")
            self.body.addWidget(label)


class Chip(QLabel):
    """Etiqueta colorida de status. tone: ok | warn | error | info | muted."""

    def __init__(self, text: str = "", tone: str = "muted", parent: QWidget | None = None):
        super().__init__(text, parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.set_tone(tone)

    def set_state(self, text: str, tone: str) -> None:
        self.setText(text)
        self.set_tone(tone)

    def set_tone(self, tone: str) -> None:
        if self.property("tone") == tone:     # repolish é caro: só quando muda
            return
        self.setProperty("tone", tone)
        repolish(self)


def set_value_tone(label: QLabel, tone: str) -> None:
    if label.property("valueTone") == tone:
        return
    label.setProperty("valueTone", tone)
    repolish(label)

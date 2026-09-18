from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QGridLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from ..domain.cpf import format_cpf, is_valid_cpf, only_digits
from .dialogs import _button
from .theme import repolish


class CpfInput(QWidget):
    """Campo de CPF com teclado na tela (toque). Também aceita o teclado físico."""
    changed = Signal()
    submitted = Signal()          # Enter no teclado físico com CPF completo

    def __init__(self, parent=None):
        super().__init__(parent)
        self._digits = ""
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        lay = QVBoxLayout(self)
        lay.setSpacing(14)
        self.display = QLabel()
        self.display.setObjectName("cpfDisplay")
        self.display.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.hint = QLabel("")
        self.hint.setObjectName("stepHint")
        self.hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.display)
        lay.addWidget(self.hint)

        grid = QGridLayout()
        grid.setSpacing(10)
        self.keys: dict[str, QPushButton] = {}
        layout = ["123", "456", "789"]
        for r, row in enumerate(layout):
            for c, ch in enumerate(row):
                grid.addWidget(self._key(ch), r, c)
        clear = self._key("Limpar", command=self.clear)
        grid.addWidget(clear, 3, 0)
        grid.addWidget(self._key("0"), 3, 1)
        grid.addWidget(self._key("⌫", command=self.backspace), 3, 2)
        lay.addLayout(grid)
        self._render()

    def _key(self, label: str, command=None) -> QPushButton:
        btn = _button(label, "key")
        btn.clicked.connect(command if command else (lambda _=False, d=label: self.type_digit(d)))
        self.keys[label] = btn
        return btn

    # ---- estado
    @property
    def digits(self) -> str:
        return self._digits

    @property
    def is_complete(self) -> bool:
        return len(self._digits) == 11

    @property
    def is_valid(self) -> bool:
        return is_valid_cpf(self._digits)

    def type_digit(self, digit: str) -> None:
        if digit.isdigit() and len(self._digits) < 11:
            self._digits += digit
            self._render()

    def backspace(self) -> None:
        self._digits = self._digits[:-1]
        self._render()

    def clear(self) -> None:
        self._digits = ""
        self._render()

    def set_hint(self, text: str, error: bool = False) -> None:
        self.hint.setText(text)
        self.hint.setProperty("valueTone", "error" if error else "")
        repolish(self.hint)

    def _render(self) -> None:
        d = self._digits
        if not d:
            self.display.setText("000.000.000-00")
            self.display.setStyleSheet("color: #5B6E82;")
        else:
            shown = format_cpf(d) if len(d) == 11 else (
                ".".join(filter(None, [d[:3], d[3:6], d[6:9]])) + (("-" + d[9:]) if len(d) > 9 else ""))
            self.display.setText(shown)
            self.display.setStyleSheet("")
        if self.is_complete and not self.is_valid:
            self.set_hint("CPF inválido. Confira os números.", error=True)
        else:
            self.set_hint("")
        self.changed.emit()

    # ---- teclado físico
    def keyPressEvent(self, event: QKeyEvent) -> None:
        key = event.key()
        if Qt.Key.Key_0 <= key <= Qt.Key.Key_9:
            self.type_digit(chr(key))
        elif key in (Qt.Key.Key_Backspace, Qt.Key.Key_Delete):
            self.backspace()
        elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if self.is_valid:
                self.submitted.emit()
        else:
            super().keyPressEvent(event)

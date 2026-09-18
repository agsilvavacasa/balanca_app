from typing import Optional

from PySide6.QtWidgets import QCheckBox, QDialog, QLabel, QVBoxLayout

from ..config.settings import AppSettings, save_settings
from .connection_dialog import ConnectionDialog
from .dialogs import _button

MODE_LABELS = {
    "servidor": ("SERVIDOR (guarda os dados)", "PC principal: guarda o banco, aceita os terminais e abre o caixa"),
    "autoatendimento": ("AUTOATENDIMENTO", "PC da balança e da impressora: o cliente abre a comanda e pesa"),
    "caixa": ("CAIXA / PAGAMENTO", "PC de saída: lê a comanda e recebe o pagamento"),
    "operador": ("OPERADOR", "Atendimento assistido: comandas, balança, cancelamentos e preços"),
}


class ModeDialog(QDialog):
    def __init__(self, settings: AppSettings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Restaurante por quilo")
        self.setModal(True)
        self.setMinimumWidth(560)
        self.settings = settings
        self.mode: Optional[str] = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 26, 30, 26)
        layout.setSpacing(12)
        title = QLabel("Como este computador será usado?")
        title.setObjectName("appTitle")
        layout.addWidget(title)
        for mode, (label, hint) in MODE_LABELS.items():
            btn = _button(label, "primary" if mode == "servidor" else "")
            btn.clicked.connect(lambda _=False, m=mode: self._choose(m))
            layout.addWidget(btn)
            sub = QLabel(hint)
            sub.setObjectName("muted")
            layout.addWidget(sub)
        self.remember = QCheckBox("Lembrar a escolha neste computador")
        layout.addWidget(self.remember)
        conn = _button("Conexão com o servidor…")
        conn.clicked.connect(self._connection)
        layout.addWidget(conn)

    def _choose(self, mode: str) -> None:
        self.mode = mode
        if self.remember.isChecked():
            self.settings.role = mode
            save_settings(self.settings)
        self.accept()

    def _connection(self) -> None:
        ConnectionDialog(self.settings, parent=self).exec()

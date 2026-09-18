"""Configuração do banco compartilhado (rede local). Ambos os PCs apontam para o mesmo MySQL."""
from typing import Optional

from PySide6.QtWidgets import (QComboBox, QDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
                               QSpinBox, QVBoxLayout)
from sqlalchemy.engine import URL, make_url

from ..config.settings import AppSettings, config_dir
from ..database.connection import check_connection
from .dialogs import _button, _buttons_row
from .theme import repolish


def build_mysql_url(host: str, port: int, database: str, user: str, password: str) -> str:
    url = URL.create("mysql+pymysql", username=user or None, password=password or None,
                     host=host, port=port, database=database, query={"charset": "utf8mb4"})
    return url.render_as_string(hide_password=False)


def sqlite_url() -> str:
    return f"sqlite:///{config_dir() / 'balanca.db'}"


class DatabaseDialog(QDialog):
    def __init__(self, settings: AppSettings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Banco de dados e rede")
        self.setModal(True)
        self.setMinimumWidth(500)
        self.settings = settings
        self.url: Optional[str] = None

        self.kind = QComboBox()
        self.kind.addItem("MySQL na rede (vários PCs)", "mysql")
        self.kind.addItem("SQLite local (somente este PC)", "sqlite")
        self.host = QLineEdit()
        self.host.setPlaceholderText("IP ou nome do PC do banco, ex.: 192.168.0.10")
        self.port = QSpinBox()
        self.port.setRange(1, 65535)
        self.port.setValue(3306)
        self.database = QLineEdit("restaurante")
        self.user = QLineEdit()
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)

        current = settings.effective_database_url
        try:
            parsed = make_url(current)
            if parsed.drivername.startswith("mysql"):
                self.host.setText(parsed.host or "")
                self.port.setValue(parsed.port or 3306)
                self.database.setText(parsed.database or "restaurante")
                self.user.setText(parsed.username or "")
                self.password.setText(parsed.password or "")
            else:
                self.kind.setCurrentIndex(1)
        except Exception:
            pass

        form = QFormLayout()
        form.setSpacing(10)
        for label, widget in (("Tipo", self.kind), ("Servidor", self.host), ("Porta", self.port),
                              ("Banco", self.database), ("Usuário", self.user), ("Senha", self.password)):
            form.addRow(label, widget)
        hint = QLabel("Os dois PCs (balança/autoatendimento e caixa) devem usar o MESMO servidor. "
                      "A senha fica gravada em texto no arquivo de configuração deste PC.")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        self.result = QLabel("")
        self.result.setWordWrap(True)

        test = _button("TESTAR CONEXÃO")
        test.clicked.connect(self._test)
        cancel = _button("CANCELAR")
        cancel.clicked.connect(self.reject)
        save = _button("SALVAR", "primary")
        save.clicked.connect(self._save)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)
        layout.addLayout(form)
        layout.addWidget(hint)
        layout.addWidget(self.result)
        row = QHBoxLayout()
        row.addWidget(test)
        row.addStretch(1)
        row.addWidget(cancel)
        row.addWidget(save)
        layout.addLayout(row)
        self.kind.currentIndexChanged.connect(self._sync)
        self._sync()

    def _sync(self) -> None:
        mysql = self.kind.currentData() == "mysql"
        for w in (self.host, self.port, self.database, self.user, self.password):
            w.setEnabled(mysql)

    def current_url(self) -> str:
        if self.kind.currentData() == "sqlite":
            return sqlite_url()
        return build_mysql_url(self.host.text().strip(), self.port.value(),
                               self.database.text().strip(), self.user.text().strip(),
                               self.password.text())

    def _show(self, text: str, ok: bool) -> None:
        self.result.setText(text)
        self.result.setProperty("valueTone", "ok" if ok else "error")
        repolish(self.result)

    def _valid_form(self) -> bool:
        if self.kind.currentData() == "mysql" and not (self.host.text().strip() and self.user.text().strip()
                                                       and self.database.text().strip()):
            self._show("Preencha servidor, banco e usuário.", False)
            return False
        return True

    def _test(self) -> None:
        if not self._valid_form():
            return
        self._show("Testando…", True)
        self.repaint()
        ok, message = check_connection(self.current_url())
        self._show(message, ok)

    def _save(self) -> None:
        if not self._valid_form():
            return
        self.url = self.current_url()
        self.accept()

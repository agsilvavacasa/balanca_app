"""Onde ficam os dados deste PC: no próprio PC (servidor/teste) ou em outro PC (informar IP e código)."""
from typing import Optional

from PySide6.QtWidgets import (QDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QRadioButton,
                               QSpinBox, QVBoxLayout)

from ..config.settings import AppSettings, save_settings
from ..net import protocol
from ..net.client import build_remote_services
from ..services.errors import BusinessError
from .db_dialog import DatabaseDialog
from .dialogs import _button
from .theme import repolish


class ConnectionDialog(QDialog):
    def __init__(self, settings: AppSettings, client_name: str = "Terminal", parent=None,
                 prefer_remote: bool = True):
        super().__init__(parent)
        self.setWindowTitle("Conexão com o servidor")
        self.setModal(True)
        self.setMinimumWidth(520)
        self.settings = settings
        self.client_name = client_name
        conn = settings.connection

        title = QLabel("Onde estão os dados deste computador?")
        title.setObjectName("appTitle")
        self.remote_radio = QRadioButton("Em outro PC (o servidor) — informe o IP e o código")
        self.local_radio = QRadioButton("Neste PC (servidor ou teste sem rede)")
        (self.remote_radio if (conn.mode == "remote" or (conn.mode == "" and prefer_remote))
         else self.local_radio).setChecked(True)

        self.host = QLineEdit(conn.host)
        self.host.setPlaceholderText("IP do servidor, ex.: 192.168.0.10")
        self.port = QSpinBox()
        self.port.setRange(1, 65535)
        self.port.setValue(conn.port or protocol.DEFAULT_PORT)
        self.key = QLineEdit(conn.access_key)
        self.key.setPlaceholderText("Código mostrado na tela do servidor")
        form = QFormLayout()
        form.setSpacing(10)
        form.addRow("IP do servidor", self.host)
        form.addRow("Porta", self.port)
        form.addRow("Código", self.key)

        self.result = QLabel("")
        self.result.setWordWrap(True)
        hint = QLabel("No PC servidor, abra o programa em modo SERVIDOR: ele mostra o IP e o código. "
                      "Na primeira vez o Windows pergunta se deixa o programa usar a rede: permita em "
                      "redes privadas.")
        hint.setObjectName("muted")
        hint.setWordWrap(True)

        self.test_btn = _button("TESTAR CONEXÃO")
        self.test_btn.clicked.connect(self._test)
        self.db_btn = _button("Banco de dados deste PC…")
        self.db_btn.clicked.connect(self._database)
        cancel = _button("CANCELAR")
        cancel.clicked.connect(self.reject)
        save = _button("SALVAR", "primary")
        save.clicked.connect(self._save)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(26, 22, 26, 22)
        layout.setSpacing(12)
        layout.addWidget(title)
        layout.addWidget(self.remote_radio)
        layout.addLayout(form)
        layout.addWidget(self.test_btn)
        layout.addWidget(self.local_radio)
        layout.addWidget(self.db_btn)
        layout.addWidget(hint)
        layout.addWidget(self.result)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(cancel)
        row.addWidget(save)
        layout.addLayout(row)
        self.remote_radio.toggled.connect(self._sync)
        self._sync()

    def _sync(self) -> None:
        remote = self.remote_radio.isChecked()
        for w in (self.host, self.port, self.key, self.test_btn):
            w.setEnabled(remote)
        self.db_btn.setEnabled(not remote)

    def _show(self, text: str, ok: bool) -> None:
        self.result.setText(text)
        self.result.setProperty("valueTone", "ok" if ok else "error")
        repolish(self.result)

    def _fields_ok(self) -> bool:
        if not self.host.text().strip() or not self.key.text().strip():
            self._show("Informe o IP do servidor e o código.", False)
            return False
        return True

    def _test(self) -> Optional[str]:
        if not self._fields_ok():
            return None
        self._show("Testando…", True)
        self.repaint()
        try:
            services = build_remote_services(self.host.text().strip(), self.port.value(),
                                             self.key.text().strip().upper(), self.client_name)
            services.auth.list_operators()
        except BusinessError as exc:
            self._show(str(exc), False)
            return None
        self._show("Conectado ao servidor.", True)
        return "ok"

    def _database(self) -> None:
        dialog = DatabaseDialog(self.settings, self)
        if dialog.exec() == dialog.DialogCode.Accepted and dialog.url:
            self.settings.database_url = dialog.url

    def _save(self) -> None:
        conn = self.settings.connection
        if self.remote_radio.isChecked():
            if not self._fields_ok():
                return
            conn.mode = "remote"
            conn.host = self.host.text().strip()
            conn.port = self.port.value()
            conn.access_key = self.key.text().strip().upper()
        else:
            conn.mode = "local"
        save_settings(self.settings)
        self.accept()

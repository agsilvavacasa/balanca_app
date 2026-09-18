"""Janela do PC servidor: guarda os dados, aceita os terminais e mostra IP, código e quem está conectado."""
from typing import Callable, Optional

from PySide6.QtCore import QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QListWidget, QMainWindow, QMessageBox,
                               QPlainTextEdit, QVBoxLayout, QWidget)

from ..bootstrap import Services
from ..config.settings import AppSettings, save_settings
from ..net.server import ServerHost, local_ips, new_access_key
from .dialogs import _button
from .widgets import Card, Chip

REFRESH_MS = 1500


class ServerWindow(QMainWindow):
    def __init__(self, settings: AppSettings, services: Services,
                 opener: Optional[Callable[[str], Optional[QWidget]]] = None, port: Optional[int] = None):
        super().__init__()
        self.settings = settings
        self.services = services
        self.opener = opener
        self.children_windows: list[QWidget] = []
        if not settings.server.access_key:
            settings.server.access_key = new_access_key()
            save_settings(settings)
        self.host = ServerHost(services, settings.server.access_key,
                               port=settings.server.port if port is None else port,
                               name=settings.server.name)

        self.setWindowTitle("Servidor")
        self.resize(760, 780)
        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        lay = QVBoxLayout(root)
        lay.setContentsMargins(24, 22, 24, 22)
        lay.setSpacing(16)

        head = QHBoxLayout()
        title = QLabel("Servidor")
        title.setObjectName("appTitle")
        self.status = Chip("INICIANDO…", "muted")
        head.addWidget(title)
        head.addStretch(1)
        head.addWidget(self.status)
        lay.addLayout(head)

        conn = Card("Como conectar os terminais")
        self.address = QLabel("")
        self.address.setObjectName("commandTotal")
        self.code = QLabel("")
        self.code.setObjectName("bigCode")
        self.code.setStyleSheet("font-size: 54px;")
        hint = QLabel("No autoatendimento (e em outros caixas), informe este IP e este código quando o "
                      "programa perguntar. Mantenha esta janela aberta: ela é quem guarda os dados.")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        conn.body.addWidget(self._caption("ENDEREÇO"))
        conn.body.addWidget(self.address)
        conn.body.addWidget(self._caption("CÓDIGO DE ACESSO"))
        conn.body.addWidget(self.code)
        conn.body.addWidget(hint)
        row = QHBoxLayout()
        self.copy_btn = _button("Copiar endereço")
        self.newkey_btn = _button("Gerar novo código")
        self.copy_btn.clicked.connect(self._copy)
        self.newkey_btn.clicked.connect(self._new_key)
        row.addWidget(self.copy_btn)
        row.addWidget(self.newkey_btn)
        row.addStretch(1)
        conn.body.addLayout(row)
        lay.addWidget(conn)

        open_card = Card("Usar este PC")
        row = QHBoxLayout()
        self.cashier_btn = _button("Abrir caixa", "primary")
        self.operator_btn = _button("Abrir operador")
        self.cashier_btn.clicked.connect(lambda: self._open("caixa"))
        self.operator_btn.clicked.connect(lambda: self._open("operador"))
        row.addWidget(self.cashier_btn, 2)
        row.addWidget(self.operator_btn, 1)
        open_card.body.addLayout(row)
        lay.addWidget(open_card)

        clients = Card("Terminais conectados")
        self.clients = QListWidget()
        self.clients.setStyleSheet("QListWidget { background: #1C2937; border: 1px solid #2A3B4D; "
                                   "border-radius: 10px; font-size: 15px; } "
                                   "QListWidget::item { padding: 8px; }")
        self.clients.setMinimumHeight(150)
        clients.body.addWidget(self.clients, 1)
        lay.addWidget(clients, 1)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(130)
        lay.addWidget(self.log)

        self._start()
        self.timer = QTimer(self)
        self.timer.setInterval(REFRESH_MS)
        self.timer.timeout.connect(self._refresh)
        self.timer.start()
        self._refresh()

    @staticmethod
    def _caption(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("cardTitle")
        return label

    def _start(self) -> None:
        try:
            self.host.start()
        except OSError as exc:
            self.status.set_state("NÃO INICIOU", "error")
            self.log.appendPlainText(f"Não foi possível abrir a porta {self.host.port}: {exc}. "
                                     "Feche outro servidor aberto neste PC ou mude a porta.")
            return
        self.status.set_state("SERVIDOR ATIVO", "ok")

    def _refresh(self) -> None:
        ips = local_ips()
        self.address.setText(f"{ips[0]} : {self.host.port}" + (f"   (ou {', '.join(ips[1:])})" if len(ips) > 1 else ""))
        self.code.setText(self.host.access_key)
        current = [f"{c.name}  ·  {c.address}  ·  {c.requests} chamadas" for c in self.host.active_clients()]
        shown = [self.clients.item(i).text() for i in range(self.clients.count())]
        if current != shown:
            self.clients.clear()
            self.clients.addItems(current or ["Nenhum terminal conectado no momento."])
        self.log.setPlainText("\n".join(list(self.host.events)[-30:]))

    def _copy(self) -> None:
        QGuiApplication.clipboard().setText(local_ips()[0])

    def _new_key(self) -> None:
        answer = QMessageBox.question(
            self, "Gerar novo código",
            "Os terminais conectados perderão o acesso até receberem o novo código. Continuar?")
        if answer != QMessageBox.StandardButton.Yes:
            return
        key = new_access_key()
        self.settings.server.access_key = key
        self.host.access_key = key
        save_settings(self.settings)
        self._refresh()

    def _open(self, mode: str) -> None:
        if self.opener is None:
            return
        window = self.opener(mode)
        if window is not None:
            self.children_windows.append(window)

    def closeEvent(self, event) -> None:
        if self.host.active_clients() and self.isVisible():
            answer = QMessageBox.question(self, "Encerrar servidor",
                                          "Há terminais conectados. Encerrar o servidor mesmo assim?")
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
        self.timer.stop()
        self.host.stop()
        for window in self.children_windows:
            window.close()
        super().closeEvent(event)

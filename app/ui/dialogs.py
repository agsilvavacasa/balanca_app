from dataclasses import replace
from decimal import Decimal, InvalidOperation
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFormLayout, QHBoxLayout, QLabel,
                               QLineEdit, QMessageBox, QPlainTextEdit, QPushButton, QSpinBox,
                               QVBoxLayout, QWidget)

from ..config.settings import ScaleSettings
from ..domain.money import format_brl, format_kg, to_decimal
from ..hardware.prix3fit import ToledoPrix3Fit, pyserial_factory
from ..services.dto import OperatorInfo
from .theme import repolish


def _button(text: str, kind: str = "", parent: QWidget | None = None) -> QPushButton:
    btn = QPushButton(text, parent)
    if kind:
        btn.setProperty("kind", kind)
        repolish(btn)
    btn.setAutoDefault(False)     # Enter (inclusive o do leitor de código de barras) não aciona botões
    btn.setDefault(False)
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    return btn


def _buttons_row(*buttons: QPushButton) -> QHBoxLayout:
    row = QHBoxLayout()
    row.setSpacing(10)
    row.addStretch(1)
    for b in buttons:
        row.addWidget(b)
    return row


class LoginDialog(QDialog):
    def __init__(self, operators: list[OperatorInfo], authenticate, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Entrar")
        self.setModal(True)
        self.setMinimumWidth(380)
        self._authenticate = authenticate
        self.operator: Optional[OperatorInfo] = None

        title = QLabel("Restaurante")
        title.setObjectName("appTitle")
        subtitle = QLabel("Identifique-se para iniciar o atendimento")
        subtitle.setObjectName("appSubtitle")
        self.combo = QComboBox()
        for op in operators:
            self.combo.addItem(op.name, op.id)
        self.pin = QLineEdit()
        self.pin.setEchoMode(QLineEdit.EchoMode.Password)
        self.pin.setPlaceholderText("PIN")
        self.pin.returnPressed.connect(self._try)
        self.error = QLabel("")
        self.error.setProperty("valueTone", "error")
        ok = _button("ENTRAR", "primary")
        ok.clicked.connect(self._try)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(12)
        for w in (title, subtitle, self.combo, self.pin, self.error, ok):
            layout.addWidget(w)
        self.pin.setFocus()

    def _try(self) -> None:
        op = self._authenticate(self.combo.currentData(), self.pin.text())
        if op is None:
            self.error.setText("PIN incorreto.")
            self.pin.clear()
            self.pin.setFocus()
            return
        self.operator = op
        self.accept()


class ConfirmConsumptionDialog(QDialog):
    """Seção 17: nunca grava automaticamente ao receber o peso."""

    def __init__(self, command_code: str, weight_kg: Decimal, price: Decimal, total: Decimal,
                 parent=None):
        super().__init__(parent)
        self.setWindowTitle("Confirmar consumo")
        self.setModal(True)
        self.setMinimumWidth(460)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(10)

        head = QLabel(f"COMANDA {command_code}")
        head.setObjectName("appTitle")
        layout.addWidget(head)
        for label, value in (("Peso líquido", format_kg(weight_kg)), ("Preço/kg", format_brl(price))):
            row = QHBoxLayout()
            name = QLabel(label)
            name.setObjectName("fieldLabel")
            val = QLabel(value)
            val.setObjectName("priceValue")
            row.addWidget(name)
            row.addStretch(1)
            row.addWidget(val)
            layout.addLayout(row)
        total_label = QLabel(format_brl(total))
        total_label.setObjectName("moneyValue")
        total_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(total_label)

        confirm = _button("CONFIRMAR", "primary")
        cancel = _button("CANCELAR")
        confirm.clicked.connect(self.accept)
        cancel.clicked.connect(self.reject)
        layout.addLayout(_buttons_row(cancel, confirm))


class CancelConsumptionDialog(QDialog):
    def __init__(self, description: str, total: Decimal, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Cancelar lançamento")
        self.setModal(True)
        self.setMinimumWidth(420)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(10)
        layout.addWidget(QLabel(f"Cancelar {description} ({format_brl(total)})?"))
        hint = QLabel("O lançamento não é apagado: fica marcado como cancelado, com motivo, data e operador.")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.reason = QPlainTextEdit()
        self.reason.setPlaceholderText("Motivo do cancelamento")
        self.reason.setFixedHeight(80)
        layout.addWidget(self.reason)
        back = _button("VOLTAR")
        ok = _button("CANCELAR LANÇAMENTO", "danger")
        back.clicked.connect(self.reject)
        ok.clicked.connect(self._confirm)
        layout.addLayout(_buttons_row(back, ok))

    def _confirm(self) -> None:
        if len(self.reason.toPlainText().strip()) < 3:
            QMessageBox.warning(self, "Motivo obrigatório", "Informe o motivo do cancelamento.")
            return
        self.accept()

    @property
    def reason_text(self) -> str:
        return self.reason.toPlainText().strip()


class ChangePriceDialog(QDialog):
    """RF019: alterar o preço/kg exige PIN de gerente."""

    def __init__(self, current: Decimal, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Alterar preço/kg")
        self.setModal(True)
        self.setMinimumWidth(380)
        self.new_price: Optional[Decimal] = None
        self.manager_pin = ""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(10)
        layout.addWidget(QLabel(f"Preço vigente: {format_brl(current)}"))
        form = QFormLayout()
        self.price = QLineEdit()
        self.price.setPlaceholderText("Novo preço/kg, ex.: 82,90")
        self.pin = QLineEdit()
        self.pin.setEchoMode(QLineEdit.EchoMode.Password)
        self.pin.setPlaceholderText("PIN do gerente")
        form.addRow("Novo preço", self.price)
        form.addRow("Autorização", self.pin)
        layout.addLayout(form)
        cancel = _button("CANCELAR")
        ok = _button("SALVAR", "primary")
        cancel.clicked.connect(self.reject)
        ok.clicked.connect(self._save)
        layout.addLayout(_buttons_row(cancel, ok))

    def _save(self) -> None:
        try:
            value = to_decimal(self.price.text())
            if value <= 0:
                raise InvalidOperation
        except (InvalidOperation, ValueError):
            QMessageBox.warning(self, "Preço inválido", "Informe um preço maior que zero, ex.: 82,90")
            return
        self.new_price = value
        self.manager_pin = self.pin.text()
        self.accept()


class ScaleSettingsDialog(QDialog):
    """Seção 18: a configuração da balança fica nas configurações, não no código."""

    def __init__(self, settings: ScaleSettings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Configuração da balança")
        self.setModal(True)
        self.setMinimumWidth(460)
        self._settings = settings

        self.mode = QComboBox()
        self.mode.addItem("Simulada (sem hardware)", "simulated")
        self.mode.addItem("Balança real (porta serial)", "serial")
        self.mode.setCurrentIndex(0 if settings.mode == "simulated" else 1)

        self.manufacturer = QLineEdit(f"{settings.manufacturer} {settings.model}")
        self.manufacturer.setReadOnly(True)
        self.protocol = QComboBox()
        self.protocol.addItem("Prt5")
        self.protocol.setEnabled(False)

        self.port = QComboBox()
        self.port.setEditable(True)
        for name in self._available_ports():
            self.port.addItem(name)
        self.port.setCurrentText(settings.port)
        self.baud = QComboBox()
        for b in (2400, 4800, 9600):
            self.baud.addItem(str(b), b)
        self.baud.setCurrentText(str(settings.baudrate))
        self.bits = QComboBox()
        for b in (7, 8):
            self.bits.addItem(str(b), b)
        self.bits.setCurrentText(str(settings.data_bits))
        self.parity = QComboBox()
        self.parity.addItem("Nenhuma", "N")
        self.parity.addItem("Par", "E")
        self.parity.setCurrentIndex(0 if settings.parity == "N" else 1)
        self.stop = QComboBox()
        for b in (1, 2):
            self.stop.addItem(str(b), b)
        self.stop.setCurrentText(str(settings.stop_bits))
        self.tare = QSpinBox()
        self.tare.setRange(0, 32000)
        self.tare.setSuffix(" g")
        self.tare.setValue(settings.default_tare_g)
        self.send_price = QCheckBox("Enviar o preço/kg para o display da balança")
        self.send_price.setChecked(settings.send_price_to_scale)

        form = QFormLayout()
        form.setSpacing(10)
        for label, widget in (("Modo", self.mode), ("Balança", self.manufacturer),
                              ("Protocolo", self.protocol), ("Porta", self.port),
                              ("Baudrate", self.baud), ("Data bits", self.bits),
                              ("Paridade", self.parity), ("Stop bits", self.stop),
                              ("Tara padrão", self.tare)):
            form.addRow(label, widget)

        hint = QLabel("A velocidade, os bits e a paridade precisam ser iguais aos configurados na "
                      "balança (C15 e demais). Protocolo e velocidade só são alterados na balança "
                      "com a senha técnica.")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        self.result = QLabel("")
        self.result.setWordWrap(True)

        test = _button("TESTAR CONEXÃO")
        test.clicked.connect(self._test)
        cancel = _button("CANCELAR")
        save = _button("SALVAR", "primary")
        cancel.clicked.connect(self.reject)
        save.clicked.connect(self.accept)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)
        layout.addLayout(form)
        layout.addWidget(self.send_price)
        layout.addWidget(hint)
        layout.addWidget(self.result)
        row = QHBoxLayout()
        row.addWidget(test)
        row.addStretch(1)
        row.addWidget(cancel)
        row.addWidget(save)
        layout.addLayout(row)
        self.mode.currentIndexChanged.connect(self._sync_enabled)
        self._sync_enabled()

    @staticmethod
    def _available_ports() -> list[str]:
        try:
            from serial.tools import list_ports
            return [p.device for p in list_ports.comports()]
        except Exception:
            return []

    def _sync_enabled(self) -> None:
        real = self.mode.currentData() == "serial"
        for w in (self.port, self.baud, self.bits, self.parity, self.stop):
            w.setEnabled(real)

    def values(self) -> ScaleSettings:
        return replace(
            self._settings, mode=self.mode.currentData(), port=self.port.currentText().strip(),
            baudrate=self.baud.currentData(), data_bits=self.bits.currentData(),
            parity=self.parity.currentData(), stop_bits=self.stop.currentData(),
            default_tare_g=self.tare.value(), send_price_to_scale=self.send_price.isChecked())

    def _show(self, text: str, tone: str) -> None:
        self.result.setText(text)
        self.result.setProperty("valueTone", tone)
        repolish(self.result)

    def _test(self) -> None:
        cfg = self.values()
        if cfg.mode == "simulated":
            self._show("Modo simulado: nada a testar na porta.", "muted")
            return
        driver = ToledoPrix3Fit(pyserial_factory(cfg.port, cfg.baudrate, cfg.data_bits, cfg.parity,
                                                  cfg.stop_bits, cfg.timeout_s))
        try:
            driver.connect()
            reading = driver.get_weight()
            shown = format_kg(reading.weight_kg) if reading.weight_kg is not None else reading.status.value
            self._show(f"Conectada. Resposta bruta: {reading.raw_hex}  →  {shown}", "ok")
        except Exception as exc:
            self._show(f"Falha: {exc}", "error")
        finally:
            driver.disconnect()


class CpfDialog(QDialog):
    """Pede o CPF (teclado na tela). `digits` fica vazio se o operador optar por seguir sem CPF."""

    def __init__(self, title: str = "CPF do cliente", allow_skip: bool = True, parent=None):
        super().__init__(parent)
        from .keypad import CpfInput          # import tardio: keypad importa este módulo
        self.setWindowTitle(title)
        self.setModal(True)
        self.digits = ""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(14)
        heading = QLabel(title)
        heading.setObjectName("appTitle")
        layout.addWidget(heading)
        self.cpf = CpfInput()
        self.cpf.submitted.connect(self._ok)
        layout.addWidget(self.cpf)
        self.ok_btn = _button("CONFIRMAR", "primary")
        self.ok_btn.setEnabled(False)
        self.ok_btn.clicked.connect(self._ok)
        cancel = _button("CANCELAR")
        cancel.clicked.connect(self.reject)
        buttons = [cancel]
        if allow_skip:
            skip = _button("SEM CPF")
            skip.clicked.connect(self._skip)
            buttons.append(skip)
        buttons.append(self.ok_btn)
        layout.addLayout(_buttons_row(*buttons))
        self.cpf.changed.connect(lambda: self.ok_btn.setEnabled(self.cpf.is_valid))
        self.cpf.setFocus()

    def _ok(self) -> None:
        if self.cpf.is_valid:
            self.digits = self.cpf.digits
            self.accept()

    def _skip(self) -> None:
        self.digits = ""
        self.accept()

"""Autopagamento: o cliente lê a comanda (ou informa o CPF), confere e paga no TEF."""
from datetime import datetime
from decimal import Decimal
from typing import Optional

from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (QApplication, QHBoxLayout, QInputDialog, QMessageBox, QLabel, QLineEdit, QMainWindow,
                               QStackedWidget, QVBoxLayout, QWidget)

from ..bootstrap import Services
from ..config.settings import AppSettings, config_dir
from ..domain.cpf import format_cpf, is_valid_cpf, only_digits
from ..domain.money import format_brl
from ..domain.payment import METHOD_LABELS
from ..payments.gateway import PaymentGateway, PaymentResult, build_gateway
from ..payments.runner import ChargeRunner
from ..printing.printer import PrintResult, TicketPrinter
from ..printing.ticket import KIND_RECEIPT, build_ticket
from ..services.dto import CommandInfo
from ..services.errors import BusinessError
from .common import ItemsTable, NOT_OPEN_MESSAGE
from .dialogs import _button
from .keypad import CpfInput
from .widgets import set_value_tone

(WELCOME, CPF, SUMMARY, PAYING, DONE) = range(5)
ELECTRONIC_METHODS = ["PIX", "CREDIT", "DEBIT"]          # dinheiro só no caixa com operador


class SelfCheckoutWindow(QMainWindow):
    def __init__(self, settings: AppSettings, services: Services,
                 gateway: Optional[PaymentGateway] = None):
        super().__init__()
        self.settings = settings
        self.services = services
        self.op = services.auth.self_service_operator()
        self.printer = TicketPrinter(settings.printing)
        self.runner = ChargeRunner(gateway or build_gateway(settings.checkout.gateway), self)
        self.runner.finished.connect(self._on_charged)
        self.command: Optional[CommandInfo] = None
        self._charging: Optional[tuple[str, Decimal]] = None

        self.setWindowTitle("Autopagamento")
        self.resize(1280, 860)
        self.setMinimumSize(1000, 720)
        self.stack = QStackedWidget()
        root = QWidget()
        root.setObjectName("root")
        lay = QVBoxLayout(root)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.stack)
        self.setCentralWidget(root)
        for build in (self._build_welcome, self._build_cpf, self._build_summary, self._build_paying,
                      self._build_done):
            self.stack.addWidget(build())

        self.done_timer = QTimer(self, singleShot=True)
        self.done_timer.timeout.connect(self._finish)
        self.idle_timer = QTimer(self, singleShot=True)
        self.idle_timer.timeout.connect(self._on_idle)
        QApplication.instance().installEventFilter(self)
        QShortcut(QKeySequence("Ctrl+Shift+Q"), self, activated=self._admin_exit)
        self._go(WELCOME)

    # ================================================================= construção
    def _page(self):
        page = QWidget()
        page.setObjectName("root")
        lay = QVBoxLayout(page)
        lay.setContentsMargins(70, 40, 70, 40)
        lay.setSpacing(18)
        return page, lay

    @staticmethod
    def _label(text="", name="", align=Qt.AlignmentFlag.AlignCenter) -> QLabel:
        label = QLabel(text)
        if name:
            label.setObjectName(name)
        label.setAlignment(align)
        label.setWordWrap(True)
        return label

    def _build_welcome(self) -> QWidget:
        page, lay = self._page()
        lay.addStretch(2)
        lay.addWidget(self._label("Pagamento", "hero"))
        lay.addWidget(self._label("Aproxime a sua comanda do leitor", "heroSub"))
        self.scan_input = QLineEdit()
        self.scan_input.setObjectName("commandInput")
        self.scan_input.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.scan_input.returnPressed.connect(self._scan)
        holder = QHBoxLayout()
        holder.addStretch(1)
        holder.addWidget(self.scan_input, 4)
        holder.addStretch(1)
        lay.addLayout(holder)
        self.welcome_msg = self._label("", "bigMessage")
        lay.addWidget(self.welcome_msg)
        self.lost_btn = _button("PERDI MINHA COMANDA", "kiosk")
        self.lost_btn.clicked.connect(lambda: self._go(CPF))
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(self.lost_btn, 2)
        row.addStretch(1)
        lay.addLayout(row)
        lay.addStretch(3)
        return page

    def _build_cpf(self) -> QWidget:
        page, lay = self._page()
        lay.addWidget(self._label("Informe seu CPF", "stepTitle"))
        lay.addWidget(self._label("Vamos localizar a sua comanda.", "stepHint"))
        self.cpf = CpfInput()
        self.cpf.changed.connect(lambda: (self.cpf_ok.setEnabled(self.cpf.is_valid),
                                          self.cpf_msg.setText("")))
        self.cpf.submitted.connect(self._cpf_confirm)
        holder = QHBoxLayout()
        holder.addStretch(1)
        holder.addWidget(self.cpf, 3)
        holder.addStretch(1)
        lay.addLayout(holder, 1)
        self.cpf_msg = self._label("", "bigMessage")
        lay.addWidget(self.cpf_msg)
        row = QHBoxLayout()
        back = _button("← VOLTAR", "kiosk")
        back.clicked.connect(lambda: self._go(WELCOME))
        self.cpf_ok = _button("CONFIRMAR", "kioskPrimary")
        self.cpf_ok.setEnabled(False)
        self.cpf_ok.clicked.connect(self._cpf_confirm)
        row.addWidget(back)
        row.addStretch(1)
        row.addWidget(self.cpf_ok)
        lay.addLayout(row)
        return page

    def _build_summary(self) -> QWidget:
        page, lay = self._page()
        self.sum_title = self._label("", "stepTitle")
        lay.addWidget(self.sum_title)
        self.sum_table = ItemsTable(row_height=52, font_px=20)
        lay.addWidget(self.sum_table, 1)
        total_row = QHBoxLayout()
        total_row.addWidget(self._label("Total a pagar", "stepHint", Qt.AlignmentFlag.AlignLeft))
        self.sum_total = self._label("", "moneyValue", Qt.AlignmentFlag.AlignRight)
        total_row.addWidget(self.sum_total)
        lay.addLayout(total_row)
        self.sum_msg = self._label("", "bigMessage")
        lay.addWidget(self.sum_msg)
        lay.addWidget(self._label("Como deseja pagar?", "stepHint"))
        row = QHBoxLayout()
        row.setSpacing(16)
        self.pay_buttons = {}
        for code in ELECTRONIC_METHODS:
            btn = _button(METHOD_LABELS[code].upper(), "kioskPrimary")
            btn.clicked.connect(lambda _=False, c=code: self._pay(c))
            row.addWidget(btn)
            self.pay_buttons[code] = btn
        lay.addLayout(row)
        back = _button("← Cancelar", "kiosk")
        back.clicked.connect(self._finish)
        lay.addWidget(back, 0, Qt.AlignmentFlag.AlignLeft)
        return page

    def _build_paying(self) -> QWidget:
        page, lay = self._page()
        lay.addStretch(1)
        lay.addWidget(self._label("Siga as instruções de pagamento", "hero"))
        self.paying_amount = self._label("", "moneyValue")
        lay.addWidget(self.paying_amount)
        self.paying_method = self._label("", "heroSub")
        lay.addWidget(self.paying_method)
        lay.addWidget(self._label("Aguarde a aprovação…", "stepHint"))
        lay.addStretch(2)
        return page

    def _build_done(self) -> QWidget:
        page, lay = self._page()
        lay.addStretch(1)
        self.done_title = self._label("Pagamento aprovado!", "hero")
        lay.addWidget(self.done_title)
        self.done_code = self._label("", "bigCode")
        lay.addWidget(self.done_code)
        self.done_msg = self._label("", "heroSub")
        lay.addWidget(self.done_msg)
        ok = _button("OK", "kioskPrimary")
        ok.clicked.connect(self._finish)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(ok, 2)
        row.addStretch(1)
        lay.addLayout(row)
        lay.addStretch(2)
        return page

    # ================================================================= navegação
    def _go(self, page: int) -> None:
        self.stack.setCurrentIndex(page)
        self.done_timer.stop()
        if page == WELCOME:
            self.idle_timer.stop()
            self.scan_input.clear()
            self.scan_input.setFocus()
        elif page != PAYING:
            self._touch()
        if page == CPF:
            self.cpf.clear()
            self.cpf.setFocus()
        if page == DONE:
            self.done_timer.start(self.settings.checkout.auto_return_s * 1000)

    def _finish(self) -> None:
        if self.runner.busy:                       # não abandona uma cobrança em andamento
            return
        self.command = None
        self.welcome_msg.setText("")
        self._go(WELCOME)

    def _touch(self) -> None:
        seconds = self.settings.kiosk.idle_timeout_s
        if seconds > 0 and self.stack.currentIndex() not in (WELCOME, PAYING):
            self.idle_timer.start(seconds * 1000)

    def _on_idle(self) -> None:
        if self.stack.currentIndex() not in (WELCOME, PAYING):
            self._finish()

    def eventFilter(self, obj, event) -> bool:
        if event.type() in (QEvent.Type.MouseButtonPress, QEvent.Type.KeyPress):
            self._touch()
        return super().eventFilter(obj, event)

    def _admin_exit(self) -> None:
        pin, ok = QInputDialog.getText(self, "Sair do autopagamento", "PIN do gerente:",
                                       QLineEdit.EchoMode.Password)
        if not ok:
            return
        try:
            if self.services.auth.authenticate_admin(pin):
                self.close()
        except BusinessError as exc:              # PIN travado por tentativas erradas, servidor fora do ar...
            QMessageBox.warning(self, "Não autorizado", str(exc))

    # ================================================================= localizar a comanda
    def _welcome_error(self, text: str) -> None:
        self.welcome_msg.setText(text)
        set_value_tone(self.welcome_msg, "error")
        self.scan_input.setFocus()

    def _scan(self) -> None:
        raw = self.scan_input.text()
        self.scan_input.clear()
        if not raw.strip():
            return
        digits = only_digits(raw)
        try:
            if len(digits) == 11:
                self._open(self._by_cpf(digits))
            else:
                self._open(self.services.commands.find(raw))
        except BusinessError as exc:
            self._welcome_error(str(exc).replace("\n", " ") + " Procure o caixa.")

    def _by_cpf(self, cpf: str) -> CommandInfo:
        if not is_valid_cpf(cpf):
            raise BusinessError("CPF inválido. Confira os números digitados.")
        found = self.services.commands.open_commands_by_cpf(cpf)
        if not found:
            raise BusinessError(f"Nenhuma comanda em aberto para o CPF {format_cpf(cpf)}.")
        if len(found) > 1:                      # não adivinha qual pagar: cobraria a comanda errada
            raise BusinessError("Há mais de uma comanda em aberto para este CPF. "
                                "Leia a comanda impressa no leitor.")
        return self.services.commands.get(found[0].id)

    def _cpf_confirm(self) -> None:
        if not self.cpf.is_valid:
            return
        try:
            self._open(self._by_cpf(self.cpf.digits), from_cpf=True)
        except BusinessError as exc:
            self.cpf_msg.setText(str(exc))

    def _open(self, info: CommandInfo, from_cpf: bool = False) -> None:
        if info.status not in ("OPEN", "AWAITING_PAYMENT"):
            self._go(WELCOME)
            self._welcome_error(NOT_OPEN_MESSAGE.get(info.status, "Comanda indisponível para pagamento."))
            return
        if not info.active_items or info.remaining <= 0:
            self._go(WELCOME)
            self._welcome_error("Esta comanda não possui itens a pagar. Procure o caixa.")
            return
        self.command = info
        self._render_summary()
        self._go(SUMMARY)

    def _render_summary(self) -> None:
        info = self.command
        self.sum_title.setText(f"Comanda {info.code}")
        self.sum_table.set_items(info.items)
        self.sum_total.setText(format_brl(info.remaining))
        self.sum_msg.setText("")

    # ================================================================= pagamento
    def _pay(self, method: str) -> None:
        if self.runner.busy or self.command is None:
            return
        try:
            info = self.services.commands.get(self.command.id)
            if info.status == "OPEN":
                info = self.services.commands.send_to_payment(info.id)     # trava novos lançamentos
            if info.status != "AWAITING_PAYMENT" or info.remaining <= 0:
                raise BusinessError(NOT_OPEN_MESSAGE.get(info.status, "Comanda indisponível para pagamento."))
        except BusinessError as exc:
            self.sum_msg.setText(str(exc).replace("\n", " "))
            set_value_tone(self.sum_msg, "error")
            return
        self.command = info
        amount = info.remaining
        self._charging = (method, amount)
        self.paying_amount.setText(format_brl(amount))
        self.paying_method.setText(METHOD_LABELS[method])
        self._go(PAYING)
        self.runner.start(method, amount, f"Comanda {info.code}")

    def _on_charged(self, result: PaymentResult) -> None:
        method, amount = self._charging
        self._charging = None
        if not result.approved:
            self._render_summary()
            self.sum_msg.setText((result.message or "Pagamento não aprovado.") + " Tente novamente ou outra forma.")
            set_value_tone(self.sum_msg, "error")
            self._go(SUMMARY)
            return
        try:
            self.command = self.services.commands.register_payment(
                self.command.id, self.op.id, method, amount, reference=result.reference)
        except Exception as exc:
            # cobrou no cartão, mas não gravou: nunca perder o rastro do NSU
            self._log_orphan(method, amount, result, exc)
            self.done_title.setText("Atenção")
            self.done_code.setText("")
            self.done_msg.setText(f"Pagamento aprovado, mas não foi possível registrá-lo. Chame um atendente. "
                                  f"Código: {result.reference}")
            self._go(DONE)
            return
        self.done_title.setText("Pagamento aprovado!")
        self.done_code.setText(self.command.code)
        message = "Obrigado! Boa viagem."
        if self.settings.printing.print_receipt:
            printed = self._print_receipt()
            message = ("Retire seu comprovante. " if printed.ok else "Não foi possível imprimir o comprovante. ") + message
        self.done_msg.setText(message)
        self._go(DONE)

    def _print_receipt(self) -> PrintResult:
        try:
            return self.printer.print_ticket(
                build_ticket(self.command, KIND_RECEIPT, self.settings.printing.title))
        except Exception as exc:
            return PrintResult(False, "", str(exc))

    def _log_orphan(self, method: str, amount: Decimal, result: PaymentResult, error: Exception) -> None:
        line = (f"{datetime.now().isoformat(timespec='seconds')};comanda={self.command.code};"
                f"metodo={method};valor={amount};ref={result.reference};erro={error}\n")
        try:
            with open(config_dir() / "pagamentos_pendentes.log", "a", encoding="utf-8") as fh:
                fh.write(line)
        except OSError:
            pass

    def closeEvent(self, event) -> None:
        QApplication.instance().removeEventFilter(self)
        super().closeEvent(event)

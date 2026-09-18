"""Caixa manual: o operador lê a comanda (ou informa o CPF), confere e registra o pagamento."""
from decimal import Decimal, InvalidOperation
from typing import Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QButtonGroup, QHBoxLayout, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QMainWindow, QMessageBox, QPushButton, QVBoxLayout,
                               QWidget)

from ..bootstrap import Services
from ..config.settings import AppSettings
from ..domain.cpf import format_cpf, is_valid_cpf, mask_cpf, only_digits
from ..domain.money import format_brl, to_decimal
from ..domain.payment import METHOD_LABELS
from ..printing.printer import PrintResult, TicketPrinter
from ..printing.ticket import KIND_COMMAND, KIND_RECEIPT, build_ticket
from ..services.dto import CommandInfo, CommandSummary, OperatorInfo
from ..services.errors import BusinessError
from .common import ItemsTable, NOT_OPEN_MESSAGE, STATUS_VIEW
from .dialogs import LoginDialog, _button
from .theme import repolish
from .widgets import Card, Chip, set_value_tone

METHODS = ["CASH", "PIX", "CREDIT", "DEBIT"]
REFRESH_MS = 2000


class CashierWindow(QMainWindow):
    def __init__(self, settings: AppSettings, services: Services, operator: OperatorInfo):
        super().__init__()
        self.settings = settings
        self.services = services
        self.operator = operator
        self.printer = TicketPrinter(settings.printing)
        self.command: Optional[CommandInfo] = None
        self.method = "CASH"
        self._queue_ids: list[int] = []

        self.setWindowTitle("Caixa — Pagamento")
        self.resize(1360, 860)
        self.setMinimumSize(1180, 760)
        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self._build_header())
        body = QHBoxLayout()
        body.setContentsMargins(20, 20, 20, 20)
        body.setSpacing(20)
        body.addLayout(self._build_left(), 4)
        body.addLayout(self._build_right(), 7)
        outer.addLayout(body, 1)

        self.timer = QTimer(self)
        self.timer.setInterval(REFRESH_MS)
        self.timer.timeout.connect(self._poll)
        self.timer.start()
        self._refresh_queue()
        self._render()
        self.scan_input.setFocus()

    # ================================================================= construção
    def _build_header(self) -> QWidget:
        from PySide6.QtWidgets import QFrame
        header = QFrame()
        header.setObjectName("header")
        lay = QHBoxLayout(header)
        lay.setContentsMargins(24, 14, 24, 14)
        titles = QVBoxLayout()
        titles.setSpacing(0)
        title = QLabel("Caixa")
        title.setObjectName("appTitle")
        sub = QLabel("Leitura da comanda e pagamento")
        sub.setObjectName("appSubtitle")
        titles.addWidget(title)
        titles.addWidget(sub)
        lay.addLayout(titles)
        lay.addStretch(1)
        self.operator_label = QLabel(f"Operador: {self.operator.name}")
        self.operator_label.setObjectName("muted")
        self.switch_btn = _button("Trocar operador")
        self.switch_btn.clicked.connect(self._switch_operator)
        lay.addWidget(self.operator_label)
        lay.addWidget(self.switch_btn)
        return header

    def _build_left(self) -> QVBoxLayout:
        col = QVBoxLayout()
        col.setSpacing(16)
        scan = Card("Ler comanda")
        self.scan_input = QLineEdit()
        self.scan_input.setObjectName("commandInput")
        self.scan_input.setPlaceholderText("Comanda ou CPF")
        self.scan_input.returnPressed.connect(self._scan)
        scan.body.addWidget(self.scan_input)
        self.scan_msg = QLabel("")
        self.scan_msg.setObjectName("message")
        self.scan_msg.setWordWrap(True)
        scan.body.addWidget(self.scan_msg)
        col.addWidget(scan)

        queue = Card("Aguardando pagamento")
        self.queue = QListWidget()
        self.queue.setStyleSheet("QListWidget { background: #1C2937; border: 1px solid #2A3B4D; "
                                 "border-radius: 10px; font-size: 16px; } "
                                 "QListWidget::item { padding: 12px; border-bottom: 1px solid #223142; } "
                                 "QListWidget::item:selected { background: #23415C; }")
        self.queue.itemClicked.connect(self._pick_from_queue)
        queue.body.addWidget(self.queue, 1)
        col.addWidget(queue, 1)
        return col

    def _build_right(self) -> QVBoxLayout:
        col = QVBoxLayout()
        col.setSpacing(16)

        card = Card("Comanda")
        head = QHBoxLayout()
        self.code_label = QLabel("—")
        self.code_label.setObjectName("commandTotal")
        self.status_chip = Chip("SEM COMANDA", "muted")
        self.cpf_label = QLabel("")
        self.cpf_label.setObjectName("muted")
        head.addWidget(self.code_label)
        head.addWidget(self.status_chip)
        head.addStretch(1)
        head.addWidget(self.cpf_label)
        card.body.addLayout(head)
        self.table = ItemsTable(row_height=40)
        self.table.setMinimumHeight(230)
        card.body.addWidget(self.table, 1)
        totals = QHBoxLayout()
        self.total_label = self._money_label("Total")
        self.paid_label = self._money_label("Pago")
        self.remaining_label = self._money_label("Restante", big=True)
        for box in (self.total_label, self.paid_label, self.remaining_label):
            totals.addLayout(box[0])
            totals.setAlignment(box[0], Qt.AlignmentFlag.AlignTop)
        card.body.addLayout(totals)
        col.addWidget(card, 3)

        pay = Card("Pagamento")
        methods = QHBoxLayout()
        methods.setSpacing(10)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.method_buttons: dict[str, QPushButton] = {}
        for code in METHODS:
            btn = _button(METHOD_LABELS[code], "method")
            btn.setCheckable(True)
            btn.clicked.connect(lambda _=False, c=code: self._select_method(c))
            self.group.addButton(btn)
            methods.addWidget(btn)
            self.method_buttons[code] = btn
        pay.body.addLayout(methods)

        fields = QHBoxLayout()
        self.amount = QLineEdit()
        self.amount.setPlaceholderText("Valor a pagar")
        self.tendered = QLineEdit()
        self.tendered.setPlaceholderText("Valor recebido")
        self.reference = QLineEdit()
        self.reference.setPlaceholderText("NSU / ID (opcional)")
        self.change_label = QLabel("")
        self.change_label.setObjectName("priceValue")
        self.field_boxes = {}
        for key, caption, widget in (("amount", "VALOR A PAGAR", self.amount),
                                     ("tendered", "VALOR RECEBIDO", self.tendered),
                                     ("reference", "NSU / ID (OPCIONAL)", self.reference)):
            box = QVBoxLayout()
            title = QLabel(caption)
            title.setObjectName("cardTitle")
            box.addWidget(title)
            box.addWidget(widget)
            fields.addLayout(box, 1)
            self.field_boxes[key] = (title, widget)
        fields.addWidget(self.change_label, 0, Qt.AlignmentFlag.AlignBottom)
        pay.body.addLayout(fields)
        self.amount.textChanged.connect(self._update_change)
        self.tendered.textChanged.connect(self._update_change)

        actions = QHBoxLayout()
        self.reopen_btn = _button("Reabrir comanda")
        self.print_btn = _button("Imprimir")
        self.pay_btn = _button("REGISTRAR PAGAMENTO", "primary")
        self.reopen_btn.clicked.connect(self._reopen)
        self.print_btn.clicked.connect(self._print)
        self.pay_btn.clicked.connect(self._register)
        actions.addWidget(self.reopen_btn)
        actions.addWidget(self.print_btn)
        actions.addStretch(1)
        actions.addWidget(self.pay_btn, 2)
        pay.body.addLayout(actions)
        self.banner = QLabel("")
        self.banner.setObjectName("message")
        self.banner.setWordWrap(True)
        pay.body.addWidget(self.banner)
        col.addWidget(pay, 2)
        self._select_method("CASH")
        return col

    @staticmethod
    def _money_label(title: str, big: bool = False):
        box = QVBoxLayout()
        name = QLabel(title.upper())
        name.setObjectName("cardTitle")
        value = QLabel(format_brl(Decimal("0")))
        value.setObjectName("moneyValue" if big else "commandTotal")
        box.addWidget(name)
        box.addWidget(value)
        return box, value

    # ================================================================= fila e leitura
    def _poll(self) -> None:
        try:
            self._refresh_queue()
            if self.command is not None:
                fresh = self.services.commands.get(self.command.id)
                if (fresh.status, fresh.total, fresh.paid) != (
                        self.command.status, self.command.total, self.command.paid):
                    self.command = fresh
                    self._render(reset_amount=True)
        except Exception as exc:                 # banco fora do ar: avisa, não derruba o caixa
            self.scan_msg.setText(f"Sem conexão com o banco de dados: {exc}")
            set_value_tone(self.scan_msg, "error")

    def _refresh_queue(self) -> None:
        rows: list[CommandSummary] = self.services.commands.list_awaiting_payment()
        ids = [r.id for r in rows]
        if ids == self._queue_ids and self.queue.count() == len(rows):
            return
        self._queue_ids = ids
        current = self.command.id if self.command else None
        self.queue.clear()
        for row in rows:
            time = row.closed_at.strftime("%H:%M") if row.closed_at else ""
            cpf = f" · CPF {mask_cpf(row.customer_cpf)}" if row.customer_cpf else ""
            item = QListWidgetItem(f"{row.code} · {format_brl(row.total - row.paid)}{cpf} · {time}")
            item.setData(Qt.ItemDataRole.UserRole, row.id)
            self.queue.addItem(item)
            if row.id == current:
                self.queue.setCurrentItem(item)

    def _pick_from_queue(self, item: QListWidgetItem) -> None:
        self._load(self.services.commands.get(item.data(Qt.ItemDataRole.UserRole)))

    def _scan(self) -> None:
        raw = self.scan_input.text()
        self.scan_input.clear()
        if not raw.strip():
            return
        digits = only_digits(raw)
        try:
            if len(digits) == 11:
                if not is_valid_cpf(digits):
                    raise BusinessError("CPF inválido. Confira os números digitados.")
                found = self.services.commands.open_commands_by_cpf(digits)
                if not found:
                    raise BusinessError(f"Nenhuma comanda em aberto para o CPF {format_cpf(digits)}.")
                note = f" ({len(found)} comandas abertas para este CPF; mostrando a mais recente)" if len(found) > 1 else ""
                self._load(self.services.commands.get(found[0].id), note)
            else:
                self._load(self.services.commands.find(raw))
        except BusinessError as exc:
            self.command = None
            self._render()
            self.scan_msg.setText(str(exc))
            set_value_tone(self.scan_msg, "error")

    def _load(self, info: CommandInfo, note: str = "") -> None:
        self.command = info
        self.banner.setText("")
        if info.status == "PAID":
            self.scan_msg.setText(f"Comanda {info.code}: {NOT_OPEN_MESSAGE['PAID']}")
            set_value_tone(self.scan_msg, "info")
        elif info.status in ("CANCELLED", "CLOSED"):
            self.scan_msg.setText(f"Comanda {info.code}: {NOT_OPEN_MESSAGE[info.status]}")
            set_value_tone(self.scan_msg, "error")
        else:
            self.scan_msg.setText(f"Comanda {info.code} carregada.{note}")
            set_value_tone(self.scan_msg, "ok")
        self._render(reset_amount=True)

    # ================================================================= exibição
    def _payable(self) -> bool:
        info = self.command
        return bool(info and info.status in ("OPEN", "AWAITING_PAYMENT") and info.remaining > 0
                    and info.active_items)

    def _render(self, reset_amount: bool = False) -> None:
        info = self.command
        if info is None:
            self.code_label.setText("—")
            self.status_chip.set_state("SEM COMANDA", "muted")
            self.cpf_label.setText("")
            self.table.setRowCount(0)
            for _, value in (self.total_label, self.paid_label, self.remaining_label):
                value.setText(format_brl(Decimal("0")))
        else:
            self.code_label.setText(info.code)
            self.status_chip.set_state(*STATUS_VIEW.get(info.status, (info.status, "muted")))
            self.cpf_label.setText(f"CPF {mask_cpf(info.customer_cpf)}" if info.customer_cpf else "sem CPF")
            self.table.set_items(info.items)
            self.total_label[1].setText(format_brl(info.total))
            self.paid_label[1].setText(format_brl(info.paid))
            self.remaining_label[1].setText(format_brl(info.remaining))
        if reset_amount:
            self.amount.setText(f"{info.remaining:.2f}".replace(".", ",") if info and self._payable() else "")
            self.tendered.clear()
            self.reference.clear()
        self._refresh_actions()

    def _select_method(self, code: str) -> None:
        self.method = code
        self.method_buttons[code].setChecked(True)
        cash = code == "CASH"
        for key, visible in (("tendered", cash), ("reference", not cash)):
            title, widget = self.field_boxes[key]
            title.setVisible(visible)
            widget.setVisible(visible)
        self.change_label.setVisible(cash)
        self._update_change()

    def _parse(self, text: str) -> Optional[Decimal]:
        try:
            return to_decimal(text) if text.strip() else None
        except (InvalidOperation, ValueError):
            return None

    def _update_change(self) -> None:
        amount, tendered = self._parse(self.amount.text()), self._parse(self.tendered.text())
        if self.method == "CASH" and amount is not None and tendered is not None and tendered >= amount:
            self.change_label.setText(f"Troco {format_brl(tendered - amount)}")
        else:
            self.change_label.setText("")

    def _refresh_actions(self) -> None:
        info = self.command
        self.pay_btn.setEnabled(self._payable())
        for w in (self.amount, self.tendered, self.reference):
            w.setEnabled(self._payable())
        for b in self.method_buttons.values():
            b.setEnabled(self._payable())
        self.reopen_btn.setEnabled(bool(info and info.status == "AWAITING_PAYMENT" and not info.payments))
        self.print_btn.setEnabled(bool(info and info.status in ("OPEN", "AWAITING_PAYMENT", "PAID")))

    # ================================================================= ações
    def _register(self) -> None:
        info = self.command
        if not self._payable():
            return
        amount = self._parse(self.amount.text())
        if amount is None or amount <= 0:
            self._banner("Informe o valor do pagamento, ex.: 20,00", "error")
            return
        tendered = self._parse(self.tendered.text()) if self.method == "CASH" else None
        try:
            self.command = self.services.commands.register_payment(
                info.id, self.operator.id, self.method, amount, tendered, self.reference.text())
        except BusinessError as exc:
            self._banner(str(exc), "error")
            self._reload_silently()
            return
        payment = self.command.payments[-1]
        if self.command.status == "PAID":
            change = f" Troco: {format_brl(payment.change)}." if payment.change else ""
            self._banner(f"Comanda {self.command.code} paga.{change}", "ok")
            if self.settings.printing.print_receipt:
                self._print_ticket(KIND_RECEIPT)
        else:
            self._banner(f"Pagamento parcial registrado. Restante: {format_brl(self.command.remaining)}", "warn")
        self._render(reset_amount=True)
        self._refresh_queue()
        self.scan_input.setFocus()

    def _reload_silently(self) -> None:
        try:
            self.command = self.services.commands.get(self.command.id)
            self._render(reset_amount=True)
        except BusinessError:
            pass

    def _reopen(self) -> None:
        if not (self.command and self.command.status == "AWAITING_PAYMENT"):
            return
        answer = QMessageBox.question(self, "Reabrir comanda",
                                      f"Devolver a comanda {self.command.code} ao atendimento?\n"
                                      "O cliente poderá lançar novos itens.")
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self.command = self.services.commands.reopen_command(self.command.id)
        except BusinessError as exc:
            self._banner(str(exc), "error")
            return
        self._banner(f"Comanda {self.command.code} reaberta.", "info")
        self._render(reset_amount=True)
        self._refresh_queue()

    def _print(self) -> None:
        if self.command:
            self._print_ticket(KIND_RECEIPT if self.command.status == "PAID" else KIND_COMMAND)

    def _print_ticket(self, kind: str) -> PrintResult:
        try:
            result = self.printer.print_ticket(build_ticket(self.command, kind, self.settings.printing.title))
        except Exception as exc:
            result = PrintResult(False, "", str(exc))
        if not result.ok:
            self._banner(f"Falha ao imprimir: {result.message}", "error")
        return result

    def _banner(self, text: str, tone: str) -> None:
        self.banner.setText(text)
        set_value_tone(self.banner, tone)

    def _switch_operator(self) -> None:
        dialog = LoginDialog(self.services.auth.list_operators(), self.services.auth.authenticate, self)
        if dialog.exec() == dialog.DialogCode.Accepted and dialog.operator:
            self.operator = dialog.operator
            self.operator_label.setText(f"Operador: {self.operator.name}")

    def closeEvent(self, event) -> None:
        self.timer.stop()
        super().closeEvent(event)

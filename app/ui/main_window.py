from decimal import Decimal
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QGroupBox, QHBoxLayout, QHeaderView,
                               QLabel, QLineEdit, QMainWindow, QMessageBox, QPushButton, QSpinBox,
                               QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from ..bootstrap import Services
from ..config.settings import AppSettings, save_settings
from ..domain.money import calculate_total, format_brl, format_kg
from ..hardware.scale import ScaleReading
from ..services.dto import CommandInfo, OperatorInfo
from ..domain.cpf import format_cpf, is_valid_cpf, only_digits
from ..printing.printer import TicketPrinter
from ..printing.ticket import KIND_COMMAND, build_ticket
from ..services.errors import BusinessError, DuplicateOpenCommand, PriceNotFound
from ..services.command_service import WEIGHED_PRODUCT_CODE
from ..services.weighing_service import MESSAGES, StabilityTracker, WeighingState
from .common import NOT_OPEN_MESSAGE, STATUS_VIEW
from .dialogs import (CancelConsumptionDialog, ChangePriceDialog, ConfirmConsumptionDialog,
                      CpfDialog, LoginDialog, ScaleSettingsDialog, _button)
from .theme import repolish
from .simulator_panel import build_simulator_panel
from .widgets import Card, Chip, set_value_tone
from .workers import ScaleController

STATE_VIEW = {
    WeighingState.NO_SCALE: ("SEM BALANÇA", "error", "error"),
    WeighingState.EMPTY: ("PRATO VAZIO", "muted", "muted"),
    WeighingState.SETTLING: ("ESTABILIZANDO…", "warn", "warn"),
    WeighingState.STABLE: ("PESO ESTÁVEL", "ok", "ok"),
    WeighingState.NEGATIVE: ("PESO NEGATIVO", "error", "error"),
    WeighingState.OVERLOAD: ("SOBRECARGA", "error", "error"),
}
NO_SCALE_HELP = ("Balança não conectada. Verifique: cabo, porta COM, alimentação e "
                 "configuração da balança.")


class MainWindow(QMainWindow):
    def __init__(self, settings: AppSettings, services: Services, operator: OperatorInfo):
        super().__init__()
        self.settings = settings
        self.services = services
        self.operator = operator
        self.printer = TicketPrinter(settings.printing)

        self.command: Optional[CommandInfo] = None
        self.price: Optional[Decimal] = None
        self.tracker = StabilityTracker(settings.scale.stable_reads,
                                        Decimal(settings.scale.capacity_kg))
        self.state = WeighingState.NO_SCALE
        self.weight: Optional[Decimal] = None
        self.last_reading: Optional[ScaleReading] = None
        self.tare_sent_g: Optional[int] = None
        self.armed = True             # evita registrar duas vezes o mesmo prato
        self.link_ok = False
        self.scale: Optional[ScaleController] = None
        self._sim_panel: Optional[QGroupBox] = None

        self.setWindowTitle("Restaurante — Registro de consumo")
        self.resize(1360, 900)
        self.setMinimumSize(1180, 820)

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
        body.addLayout(self._build_left(), 11)
        self.right_col = self._build_right()
        body.addLayout(self.right_col, 9)
        outer.addLayout(body, 1)

        self._load_price()
        self._setup_scale()
        self._render_command()
        self._render_weight()
        self.command_input.setFocus()

    # ================================================================= construção
    def _build_header(self) -> QWidget:
        from PySide6.QtWidgets import QFrame
        header = QFrame()
        header.setObjectName("header")
        lay = QHBoxLayout(header)
        lay.setContentsMargins(24, 14, 24, 14)
        lay.setSpacing(12)
        titles = QVBoxLayout()
        titles.setSpacing(0)
        title = QLabel("Restaurante")
        title.setObjectName("appTitle")
        sub = QLabel("Registro de consumo · comida por quilo")
        sub.setObjectName("appSubtitle")
        titles.addWidget(title)
        titles.addWidget(sub)
        lay.addLayout(titles)
        lay.addStretch(1)

        self.scale_chip = Chip("BALANÇA", "muted")
        self.operator_label = QLabel()
        self.operator_label.setObjectName("muted")
        self.switch_btn = _button("Trocar operador")
        self.price_btn = _button("Preço/kg")
        self.settings_btn = _button("Balança")
        self.switch_btn.clicked.connect(self._switch_operator)
        self.price_btn.clicked.connect(self._change_price)
        self.settings_btn.clicked.connect(self._open_scale_settings)
        for w in (self.scale_chip, self.operator_label, self.switch_btn, self.price_btn,
                  self.settings_btn):
            lay.addWidget(w)
        self._update_operator_label()
        return header

    def _build_left(self) -> QVBoxLayout:
        col = QVBoxLayout()
        col.setSpacing(16)

        card = Card("Comanda")
        row = QHBoxLayout()
        self.command_input = QLineEdit()
        self.command_input.setObjectName("commandInput")
        self.command_input.setPlaceholderText("Passe a comanda no leitor ou digite o CPF")
        self.command_input.returnPressed.connect(self._scan)
        self.command_chip = Chip("AGUARDANDO COMANDA", "muted")
        self.new_btn = _button("Nova comanda")
        self.new_btn.clicked.connect(self._new_command)
        row.addWidget(self.command_input, 1)
        row.addWidget(self.command_chip)
        row.addWidget(self.new_btn)
        card.body.addLayout(row)
        self.command_msg = QLabel("")
        self.command_msg.setObjectName("message")
        self.command_msg.setWordWrap(True)
        card.body.addWidget(self.command_msg)
        total_row = QHBoxLayout()
        total_name = QLabel("Total da comanda")
        total_name.setObjectName("fieldLabel")
        self.total_label = QLabel(format_brl(Decimal("0")))
        self.total_label.setObjectName("commandTotal")
        total_row.addWidget(total_name)
        total_row.addStretch(1)
        total_row.addWidget(self.total_label)
        card.body.addLayout(total_row)
        col.addWidget(card)

        items = Card("Lançamentos")
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["ITEM", "PESO / QTD", "PREÇO", "TOTAL", "SITUAÇÃO"])
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        head = self.table.horizontalHeader()
        head.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for i in (1, 2, 3, 4):
            head.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
        for index in range(5):
            header_item = self.table.horizontalHeaderItem(index)
            right = index in (1, 2, 3)
            header_item.setTextAlignment((Qt.AlignmentFlag.AlignRight if right else Qt.AlignmentFlag.AlignLeft)
                                         | Qt.AlignmentFlag.AlignVCenter)
        self.table.itemSelectionChanged.connect(self._refresh_actions)
        items.body.addWidget(self.table, 1)
        actions = QHBoxLayout()
        self.cancel_btn = _button("Cancelar lançamento", "danger")
        self.print_btn = _button("Imprimir comanda")
        self.reopen_btn = _button("Reabrir")
        self.close_btn = _button("Enviar para pagamento")
        self.cancel_btn.clicked.connect(self._cancel_item)
        self.print_btn.clicked.connect(self._print_command)
        self.reopen_btn.clicked.connect(self._reopen_command)
        self.close_btn.clicked.connect(self._close_command)
        actions.addWidget(self.cancel_btn)
        actions.addStretch(1)
        actions.addWidget(self.print_btn)
        actions.addWidget(self.reopen_btn)
        actions.addWidget(self.close_btn)
        items.body.addLayout(actions)
        col.addWidget(items, 1)

        products = Card("Produtos avulsos")
        prow = QHBoxLayout()
        prow.setSpacing(10)
        self.product_buttons: list[QPushButton] = []
        try:
            for product in self.services.commands.unit_products():
                btn = _button(f"{product.description}\n{format_brl(product.price)}", "product")
                btn.clicked.connect(lambda _=False, code=product.code: self._add_unit(code))
                self.product_buttons.append(btn)
                prow.addWidget(btn)
        except BusinessError as exc:
            prow.addWidget(QLabel(str(exc)))
        prow.addStretch(1)
        products.body.addLayout(prow)
        col.addWidget(products)
        return col

    def _build_right(self) -> QVBoxLayout:
        col = QVBoxLayout()
        col.setSpacing(16)

        card = Card("Pesagem · comida por kg")
        top = QHBoxLayout()
        self.weight_chip = Chip("SEM BALANÇA", "error")
        top.addWidget(self.weight_chip)
        top.addStretch(1)
        card.body.addLayout(top)

        self.weight_label = QLabel("— — —")
        self.weight_label.setObjectName("weightValue")
        self.weight_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.weight_label.setMinimumHeight(96)
        card.body.addWidget(self.weight_label)
        self.weight_msg = QLabel("")
        self.weight_msg.setObjectName("message")
        self.weight_msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.weight_msg.setWordWrap(True)
        card.body.addWidget(self.weight_msg)

        price_row = QHBoxLayout()
        pname = QLabel("Preço/kg")
        pname.setObjectName("fieldLabel")
        self.price_label = QLabel("—")
        self.price_label.setObjectName("priceValue")
        price_row.addWidget(pname)
        price_row.addStretch(1)
        price_row.addWidget(self.price_label)
        card.body.addLayout(price_row)

        from PySide6.QtWidgets import QFrame
        box = QFrame()
        box.setObjectName("inner")
        box_lay = QVBoxLayout(box)
        box_lay.setContentsMargins(16, 12, 16, 12)
        vname = QLabel("VALOR DO PRATO")
        vname.setObjectName("cardTitle")
        vname.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.value_label = QLabel("R$ --,--")
        self.value_label.setObjectName("moneyValue")
        self.value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.value_label.setMinimumHeight(84)
        box_lay.addWidget(vname)
        box_lay.addWidget(self.value_label)
        card.body.addWidget(box)

        tare_row = QHBoxLayout()
        self.tare_btn = _button("")
        self.tare_btn.clicked.connect(self._apply_tare)
        self.tare_label = QLabel("Tara: pela tecla da balança")
        self.tare_label.setObjectName("muted")
        tare_row.addWidget(self.tare_btn)
        tare_row.addWidget(self.tare_label, 1)
        card.body.addLayout(tare_row)

        self.register_btn = _button("REGISTRAR CONSUMO", "primary")
        self.register_btn.clicked.connect(self._register)
        card.body.addWidget(self.register_btn)
        col.addWidget(card)

        self.sim_holder = QVBoxLayout()
        col.addLayout(self.sim_holder)
        col.addStretch(1)
        return col

    def _build_simulator_panel(self) -> QGroupBox:
        return build_simulator_panel(
            self.scale.simulator, lambda text: self._say(text, "info", banner=False))

    # ================================================================= balança
    def _setup_scale(self) -> None:
        self._teardown_scale()
        self.tracker = StabilityTracker(self.settings.scale.stable_reads,
                                        Decimal(self.settings.scale.capacity_kg))
        self.scale = ScaleController(self.settings.scale, self)
        self.scale.reading.connect(self._on_reading)
        self.scale.link_changed.connect(self._on_link)
        self.scale.command_result.connect(self._on_scale_command)
        self.tare_sent_g = None
        self.tare_btn.setText(f"Aplicar tara {format_kg(Decimal(self.settings.scale.default_tare_g) / 1000)}")
        self.tare_label.setText("Tara: pela tecla da balança")
        if self.scale.simulator is not None:
            self._sim_panel = self._build_simulator_panel()
            self.sim_holder.addWidget(self._sim_panel)
        self._set_link_chip(False, "")
        self.scale.start()

    def _teardown_scale(self) -> None:
        if self.scale is not None:
            self.scale.stop()
            self.scale.deleteLater()
            self.scale = None
        if self._sim_panel is not None:
            self.sim_holder.removeWidget(self._sim_panel)
            self._sim_panel.deleteLater()
            self._sim_panel = None
        self.last_reading = None

    def _set_link_chip(self, ok: bool, detail: str) -> None:
        simulated = self.settings.scale.mode == "simulated"
        if ok and detail:
            self.scale_chip.set_state("SEM RESPOSTA DA BALANÇA", "warn")
        elif ok:
            self.scale_chip.set_state("BALANÇA SIMULADA" if simulated else "BALANÇA CONECTADA",
                                      "info" if simulated else "ok")
        else:
            self.scale_chip.set_state("BALANÇA DESCONECTADA", "error")
        self.scale_chip.setToolTip(detail)

    def _on_link(self, ok: bool, detail: str) -> None:
        newly_connected = ok and not self.link_ok
        self.link_ok = ok
        self._set_link_chip(ok, detail)
        if newly_connected and self.settings.scale.send_price_to_scale and self.price is not None:
            self.scale.request_price(self.price)
        self._refresh_actions()

    def _on_reading(self, reading: Optional[ScaleReading]) -> None:
        self.last_reading = reading
        self.state, self.weight = self.tracker.evaluate(reading)
        if self.state in (WeighingState.EMPTY, WeighingState.NEGATIVE):
            self.armed = True          # prato saiu da balança: pode registrar de novo
        self._render_weight()

    def _on_scale_command(self, name: str, ok: bool, message: str) -> None:
        if name == "tare":
            if ok:
                grams = self._pending_tare
                self.tare_sent_g = grams
                self.tare_label.setText(f"Tara enviada: {format_kg(Decimal(grams) / 1000)}")
                self._say("Tara aplicada na balança.", "ok", banner=False)
            else:
                self._say(f"Não foi possível aplicar a tara. {message}", "error", banner=False)
        elif name == "price" and not ok:
            self._say(f"Não foi possível enviar o preço à balança. {message}", "error", banner=False)

    _pending_tare = 0

    def _apply_tare(self) -> None:
        self._pending_tare = self.settings.scale.default_tare_g
        self.scale.request_tare(self._pending_tare)

    # ================================================================= renderização
    def _render_weight(self) -> None:
        text, chip_tone, value_tone = STATE_VIEW[self.state]
        self.weight_chip.set_state(text, chip_tone)
        shown = (format_kg(self.weight) if self.weight is not None and self.state in (
            WeighingState.EMPTY, WeighingState.SETTLING, WeighingState.STABLE) else "— — —")
        self.weight_label.setText(shown)
        set_value_tone(self.weight_label, value_tone if self.state is not WeighingState.EMPTY else "muted")
        self.weight_msg.setText(NO_SCALE_HELP if self.state is WeighingState.NO_SCALE
                                else MESSAGES[self.state])
        if self.state is WeighingState.STABLE and self.price is not None:
            self.value_label.setText(format_brl(calculate_total(self.weight, self.price)))
            set_value_tone(self.value_label, "ok")
        else:
            self.value_label.setText("R$ --,--")
            set_value_tone(self.value_label, "muted")
        self._refresh_actions()

    def _render_command(self) -> None:
        info = self.command
        if info is None:
            self.total_label.setText(format_brl(Decimal("0")))
            self.table.setRowCount(0)
            return
        self.command_chip.set_state(*STATUS_VIEW.get(info.status, (info.status, "muted")))
        self.total_label.setText(format_brl(info.total))
        self.table.setRowCount(len(info.items))
        for row, item in enumerate(info.items):
            qty = format_kg(item.weight_kg) if item.weight_kg is not None else f"{int(item.quantity)} un"
            unit = format_brl(item.unit_price) + ("/kg" if item.type == "WEIGHT" else "")
            cancelled = item.status == "CANCELLED"
            cells = [item.description, qty, unit, format_brl(item.total_price),
                     "Cancelado" if cancelled else "Lançado"]
            for col, text in enumerate(cells):
                cell = QTableWidgetItem(text)
                if col in (1, 2, 3):
                    cell.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                if col == 0:
                    cell.setData(Qt.ItemDataRole.UserRole, item.id)
                if cancelled:
                    font = QFont(cell.font())
                    font.setStrikeOut(True)
                    cell.setFont(font)
                    cell.setForeground(Qt.GlobalColor.gray)
                    if item.cancel_reason:
                        cell.setToolTip(f"Motivo: {item.cancel_reason}")
                self.table.setItem(row, col, cell)
            self.table.setRowHeight(row, 44)
        self.table.scrollToBottom()

    def _refresh_actions(self) -> None:
        open_cmd = self.command is not None and self.command.status == "OPEN"
        self.register_btn.setEnabled(bool(open_cmd and self.state is WeighingState.STABLE
                                          and self.armed and self.price is not None))
        for btn in self.product_buttons:
            btn.setEnabled(open_cmd)
        self.close_btn.setEnabled(bool(open_cmd and self.command.active_items))
        self.cancel_btn.setEnabled(open_cmd and self._selected_item_id() is not None)
        awaiting = self.command is not None and self.command.status == "AWAITING_PAYMENT"
        self.reopen_btn.setEnabled(bool(awaiting and not self.command.payments))
        self.print_btn.setEnabled(bool(self.command and self.command.status in ("OPEN", "AWAITING_PAYMENT")))
        self.tare_btn.setEnabled(self.link_ok)

    def _selected_item_id(self) -> Optional[int]:
        rows = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        if not rows or self.command is None:
            return None
        item = self.table.item(rows[0].row(), 0)
        item_id = item.data(Qt.ItemDataRole.UserRole)
        info = next((i for i in self.command.items if i.id == item_id), None)
        return item_id if info is not None and info.status == "ACTIVE" else None

    def _say(self, text: str, tone: str = "muted", banner: bool = True) -> None:
        """Mensagem ao operador: na barra de status e, por padrão, sob o campo da comanda."""
        if banner:
            self.command_msg.setText(text)
            set_value_tone(self.command_msg, tone)
        self.statusBar().showMessage(text.replace("\n", " "), 8000)

    def _update_operator_label(self) -> None:
        self.operator_label.setText(f"Operador: {self.operator.name}")

    # ================================================================= ações
    def _load_price(self) -> None:
        try:
            self.price = self.services.pricing.current_price(WEIGHED_PRODUCT_CODE)
            self.price_label.setText(format_brl(self.price))
        except PriceNotFound as exc:
            self.price = None
            self.price_label.setText("—")
            self._say(str(exc), "error")

    def _scan(self) -> None:
        raw = self.command_input.text()
        self.command_input.clear()
        if not raw.strip():
            return
        digits = only_digits(raw)
        try:
            if len(digits) == 11:                     # CPF digitado: recupera comanda perdida
                if not is_valid_cpf(digits):
                    raise BusinessError("CPF inválido. Confira os números digitados.")
                found = self.services.commands.open_commands_by_cpf(digits)
                if not found:
                    raise BusinessError(f"Nenhuma comanda em aberto para o CPF {format_cpf(digits)}.")
                self.command = self.services.commands.get(found[0].id)
            else:
                self.command = self.services.commands.find(raw)
        except BusinessError as exc:
            self.command = None
            self.command_chip.set_state("NÃO ENCONTRADA", "error")
            self._say(str(exc), "error")
            self._render_command()
            self._refresh_actions()
            return
        self._after_command_loaded()

    def _after_command_loaded(self) -> None:
        self.tare_sent_g = None
        self.tare_label.setText("Tara: pela tecla da balança")
        self.armed = True
        info = self.command
        if info.status == "OPEN":
            self._say(f"Comanda {info.code} aberta. Total atual: {format_brl(info.total)}", "ok")
        else:
            self._say(f"Comanda: {info.code}\n{NOT_OPEN_MESSAGE.get(info.status, 'Comanda não aceita novos consumos.')}",
                      "warn" if info.status == "AWAITING_PAYMENT" else "error")
        self._render_command()
        self._refresh_actions()

    def _new_command(self) -> None:
        dialog = CpfDialog("CPF do cliente", allow_skip=not self.settings.kiosk.require_cpf, parent=self)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        try:
            self.command = self.services.commands.start_command(self.operator.id, dialog.digits or None)
        except DuplicateOpenCommand as exc:
            self.command = self.services.commands.find(exc.existing_code)
            self._after_command_loaded()
            self._say(f"{exc} Comanda carregada.", "warn")
            return
        except BusinessError as exc:
            self._say(str(exc), "error")
            return
        self._after_command_loaded()
        if self.settings.printing.print_on_start:
            self._print_command()

    def _print_command(self) -> None:
        if not self.command:
            return
        result = self.printer.print_ticket(
            build_ticket(self.command, KIND_COMMAND, self.settings.printing.title))
        detail = result.message or (f"impressa em {result.destination}" if result.ok else "")
        self._say(f"Comanda {self.command.code}: {detail}" if result.ok
                  else f"Falha ao imprimir: {result.message}", "info" if result.ok else "error")

    def _reopen_command(self) -> None:
        if not (self.command and self.command.status == "AWAITING_PAYMENT"):
            return
        try:
            self.command = self.services.commands.reopen_command(self.command.id)
        except BusinessError as exc:
            self._say(str(exc), "error")
            return
        self._say(f"Comanda {self.command.code} reaberta para novos lançamentos.", "info")
        self._render_command()
        self._refresh_actions()

    def _reload_command(self) -> None:
        self.command = self.services.commands.find(self.command.code)
        self._render_command()
        self._refresh_actions()

    def _register(self) -> None:
        if not (self.command and self.state is WeighingState.STABLE and self.weight and self.price):
            return
        weight, price = self.weight, self.price
        total = calculate_total(weight, price)
        dialog = ConfirmConsumptionDialog(self.command.code, weight, price, total, self)
        if dialog.exec() != dialog.DialogCode.Accepted:
            self._say("Registro cancelado pelo operador.", "muted")
            self.command_input.setFocus()
            return
        raw = self.last_reading.raw_hex if self.last_reading else None
        try:
            item = self.services.commands.add_weighed_consumption(
                self.command.id, self.operator.id, weight, self.tare_sent_g, raw)
        except BusinessError as exc:
            self._say(str(exc), "error")
            QMessageBox.warning(self, "Não foi possível registrar", str(exc))
            self._reload_command_safely()
            return
        self.armed = False
        self._say(f"Consumo registrado. Comanda: {self.command.code}. Valor: {format_brl(item.total_price)}.",
                  "ok")
        self._reload_command()
        self.command_input.setFocus()

    def _reload_command_safely(self) -> None:
        try:
            self._reload_command()
        except BusinessError:
            pass

    def _add_unit(self, product_code: str) -> None:
        if not (self.command and self.command.status == "OPEN"):
            return
        try:
            item = self.services.commands.add_unit_product(self.command.id, self.operator.id, product_code)
        except BusinessError as exc:
            self._say(str(exc), "error")
            self._reload_command_safely()
            return
        self._say(f"{item.description} lançado: {format_brl(item.total_price)}.", "ok")
        self._reload_command()
        self.command_input.setFocus()

    def _cancel_item(self) -> None:
        item_id = self._selected_item_id()
        if item_id is None:
            return
        item = next(i for i in self.command.items if i.id == item_id)
        dialog = CancelConsumptionDialog(item.description, item.total_price, self)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        try:
            self.services.commands.cancel_consumption(item_id, self.operator.id, dialog.reason_text)
        except BusinessError as exc:
            self._say(str(exc), "error")
        else:
            self._say(f"Lançamento cancelado: {item.description}.", "info")
        self._reload_command_safely()
        self.command_input.setFocus()

    def _close_command(self) -> None:
        if not (self.command and self.command.status == "OPEN"):
            return
        answer = QMessageBox.question(
            self, "Enviar para pagamento",
            f"Enviar a comanda {self.command.code} para pagamento?\nTotal: {format_brl(self.command.total)}\n\n"
            "Depois de enviada não recebe novos lançamentos (dá para reabrir enquanto não houver pagamento).")
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self.command = self.services.commands.send_to_payment(self.command.id)
        except BusinessError as exc:
            self._say(str(exc), "error")
            return
        self._say(f"Comanda {self.command.code} enviada ao caixa. Total: {format_brl(self.command.total)}.", "info")
        self._render_command()
        self._refresh_actions()
        self.command_input.setFocus()

    def _change_price(self) -> None:
        if self.price is None:
            return
        dialog = ChangePriceDialog(self.price, self)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        admin = self.services.auth.authenticate_admin(dialog.manager_pin)
        if admin is None:
            QMessageBox.warning(self, "Não autorizado", "PIN de gerente inválido. O preço não foi alterado.")
            return
        try:
            self.services.pricing.set_price(WEIGHED_PRODUCT_CODE, dialog.new_price, admin.id)
        except BusinessError as exc:
            QMessageBox.warning(self, "Preço inválido", str(exc))
            return
        self._load_price()
        if self.settings.scale.send_price_to_scale and self.price is not None:
            self.scale.request_price(self.price)
        self._render_weight()
        self._say(f"Preço/kg alterado para {format_brl(self.price)} (autorizado por {admin.name}).", "info")

    def _switch_operator(self) -> None:
        dialog = LoginDialog(self.services.auth.list_operators(), self.services.auth.authenticate, self)
        if dialog.exec() == dialog.DialogCode.Accepted and dialog.operator:
            self.operator = dialog.operator
            self._update_operator_label()
            self._say(f"Operador: {self.operator.name}", "muted")
        self.command_input.setFocus()

    def _open_scale_settings(self) -> None:
        self.scale.stop()                       # libera a porta para o teste de conexão
        dialog = ScaleSettingsDialog(self.settings.scale, self)
        if dialog.exec() == dialog.DialogCode.Accepted:
            self.settings.scale = dialog.values()
            save_settings(self.settings)
            self._say("Configuração da balança salva.", "info")
        self._setup_scale()
        self.state, self.weight = WeighingState.NO_SCALE, None
        self._render_weight()
        self.command_input.setFocus()

    def closeEvent(self, event) -> None:
        self._teardown_scale()
        super().closeEvent(event)

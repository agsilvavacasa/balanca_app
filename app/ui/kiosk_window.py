"""Autoatendimento: o cliente abre a comanda (com CPF), se serve, pesa o prato e indica o
que mais pegou. O pagamento acontece na saída (caixa ou autopagamento)."""
from decimal import Decimal
from typing import Optional

from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (QApplication, QFrame, QGridLayout, QHBoxLayout, QInputDialog, QLabel,
                               QLineEdit, QMainWindow, QStackedWidget, QVBoxLayout, QWidget)

from ..bootstrap import Services
from ..config.settings import AppSettings
from ..domain.cpf import format_cpf, is_valid_cpf, only_digits
from ..domain.money import calculate_total, format_brl, format_kg
from ..printing.printer import PrintResult, TicketPrinter
from ..printing.ticket import KIND_COMMAND, build_ticket
from ..services.command_service import WEIGHED_PRODUCT_CODE
from ..services.dto import CommandInfo, ProductInfo
from ..services.errors import BusinessError, DuplicateOpenCommand, InvalidCpf, PriceNotFound
from ..services.weighing_service import StabilityTracker, WeighingState
from .common import ItemsTable, NOT_OPEN_MESSAGE
from .dialogs import _button
from .keypad import CpfInput
from .simulator_panel import build_simulator_panel
from .theme import repolish
from .widgets import Chip, set_value_tone
from .workers import ScaleController

(WELCOME, CPF, NEWDONE, PICK, WEIGH, EXTRAS, REVIEW, ENDDONE) = range(8)

# mensagens para o cliente (linguagem simples)
WEIGH_TEXT = {
    WeighingState.NO_SCALE: ("BALANÇA INDISPONÍVEL", "error", "Balança indisponível. Chame um atendente."),
    WeighingState.EMPTY: ("PRATO VAZIO", "muted", "Coloque o prato na balança."),
    WeighingState.SETTLING: ("MEDINDO…", "warn", "Aguarde, estamos medindo o peso…"),
    WeighingState.STABLE: ("PESO OK", "ok", "Tudo certo! Toque em REGISTRAR PRATO."),
    WeighingState.NEGATIVE: ("PESO INVÁLIDO", "error", "Confira se o prato está corretamente sobre a balança."),
    WeighingState.OVERLOAD: ("PESO ACIMA DO LIMITE", "error", "Peso acima do limite da balança. Retire o excesso."),
}


class KioskWindow(QMainWindow):
    def __init__(self, settings: AppSettings, services: Services):
        super().__init__()
        self.settings = settings
        self.services = services
        self.op = services.auth.self_service_operator()
        self.printer = TicketPrinter(settings.printing)

        self.command: Optional[CommandInfo] = None
        self.purpose = "new"                       # "new" | "lost" (fluxo do CPF)
        self.staged: dict[str, int] = {}
        self.products: list[ProductInfo] = []
        self.price: Optional[Decimal] = None

        self.tracker = StabilityTracker(settings.scale.stable_reads, Decimal(settings.scale.capacity_kg))
        self.state = WeighingState.NO_SCALE
        self.weight: Optional[Decimal] = None
        self.last_reading = None
        self.tare_sent_g: Optional[int] = None
        self.armed = True
        self.link_ok = False
        self.scale: Optional[ScaleController] = None
        self._sim_window = None
        self._countdown = 0
        self._pending_tare = 0

        self.setWindowTitle("Autoatendimento")
        self.resize(1280, 860)
        self.setMinimumSize(1000, 720)
        self.stack = QStackedWidget()
        root = QWidget()
        root.setObjectName("root")
        lay = QVBoxLayout(root)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.stack)
        self.setCentralWidget(root)
        for build in (self._build_welcome, self._build_cpf, self._build_newdone, self._build_pick,
                      self._build_weigh, self._build_extras, self._build_review, self._build_enddone):
            self.stack.addWidget(build())

        self.done_timer = QTimer(self, singleShot=True)
        self.done_timer.timeout.connect(self._finish_session)
        self.idle_timer = QTimer(self, singleShot=True)
        self.idle_timer.timeout.connect(self._on_idle)
        self.count_timer = QTimer(self)
        self.count_timer.setInterval(1000)
        self.count_timer.timeout.connect(self._tick_auto_register)
        QApplication.instance().installEventFilter(self)
        QShortcut(QKeySequence("Ctrl+Shift+Q"), self, activated=self._admin_exit)

        self._load_catalog()
        self._setup_scale()
        self._go(WELCOME)

    # ================================================================= construção
    def _page(self) -> tuple[QWidget, QVBoxLayout]:
        page = QWidget()
        page.setObjectName("root")
        lay = QVBoxLayout(page)
        lay.setContentsMargins(70, 40, 70, 40)
        lay.setSpacing(18)
        return page, lay

    @staticmethod
    def _label(text: str = "", name: str = "", align=Qt.AlignmentFlag.AlignCenter, wrap=True) -> QLabel:
        label = QLabel(text)
        if name:
            label.setObjectName(name)
        label.setAlignment(align)
        label.setWordWrap(wrap)
        return label

    def _build_welcome(self) -> QWidget:
        page, lay = self._page()
        lay.addStretch(2)
        lay.addWidget(self._label("Bem-vindo!", "hero"))
        lay.addWidget(self._label("Abra sua comanda ou aproxime a sua do leitor", "heroSub"))
        lay.addSpacing(20)
        row = QHBoxLayout()
        row.setSpacing(24)
        self.new_btn = _button("NOVA COMANDA", "kioskPrimary")
        self.lost_btn = _button("PERDI MINHA COMANDA", "kiosk")
        self.new_btn.clicked.connect(lambda: self._open_cpf("new"))
        self.lost_btn.clicked.connect(lambda: self._open_cpf("lost"))
        row.addStretch(1)
        row.addWidget(self.new_btn, 3)
        row.addWidget(self.lost_btn, 3)
        row.addStretch(1)
        lay.addLayout(row)
        lay.addWidget(self._label("Já tem comanda? Aproxime-a do leitor", "stepHint"))
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
        self.welcome_price = self._label("", "stepHint")
        lay.addWidget(self.welcome_price)
        lay.addStretch(3)
        return page

    def _build_cpf(self) -> QWidget:
        page, lay = self._page()
        self.cpf_title = self._label("", "stepTitle")
        self.cpf_hint = self._label("", "stepHint")
        lay.addWidget(self.cpf_title)
        lay.addWidget(self.cpf_hint)
        self.cpf = CpfInput()
        self.cpf.changed.connect(self._cpf_changed)
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
        self.skip_btn = _button("SEGUIR SEM CPF", "kiosk")
        self.skip_btn.clicked.connect(lambda: self._create_command(None))
        self.cpf_ok = _button("CONFIRMAR", "kioskPrimary")
        self.cpf_ok.clicked.connect(self._cpf_confirm)
        row.addWidget(back)
        row.addStretch(1)
        row.addWidget(self.skip_btn)
        row.addWidget(self.cpf_ok)
        lay.addLayout(row)
        return page

    def _build_newdone(self) -> QWidget:
        page, lay = self._page()
        lay.addStretch(1)
        lay.addWidget(self._label("Comanda criada!", "hero"))
        self.new_code = self._label("", "bigCode")
        lay.addWidget(self.new_code)
        lay.addWidget(self._label("Retire sua comanda impressa e guarde-a. Agora é só se servir!", "heroSub"))
        self.new_print_msg = self._label("", "bigMessage")
        lay.addWidget(self.new_print_msg)
        lay.addSpacing(10)
        ok = _button("OK", "kioskPrimary")
        ok.clicked.connect(self._finish_session)
        holder = QHBoxLayout()
        holder.addStretch(1)
        holder.addWidget(ok, 2)
        holder.addStretch(1)
        lay.addLayout(holder)
        lay.addStretch(2)
        return page

    def _build_pick(self) -> QWidget:
        page, lay = self._page()
        lay.addWidget(self._label("Encontramos sua comanda", "stepTitle"))
        self.pick_msg = self._label("", "stepHint")
        lay.addWidget(self.pick_msg)
        self.pick_rows = QVBoxLayout()
        self.pick_rows.setSpacing(14)
        lay.addLayout(self.pick_rows)
        lay.addStretch(1)
        back = _button("← VOLTAR", "kiosk")
        back.clicked.connect(lambda: self._go(WELCOME))
        lay.addWidget(back, 0, Qt.AlignmentFlag.AlignLeft)
        return page

    def _build_weigh(self) -> QWidget:
        page, lay = self._page()
        top = QHBoxLayout()
        self.weigh_code = Chip("COMANDA", "info")
        exit_btn = _button("Sair", "kiosk")
        exit_btn.clicked.connect(self._finish_session)
        top.addWidget(self.weigh_code)
        top.addStretch(1)
        top.addWidget(exit_btn)
        lay.addLayout(top)
        lay.addWidget(self._label("1 · Pese seu prato", "stepTitle"))
        self.weight_chip = Chip("PRATO VAZIO", "muted")
        chip_row = QHBoxLayout()
        chip_row.addStretch(1)
        chip_row.addWidget(self.weight_chip)
        chip_row.addStretch(1)
        lay.addLayout(chip_row)
        self.weight_label = self._label("— — —", "weightValue")
        self.weight_label.setMinimumHeight(96)
        lay.addWidget(self.weight_label)
        self.weigh_msg = self._label("", "bigMessage")
        lay.addWidget(self.weigh_msg)

        box = QFrame()
        box.setObjectName("inner")
        blay = QVBoxLayout(box)
        self.price_label = self._label("", "stepHint")
        self.value_label = self._label("R$ --,--", "moneyValue")
        self.value_label.setMinimumHeight(84)
        blay.addWidget(self.price_label)
        blay.addWidget(self.value_label)
        lay.addWidget(box)
        self.consumed_label = self._label("", "stepHint")
        lay.addWidget(self.consumed_label)

        row = QHBoxLayout()
        self.skip_plate_btn = _button("Bebidas e sobremesas →", "kiosk")
        self.skip_plate_btn.clicked.connect(lambda: self._go(EXTRAS))
        self.register_btn = _button("REGISTRAR PRATO", "kioskPrimary")
        self.register_btn.clicked.connect(self._register_plate)
        row.addWidget(self.skip_plate_btn)
        row.addWidget(self.register_btn, 1)
        lay.addLayout(row)
        lay.addStretch(1)
        return page

    def _build_extras(self) -> QWidget:
        page, lay = self._page()
        lay.addWidget(self._label("2 · Pegou bebidas ou sobremesas?", "stepTitle"))
        self.extras_banner = self._label("", "stepHint")
        lay.addWidget(self.extras_banner)
        self.tiles_grid = QGridLayout()
        self.tiles_grid.setSpacing(16)
        lay.addLayout(self.tiles_grid)
        lay.addStretch(1)
        row = QHBoxLayout()
        back = _button("← Pesar outro prato", "kiosk")
        back.clicked.connect(self._enter_weigh)
        self.extras_ok = _button("CONTINUAR", "kioskPrimary")
        self.extras_ok.clicked.connect(self._commit_extras)
        row.addWidget(back)
        row.addStretch(1)
        row.addWidget(self.extras_ok)
        lay.addLayout(row)
        return page

    def _build_review(self) -> QWidget:
        page, lay = self._page()
        lay.addWidget(self._label("3 · Confira seu consumo", "stepTitle"))
        self.review_table = ItemsTable(row_height=54, font_px=20)
        lay.addWidget(self.review_table, 1)
        total_row = QHBoxLayout()
        total_row.addWidget(self._label("Total até agora", "stepHint", Qt.AlignmentFlag.AlignLeft))
        self.review_total = self._label("", "moneyValue", Qt.AlignmentFlag.AlignRight)
        total_row.addWidget(self.review_total)
        lay.addLayout(total_row)
        lay.addWidget(self._label("O pagamento é feito no caixa, quando você sair do restaurante.", "stepHint"))
        row = QHBoxLayout()
        back = _button("← Adicionar mais", "kiosk")
        back.clicked.connect(lambda: self._go(EXTRAS))
        self.review_done = _button("CONCLUIR", "kioskPrimary")
        self.review_done.clicked.connect(lambda: self._go(ENDDONE))
        row.addWidget(back)
        row.addStretch(1)
        row.addWidget(self.review_done)
        lay.addLayout(row)
        return page

    def _build_enddone(self) -> QWidget:
        page, lay = self._page()
        lay.addStretch(1)
        lay.addWidget(self._label("Tudo certo!", "hero"))
        self.end_code = self._label("", "bigCode")
        lay.addWidget(self.end_code)
        self.end_total = self._label("", "moneyValue")
        lay.addWidget(self.end_total)
        lay.addWidget(self._label("Ao sair do restaurante, apresente sua comanda no caixa. "
                                  "Se a perder, basta informar seu CPF.", "heroSub"))
        ok = _button("OK", "kioskPrimary")
        ok.clicked.connect(self._finish_session)
        holder = QHBoxLayout()
        holder.addStretch(1)
        holder.addWidget(ok, 2)
        holder.addStretch(1)
        lay.addLayout(holder)
        lay.addStretch(2)
        return page

    # ================================================================= dados e balança
    def _load_catalog(self) -> None:
        try:
            self.price = self.services.pricing.current_price(WEIGHED_PRODUCT_CODE)
            self.welcome_price.setText(f"Comida por quilo: {format_brl(self.price)}/kg")
            self.price_label.setText(f"Preço por quilo: {format_brl(self.price)}")
        except PriceNotFound as exc:
            self.price = None
            self.welcome_msg.setText(str(exc))
        try:
            self.products = self.services.commands.unit_products()
        except BusinessError:
            self.products = []
        self._build_tiles()

    def _build_tiles(self) -> None:
        while self.tiles_grid.count():
            item = self.tiles_grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.tiles: dict[str, tuple[QFrame, QLabel]] = {}
        for index, product in enumerate(self.products):
            tile = QFrame()
            tile.setObjectName("tile")
            tile.setProperty("active", False)
            tlay = QVBoxLayout(tile)
            tlay.setContentsMargins(20, 16, 20, 16)
            tlay.addWidget(self._label(product.description, "tileName"))
            tlay.addWidget(self._label(format_brl(product.price), "tilePrice"))
            ctl = QHBoxLayout()
            minus = _button("−", "round")
            plus = _button("+", "round")
            qty = self._label("0", "tileQty")
            minus.clicked.connect(lambda _=False, c=product.code: self._bump(c, -1))
            plus.clicked.connect(lambda _=False, c=product.code: self._bump(c, +1))
            ctl.addStretch(1)
            ctl.addWidget(minus)
            ctl.addWidget(qty)
            ctl.addWidget(plus)
            ctl.addStretch(1)
            tlay.addLayout(ctl)
            self.tiles[product.code] = (tile, qty)
            self.tiles_grid.addWidget(tile, index // 3, index % 3)

    def _setup_scale(self) -> None:
        self.scale = ScaleController(self.settings.scale, self)
        self.scale.reading.connect(self._on_reading)
        self.scale.link_changed.connect(self._on_link)
        self.scale.command_result.connect(self._on_scale_command)
        if self.scale.simulator is not None:
            # só existe em modo de teste: janela à parte, para não ocupar a tela do cliente
            self._sim_window = QWidget(self, Qt.WindowType.Tool)
            self._sim_window.setWindowTitle("Simulador da balança")
            box = QVBoxLayout(self._sim_window)
            box.addWidget(build_simulator_panel(self.scale.simulator, lambda text: None))
            self._sim_window.resize(560, 300)
            self._sim_window.show()
        self.scale.start()

    def _on_link(self, ok: bool, detail: str) -> None:
        newly = ok and not self.link_ok
        self.link_ok = ok
        if newly and self.settings.scale.send_price_to_scale and self.price is not None:
            self.scale.request_price(self.price)
        if newly and self.stack.currentIndex() == WEIGH:
            self._auto_tare()

    def _on_reading(self, reading) -> None:
        self.last_reading = reading
        self.state, self.weight = self.tracker.evaluate(reading)
        if self.state in (WeighingState.EMPTY, WeighingState.NEGATIVE):
            self.armed = True
        if self.stack.currentIndex() == WEIGH:
            self._render_weigh()

    def _on_scale_command(self, name: str, ok: bool, message: str) -> None:
        if name == "tare" and ok:
            self.tare_sent_g = self._pending_tare

    def _auto_tare(self) -> None:
        if self.settings.kiosk.auto_tare and self.link_ok:
            self._pending_tare = self.settings.scale.default_tare_g
            self.scale.request_tare(self._pending_tare)

    # ================================================================= navegação
    def _go(self, page: int) -> None:
        self.stack.setCurrentIndex(page)
        self.done_timer.stop()
        self._cancel_countdown()
        if page == WELCOME:
            self.idle_timer.stop()
            self.scan_input.clear()
            self.scan_input.setFocus()
        else:
            self._touch()
        if page == CPF:
            self.cpf.clear()
            self.cpf.setFocus()
        elif page == WEIGH:
            self._render_weigh()
        elif page == EXTRAS:
            self._render_extras()
        elif page == REVIEW:
            self._render_review()
        elif page == ENDDONE:
            self.end_code.setText(self.command.code if self.command else "")
            self.end_total.setText(format_brl(self.command.total) if self.command else "")
            self.done_timer.start(self.settings.kiosk.done_screen_s * 1000)
        elif page == NEWDONE:
            self.done_timer.start(self.settings.kiosk.done_screen_s * 1000)

    def _finish_session(self) -> None:
        self.command = None
        self.staged.clear()
        self.welcome_msg.setText("")
        self._go(WELCOME)

    def _touch(self) -> None:
        seconds = self.settings.kiosk.idle_timeout_s
        if seconds > 0 and self.stack.currentIndex() != WELCOME:
            self.idle_timer.start(seconds * 1000)

    def _on_idle(self) -> None:
        if self.stack.currentIndex() != WELCOME:
            self._finish_session()

    def eventFilter(self, obj, event) -> bool:
        if event.type() in (QEvent.Type.MouseButtonPress, QEvent.Type.KeyPress):
            self._touch()
        return super().eventFilter(obj, event)

    def _admin_exit(self) -> None:
        pin, ok = QInputDialog.getText(self, "Sair do autoatendimento", "PIN do gerente:",
                                       QLineEdit.EchoMode.Password)
        if ok and self.services.auth.authenticate_admin(pin):
            self.close()

    # ================================================================= abrir / recuperar comanda
    def _open_cpf(self, purpose: str) -> None:
        self.purpose = purpose
        new = purpose == "new"
        self.cpf_title.setText("Informe seu CPF" if new else "Informe o CPF da comanda perdida")
        self.cpf_hint.setText("Ele identifica sua comanda caso você a perca." if new
                              else "Vamos localizar sua comanda em aberto.")
        self.cpf_msg.setText("")
        self.skip_btn.setVisible(new and not self.settings.kiosk.require_cpf)
        self._cpf_changed()
        self._go(CPF)

    def _cpf_changed(self) -> None:
        self.cpf_ok.setEnabled(self.cpf.is_valid)
        self.cpf_msg.setText("")

    def _cpf_confirm(self) -> None:
        if not self.cpf.is_valid:
            return
        digits = self.cpf.digits
        if self.purpose == "new":
            self._create_command(digits)
        else:
            self._lookup_cpf(digits)

    def _create_command(self, cpf: Optional[str]) -> None:
        try:
            info = self.services.commands.start_command(self.op.id, cpf)
        except DuplicateOpenCommand as exc:
            self._lookup_cpf(cpf, note=f"{exc} Você pode continuar com ela.")
            return
        except InvalidCpf as exc:
            self.cpf_msg.setText(str(exc))
            return
        except BusinessError as exc:
            self.cpf_msg.setText(str(exc))
            return
        self.command = info
        self.new_code.setText(info.code)
        self.new_print_msg.setText("")
        if self.settings.printing.print_on_start:
            result = self._print(info)
            if not result.ok:
                self.new_print_msg.setText(
                    f"Não foi possível imprimir. Anote o número {info.code} ou informe seu CPF no caixa.")
        self._go(NEWDONE)

    def _lookup_cpf(self, cpf: str, note: str = "", error=None) -> None:
        error = error or self.cpf_msg.setText
        try:
            found = self.services.commands.open_commands_by_cpf(cpf)
        except BusinessError as exc:
            error(str(exc))
            return
        if not found:
            error(f"Nenhuma comanda em aberto para o CPF {format_cpf(cpf)}.")
            return
        self.pick_msg.setText(note)
        while self.pick_rows.count():
            item = self.pick_rows.takeAt(0)
            if item.layout():
                while item.layout().count():
                    child = item.layout().takeAt(0)
                    if child.widget():
                        child.widget().deleteLater()
            if item.widget():
                item.widget().deleteLater()
        for summary in found:
            row = QHBoxLayout()
            opened = summary.opened_at.strftime("%H:%M") if summary.opened_at else "--:--"
            row.addWidget(self._label(f"Comanda {summary.code} · {format_brl(summary.total)} · aberta às {opened}",
                                      "bigMessage", Qt.AlignmentFlag.AlignLeft), 1)
            reprint = _button("REIMPRIMIR", "kiosk")
            proceed = _button("CONTINUAR", "kioskPrimary")
            reprint.clicked.connect(lambda _=False, i=summary.id: self._reprint(i))
            proceed.clicked.connect(lambda _=False, i=summary.id: self._continue_with(i))
            proceed.setEnabled(summary.status == "OPEN")
            row.addWidget(reprint)
            row.addWidget(proceed)
            self.pick_rows.addLayout(row)
        self._go(PICK)

    def _reprint(self, command_id: int) -> None:
        info = self.services.commands.get(command_id)
        result = self._print(info)
        self.pick_msg.setText("Comanda impressa. Retire no leitor." if result.ok
                              else "Não foi possível imprimir. Chame um atendente.")

    def _continue_with(self, command_id: int) -> None:
        self._open_command(self.services.commands.get(command_id))

    def _print(self, info: CommandInfo) -> PrintResult:
        try:
            return self.printer.print_ticket(build_ticket(info, KIND_COMMAND, self.settings.printing.title))
        except Exception as exc:                      # impressora desligada, driver com erro etc.
            return PrintResult(False, "", str(exc))

    def _scan(self) -> None:
        raw = self.scan_input.text()
        self.scan_input.clear()
        if not raw.strip():
            return
        digits = only_digits(raw)
        try:
            if len(digits) == 11 and is_valid_cpf(digits):
                self._lookup_cpf_from_welcome(digits)
                return
            self._open_command(self.services.commands.find(raw))
        except BusinessError:
            self._welcome_error("Comanda não encontrada. Tente novamente ou chame um atendente.")

    def _lookup_cpf_from_welcome(self, cpf: str) -> None:
        self.purpose = "lost"
        self.cpf.clear()
        self._lookup_cpf(cpf, error=self._welcome_error)

    def _welcome_error(self, text: str) -> None:
        self.welcome_msg.setText(text)
        set_value_tone(self.welcome_msg, "error")
        self.scan_input.setFocus()

    def _open_command(self, info: CommandInfo) -> None:
        if info.status != "OPEN":
            self._go(WELCOME)
            self._welcome_error(NOT_OPEN_MESSAGE.get(info.status, "Esta comanda não está disponível.")
                                + " Procure o caixa ou um atendente.")
            return
        self.command = info
        self._enter_weigh()

    # ================================================================= pesagem
    def _enter_weigh(self) -> None:
        self.armed = True
        self.tare_sent_g = None
        self._auto_tare()
        self._go(WEIGH)

    def _render_weigh(self) -> None:
        if self.command is None:
            return
        self.weigh_code.setText(f"COMANDA {self.command.code}")
        chip_text, tone, message = WEIGH_TEXT[self.state]
        self.weight_chip.set_state(chip_text, tone)
        self.weigh_msg.setText(message)
        shown = (format_kg(self.weight) if self.weight is not None and self.state in (
            WeighingState.EMPTY, WeighingState.SETTLING, WeighingState.STABLE) else "— — —")
        self.weight_label.setText(shown)
        set_value_tone(self.weight_label, "muted" if self.state is WeighingState.EMPTY else tone)
        stable = self.state is WeighingState.STABLE and self.price is not None
        if stable:
            self.value_label.setText(format_brl(calculate_total(self.weight, self.price)))
            set_value_tone(self.value_label, "ok")
        else:
            self.value_label.setText("R$ --,--")
            set_value_tone(self.value_label, "muted")
        self.consumed_label.setText(f"Seu consumo até agora: {format_brl(self.command.total)}")
        can_register = bool(stable and self.armed)
        self.register_btn.setEnabled(can_register)
        if not self.armed and self.state is WeighingState.STABLE:
            self.weigh_msg.setText("Prato registrado. Retire o prato da balança.")
        self._update_countdown(can_register)

    def _update_countdown(self, can_register: bool) -> None:
        seconds = self.settings.kiosk.auto_register_after_s
        if seconds > 0 and can_register:
            if not self.count_timer.isActive():
                self._countdown = seconds
                self.count_timer.start()
                self.register_btn.setText(f"REGISTRANDO EM {self._countdown}…")
        else:
            self._cancel_countdown()

    def _cancel_countdown(self) -> None:
        self.count_timer.stop()
        self.register_btn.setText("REGISTRAR PRATO")

    def _tick_auto_register(self) -> None:
        self._countdown -= 1
        if self._countdown <= 0:
            self.count_timer.stop()
            self._register_plate()
        else:
            self.register_btn.setText(f"REGISTRANDO EM {self._countdown}…")

    def _register_plate(self) -> None:
        self._cancel_countdown()
        if not (self.command and self.state is WeighingState.STABLE and self.weight and self.armed):
            return
        weight = self.weight
        raw = self.last_reading.raw_hex if self.last_reading else None
        try:
            item = self.services.commands.add_weighed_consumption(
                self.command.id, self.op.id, weight, self.tare_sent_g, raw)
            self.command = self.services.commands.get(self.command.id)
        except BusinessError as exc:
            self.weigh_msg.setText(str(exc).replace("\n", " "))
            return
        self.armed = False
        self.extras_banner.setText(
            f"Prato registrado: {format_kg(item.weight_kg)} · {format_brl(item.total_price)}")
        self._go(EXTRAS)

    # ================================================================= bebidas e sobremesas
    def _bump(self, code: str, delta: int) -> None:
        self.staged[code] = max(0, min(20, self.staged.get(code, 0) + delta))
        self._render_extras()
        self._touch()

    def _render_extras(self) -> None:
        for code, (tile, qty) in self.tiles.items():
            amount = self.staged.get(code, 0)
            qty.setText(str(amount))
            tile.setProperty("active", amount > 0)
            repolish(tile)
        picked = sum(self.staged.values())
        self.extras_ok.setText("CONTINUAR" if picked == 0 else f"ADICIONAR {picked} E CONTINUAR")

    def _commit_extras(self) -> None:
        try:
            for code, amount in self.staged.items():
                if amount > 0:
                    self.services.commands.add_unit_product(self.command.id, self.op.id, code, amount)
            self.command = self.services.commands.get(self.command.id)
        except BusinessError as exc:
            self.extras_banner.setText(str(exc).replace("\n", " "))
            return
        self.staged.clear()
        self._go(REVIEW)

    def _render_review(self) -> None:
        self.command = self.services.commands.get(self.command.id)
        self.review_table.set_items(self.command.items)
        self.review_total.setText(format_brl(self.command.total))

    # ================================================================= encerramento
    def closeEvent(self, event) -> None:
        QApplication.instance().removeEventFilter(self)
        if self.scale is not None:
            self.scale.stop()
            self.scale = None
        super().closeEvent(event)

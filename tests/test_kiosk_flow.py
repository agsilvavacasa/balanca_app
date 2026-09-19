"""Fluxo do cliente no autoatendimento, sobre a balança simulada (Qt offscreen)."""
import os
from decimal import Decimal

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from app.bootstrap import build_services
from app.config.settings import AppSettings
from app.services.weighing_service import WeighingState
from app.ui import kiosk_window as kw
from app.ui.theme import apply_theme

CPF = "529.982.247-25"


def wait_until(condition, ms=3000):
    waited = 0
    while not condition() and waited < ms:
        QTest.qWait(10)
        waited += 10
    return condition()


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    apply_theme(app)
    return app


@pytest.fixture
def kiosk(qapp, tmp_path, monkeypatch):
    monkeypatch.setenv("BALANCA_HOME", str(tmp_path))
    settings = AppSettings(database_url=f"sqlite:///{tmp_path / 'k.db'}")
    settings.scale.poll_ms = 30
    settings.printing.pdf_dir = str(tmp_path / "tickets")
    settings.kiosk.done_screen_s = 1
    services = build_services(settings)
    win = kw.KioskWindow(settings, services)
    win.show()
    assert wait_until(lambda: win.link_ok)
    yield win
    win.close()
    services.db.dispose()


def type_cpf(win, cpf):
    for ch in cpf:
        if ch.isdigit():
            win.cpf.keys[ch].click()


def tickets(win):
    folder = win.settings.printing.pdf_dir
    return sorted(os.listdir(folder)) if os.path.isdir(folder) else []


def test_new_command_with_cpf_prints_ticket(kiosk):
    assert kiosk.stack.currentIndex() == kw.WELCOME
    kiosk.new_btn.click()
    assert kiosk.stack.currentIndex() == kw.CPF and not kiosk.cpf_ok.isEnabled()
    assert not kiosk.skip_btn.isVisible() or not kiosk.skip_btn.isEnabled() or kiosk.settings.kiosk.require_cpf
    type_cpf(kiosk, "11111111111")                          # inválido
    assert not kiosk.cpf_ok.isEnabled() and "inválido" in kiosk.cpf.hint.text().lower()
    kiosk.cpf.clear()
    type_cpf(kiosk, CPF)
    assert kiosk.cpf.display.text() == "529.982.247-25" and kiosk.cpf_ok.isEnabled()
    kiosk.cpf_ok.click()
    assert kiosk.stack.currentIndex() == kw.WEIGH               # vai direto para a pesagem
    assert kiosk.command.code == "000157"
    assert "000157 criada" in kiosk.weigh_notice.text() and "Retire" in kiosk.weigh_notice.text()
    assert len(tickets(kiosk)) == 1 and tickets(kiosk)[0].startswith("comanda_000157")
    info = kiosk.services.commands.find("000157")
    assert info.customer_cpf == "52998224725" and info.status == "OPEN"


def test_new_command_requires_cpf_by_default(kiosk):
    kiosk.new_btn.click()
    assert kiosk.skip_btn.isHidden()
    kiosk.settings.kiosk.require_cpf = False
    kiosk.new_btn.click()
    assert not kiosk.skip_btn.isHidden()


def test_full_customer_journey(kiosk):
    services = kiosk.services
    kiosk.new_btn.click()
    type_cpf(kiosk, CPF)
    kiosk.cpf_ok.click()
    code = kiosk.command.code
    assert kiosk.stack.currentIndex() == kw.WEIGH               # sem precisar ler a comanda de novo

    sim = kiosk.scale.simulator
    sim.place_weight(860)                                  # prato + comida; tara automática de 360 g
    assert wait_until(lambda: kiosk.tare_sent_g == 360)
    assert wait_until(lambda: kiosk.state is WeighingState.STABLE)
    assert kiosk.weight_label.text() == "0,500 kg" and kiosk.value_label.text() == "R$ 39,95"
    assert kiosk.register_btn.isEnabled()
    kiosk.register_btn.click()
    assert kiosk.stack.currentIndex() == kw.EXTRAS
    assert "0,500 kg" in kiosk.extras_banner.text()
    assert not kiosk.armed

    kiosk._bump("002", +1)                                 # 1 refrigerante
    kiosk._bump("004", +1)                                 # 1 sobremesa
    kiosk._bump("004", +1)                                 # 2 sobremesas
    kiosk._bump("003", +1)
    kiosk._bump("003", -1)                                 # água volta a 0
    assert kiosk.extras_ok.text() == "ADICIONAR 3 E CONTINUAR"
    kiosk.extras_ok.click()
    assert kiosk.stack.currentIndex() == kw.REVIEW
    assert kiosk.review_total.text() == "R$ 71,95"         # 39,95 + 8,00 + 2 x 12,00
    assert kiosk.review_table.rowCount() == 3

    kiosk.review_done.click()
    assert kiosk.stack.currentIndex() == kw.ENDDONE and kiosk.end_code.text() == code
    info = services.commands.find(code)
    assert info.status == "OPEN"                           # ainda não paga: paga na saída
    assert info.total == Decimal("71.95")
    assert {i.operator_name for i in info.items} == {"Autoatendimento"}
    assert wait_until(lambda: kiosk.stack.currentIndex() == kw.WELCOME, 4000)   # volta sozinho


def test_lost_command_found_by_cpf_and_reprint(kiosk):
    services = kiosk.services
    created = services.commands.start_command(kiosk.op.id, CPF)
    kiosk.lost_btn.click()
    type_cpf(kiosk, CPF)
    kiosk.cpf_ok.click()
    assert kiosk.stack.currentIndex() == kw.PICK
    kiosk._reprint(created.id)
    assert "impressa" in kiosk.pick_msg.text() and len(tickets(kiosk)) == 1
    kiosk._continue_with(created.id)
    assert kiosk.stack.currentIndex() == kw.WEIGH and kiosk.command.code == created.code


def test_lost_command_unknown_cpf(kiosk):
    kiosk.lost_btn.click()
    type_cpf(kiosk, "11144477735")
    kiosk.cpf_ok.click()
    assert kiosk.stack.currentIndex() == kw.CPF
    assert "Nenhuma comanda" in kiosk.cpf_msg.text()


def test_duplicate_cpf_offers_existing_command(kiosk):
    first = kiosk.services.commands.start_command(kiosk.op.id, CPF)
    kiosk.new_btn.click()
    type_cpf(kiosk, CPF)
    kiosk.cpf_ok.click()
    assert kiosk.stack.currentIndex() == kw.PICK
    assert first.code in kiosk.pick_msg.text()
    assert kiosk.services.commands.find(first.code).status == "OPEN"
    assert kiosk.services.commands.open_commands_by_cpf(CPF)[0].code == first.code


def test_scan_rejects_unknown_and_paid(kiosk):
    kiosk.scan_input.setText("999999")
    kiosk.scan_input.returnPressed.emit()
    assert kiosk.stack.currentIndex() == kw.WELCOME and "não encontrada" in kiosk.welcome_msg.text()
    kiosk.scan_input.setText("000156")                     # paga no seed
    kiosk.scan_input.returnPressed.emit()
    assert kiosk.stack.currentIndex() == kw.WELCOME and "paga" in kiosk.welcome_msg.text()


def test_unstable_or_overload_blocks_customer_registration(kiosk):
    kiosk.scan_input.setText("000155")
    kiosk.scan_input.returnPressed.emit()
    sim = kiosk.scale.simulator
    sim.place_weight(860)
    assert wait_until(lambda: kiosk.state is WeighingState.STABLE)
    sim.unstable = True
    assert wait_until(lambda: kiosk.state is WeighingState.SETTLING)
    assert not kiosk.register_btn.isEnabled()
    sim.unstable = False
    sim.place_weight(40_000)
    assert wait_until(lambda: kiosk.state is WeighingState.OVERLOAD)
    assert "limite" in kiosk.weigh_msg.text() and not kiosk.register_btn.isEnabled()


def test_same_plate_not_registered_twice(kiosk):
    kiosk.scan_input.setText("000155")
    kiosk.scan_input.returnPressed.emit()
    kiosk.scale.simulator.place_weight(860)
    assert wait_until(lambda: kiosk.state is WeighingState.STABLE)
    kiosk.register_btn.click()
    kiosk._go(kw.WEIGH)                                    # cliente volta à balança com o mesmo prato
    kiosk.armed = False
    kiosk._render_weigh()
    assert not kiosk.register_btn.isEnabled()
    assert len(kiosk.services.commands.find("000155").items) == 1


def test_auto_register_countdown(kiosk):
    kiosk.settings.kiosk.auto_register_after_s = 1
    kiosk.scan_input.setText("000155")
    kiosk.scan_input.returnPressed.emit()
    kiosk.scale.simulator.place_weight(860)
    assert wait_until(lambda: kiosk.stack.currentIndex() == kw.EXTRAS, 5000)
    assert len(kiosk.services.commands.find("000155").items) == 1


def test_idle_returns_to_welcome_keeping_command_open(kiosk):
    kiosk.settings.kiosk.idle_timeout_s = 1
    kiosk.scan_input.setText("000155")
    kiosk.scan_input.returnPressed.emit()
    assert wait_until(lambda: kiosk.stack.currentIndex() == kw.WELCOME, 3000)
    assert kiosk.services.commands.find("000155").status == "OPEN"


def test_print_failure_still_goes_to_weighing_with_number(kiosk, monkeypatch):
    from app.printing.printer import PrintResult
    monkeypatch.setattr(kiosk, "_print", lambda info: PrintResult(False, "", "sem papel"))
    kiosk.new_btn.click()
    type_cpf(kiosk, CPF)
    kiosk.cpf_ok.click()
    assert kiosk.stack.currentIndex() == kw.WEIGH
    assert "Não foi possível imprimir" in kiosk.weigh_notice.text() and kiosk.command.code in kiosk.weigh_notice.text()


def test_returning_to_weigh_clears_notice(kiosk):
    kiosk.new_btn.click()
    type_cpf(kiosk, CPF)
    kiosk.cpf_ok.click()
    assert kiosk.weigh_notice.text()
    kiosk.scale.simulator.place_weight(860)
    assert wait_until(lambda: kiosk.state is WeighingState.STABLE)
    kiosk.register_btn.click()
    assert kiosk.stack.currentIndex() == kw.EXTRAS
    kiosk._enter_weigh()                                   # "Pesar outro prato"
    assert kiosk.weigh_notice.text() == ""


def test_option_off_creates_second_command_for_same_cpf(kiosk):
    kiosk.settings.kiosk.block_duplicate_cpf = False
    first = kiosk.services.commands.start_command(kiosk.op.id, CPF)
    kiosk.new_btn.click()
    type_cpf(kiosk, CPF)
    kiosk.cpf_ok.click()
    assert kiosk.stack.currentIndex() == kw.WEIGH                          # criou outra, vai à pesagem
    assert kiosk.command.code != first.code
    assert len(kiosk.services.commands.open_commands_by_cpf(CPF)) == 2
    kiosk._finish_session()
    kiosk.lost_btn.click()                                                 # "perdi": vê as duas
    type_cpf(kiosk, CPF)
    kiosk.cpf_ok.click()
    assert kiosk.stack.currentIndex() == kw.PICK and kiosk.pick_rows.count() == 2


def test_price_change_by_manager_reaches_open_kiosk(kiosk):
    """O gerente muda o preço enquanto o kiosk está aberto: a próxima pesagem já mostra o novo valor."""
    services = kiosk.services
    admin = services.auth.authenticate_admin("9999")
    kiosk.scan_input.setText("000155")
    kiosk.scan_input.returnPressed.emit()
    assert kiosk.price == Decimal("79.90")
    kiosk._finish_session()
    services.pricing.set_price("001", Decimal("89.90"), admin.id)
    kiosk.scan_input.setText("000155")
    kiosk.scan_input.returnPressed.emit()
    assert kiosk.price == Decimal("89.90") and "89,90" in kiosk.price_label.text()
    kiosk.scale.simulator.place_weight(860)
    assert wait_until(lambda: kiosk.state is WeighingState.STABLE)
    assert kiosk.value_label.text() == "R$ 44,95"           # 0,500 x 89,90: igual ao que será cobrado
    kiosk.register_btn.click()
    assert services.commands.find("000155").total == Decimal("44.95")


def test_new_product_appears_without_restarting_kiosk(kiosk):
    from app.database.models import Product, ProductPrice, ProductType
    from datetime import datetime
    db = kiosk.services.db
    assert kiosk.tiles_grid.count() == 3
    with db.session() as s:
        p = Product(code="005", description="SUCO", type=ProductType.UNIT, unit="UN")
        s.add(p)
        s.flush()
        s.add(ProductPrice(product_id=p.id, price=Decimal("7.00"), valid_from=datetime.now()))
    kiosk.scan_input.setText("000155")
    kiosk.scan_input.returnPressed.emit()
    assert [p.description for p in kiosk.products][-1] == "SUCO"
    assert kiosk.tiles_grid.count() == 4

"""Caixa manual e autopagamento (TEF simulado), em Qt offscreen."""
import os
from decimal import Decimal

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from app.bootstrap import build_services
from app.config.settings import AppSettings
from app.payments.gateway import SimulatedTefGateway
from app.ui import cashier_window as cw
from app.ui import selfcheckout_window as sc
from app.ui.theme import apply_theme

CPF = "529.982.247-25"


def wait_until(condition, ms=4000):
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
def env(qapp, tmp_path, monkeypatch):
    monkeypatch.setenv("BALANCA_HOME", str(tmp_path))
    settings = AppSettings(database_url=f"sqlite:///{tmp_path / 'p.db'}")
    settings.printing.pdf_dir = str(tmp_path / "tickets")
    settings.checkout.auto_return_s = 1
    services = build_services(settings)
    yield settings, services, tmp_path
    services.db.dispose()


@pytest.fixture
def cashier(env):
    settings, services, _ = env
    op = next(o for o in services.auth.list_operators() if o.name == "Operador 1")
    win = cw.CashierWindow(settings, services, services.auth.authenticate(op.id, "1111"))
    win.show()
    yield win
    win.close()


def scan(win, text):
    win.scan_input.setText(text)
    win.scan_input.returnPressed.emit()


def receipts(settings):
    folder = settings.printing.pdf_dir
    return [f for f in os.listdir(folder) if f.startswith("comprovante")] if os.path.isdir(folder) else []


# ---------------------------------------------------------------- caixa manual
def test_cashier_cash_payment_with_change_prints_receipt(cashier, env):
    settings, services, _ = env
    scan(cashier, "000154")                                  # OPEN, R$ 20,00 (leu na saída)
    assert cashier.command.status == "OPEN" and cashier.remaining_label[1].text() == "R$ 20,00"
    assert cashier.pay_btn.isEnabled() and cashier.amount.text() == "20,00"
    cashier.tendered.setText("50")
    assert cashier.change_label.text() == "Troco R$ 30,00"
    cashier.pay_btn.click()
    assert cashier.command.status == "PAID"
    assert "paga" in cashier.banner.text() and "R$ 30,00" in cashier.banner.text()
    assert not cashier.pay_btn.isEnabled()
    assert len(receipts(settings)) == 1
    assert services.commands.find("000154").status == "PAID"


def test_cashier_partial_then_card(cashier):
    scan(cashier, "000154")
    cashier.amount.setText("8,00")
    cashier.pay_btn.click()
    assert cashier.command.status == "AWAITING_PAYMENT" and cashier.remaining_label[1].text() == "R$ 12,00"
    assert "parcial" in cashier.banner.text()
    cashier._select_method("CREDIT")
    assert cashier.amount.text() == "12,00"
    cashier.reference.setText("NSU99")
    cashier.pay_btn.click()
    assert cashier.command.status == "PAID"
    assert [p.method for p in cashier.command.payments] == ["CASH", "CREDIT"]
    assert cashier.command.payments[1].reference == "NSU99"


def test_cashier_finds_by_cpf_and_queue(cashier, env):
    _, services, _ = env
    op = services.auth.self_service_operator()
    c = services.commands.start_command(op.id, CPF)
    services.commands.add_unit_product(c.id, op.id, "002")
    services.commands.send_to_payment(c.id)
    cashier._refresh_queue()
    assert cashier.queue.count() == 1 and "***.982.247-**" in cashier.queue.item(0).text()
    scan(cashier, "529.982.247-25")                          # cliente perdeu a comanda
    assert cashier.command.code == c.code and cashier.pay_btn.isEnabled()
    scan(cashier, "111.444.777-35")
    assert cashier.command is None and "Nenhuma comanda" in cashier.scan_msg.text()
    scan(cashier, "123.456.789-00")
    assert "CPF inválido" in cashier.scan_msg.text()


def test_cashier_validation_messages(cashier):
    scan(cashier, "000154")
    cashier.amount.setText("99,00")
    cashier.pay_btn.click()
    assert "excede" in cashier.banner.text()
    cashier.amount.setText("")
    cashier.pay_btn.click()
    assert "Informe o valor" in cashier.banner.text()
    cashier.amount.setText("20,00")
    cashier.tendered.setText("10")
    cashier.pay_btn.click()
    assert "menor" in cashier.banner.text()
    assert cashier.command.paid == Decimal("0.00")
    scan(cashier, "000156")                                  # já paga
    assert not cashier.pay_btn.isEnabled() and "paga" in cashier.scan_msg.text()
    scan(cashier, "000155")                                  # sem itens
    assert not cashier.pay_btn.isEnabled()


def test_cashier_sees_comanda_sent_from_other_station(cashier, env):
    """Outro PC (autoatendimento/operador) envia ao caixa; a fila atualiza sozinha."""
    _, services, _ = env
    assert cashier.queue.count() == 0
    c = services.commands.find("000154")
    services.commands.send_to_payment(c.id)
    cashier._poll()
    assert cashier.queue.count() == 1 and cashier.queue.item(0).text().startswith("000154")
    cashier._pick_from_queue(cashier.queue.item(0))
    assert cashier.command.code == "000154" and cashier.pay_btn.isEnabled()


def test_cashier_reopen(cashier, env, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    _, services, _ = env
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    services.commands.send_to_payment(services.commands.find("000154").id)
    scan(cashier, "000154")
    assert cashier.command.status == "AWAITING_PAYMENT" and cashier.reopen_btn.isEnabled()
    cashier.reopen_btn.click()
    assert cashier.command.status == "OPEN"
    cashier.amount.setText("8,00")
    cashier.pay_btn.click()                                  # pagamento parcial
    assert not cashier.reopen_btn.isEnabled()                # depois de receber, não reabre


# ---------------------------------------------------------------- autopagamento
@pytest.fixture
def selfcheckout(env):
    settings, services, _ = env
    gateway = SimulatedTefGateway(delay_s=0)
    win = sc.SelfCheckoutWindow(settings, services, gateway)
    win.gateway = gateway
    win.show()
    yield win
    win.close()


def test_selfcheckout_pix_approved(selfcheckout, env):
    settings, services, _ = env
    scan(selfcheckout, "000154")
    assert selfcheckout.stack.currentIndex() == sc.SUMMARY
    assert selfcheckout.sum_total.text() == "R$ 20,00" and selfcheckout.sum_table.rowCount() == 2
    selfcheckout.pay_buttons["PIX"].click()
    assert selfcheckout.stack.currentIndex() == sc.PAYING
    assert wait_until(lambda: selfcheckout.stack.currentIndex() == sc.DONE)
    info = services.commands.find("000154")
    assert info.status == "PAID" and info.payments[0].method == "PIX"
    assert info.payments[0].reference.startswith("SIM") and info.payments[0].operator_name == "Autoatendimento"
    assert selfcheckout.done_code.text() == "000154" and len(receipts(settings)) == 1
    assert wait_until(lambda: selfcheckout.stack.currentIndex() == sc.WELCOME)


def test_selfcheckout_decline_then_retry(selfcheckout, env):
    _, services, _ = env
    scan(selfcheckout, "000154")
    selfcheckout.gateway.decline_next = True
    selfcheckout.pay_buttons["CREDIT"].click()
    assert wait_until(lambda: selfcheckout.stack.currentIndex() == sc.SUMMARY)
    assert "recusado" in selfcheckout.sum_msg.text()
    assert services.commands.find("000154").status == "AWAITING_PAYMENT"      # travada, sem pagamento
    assert services.commands.find("000154").paid == Decimal("0.00")
    selfcheckout.pay_buttons["DEBIT"].click()
    assert wait_until(lambda: selfcheckout.stack.currentIndex() == sc.DONE)
    assert services.commands.find("000154").status == "PAID"


def test_selfcheckout_by_cpf_and_rejections(selfcheckout, env):
    _, services, _ = env
    op = services.auth.self_service_operator()
    c = services.commands.start_command(op.id, CPF)
    services.commands.add_unit_product(c.id, op.id, "004", 2)
    selfcheckout.lost_btn.click()
    for ch in "52998224725":
        selfcheckout.cpf.keys[ch].click()
    selfcheckout.cpf_ok.click()
    assert selfcheckout.stack.currentIndex() == sc.SUMMARY and selfcheckout.sum_total.text() == "R$ 24,00"
    selfcheckout._finish()
    scan(selfcheckout, "000156")
    assert "paga" in selfcheckout.welcome_msg.text()
    scan(selfcheckout, "000155")
    assert "não possui itens" in selfcheckout.welcome_msg.text()
    scan(selfcheckout, "999999")
    assert "não cadastrada" in selfcheckout.welcome_msg.text().lower()


def test_selfcheckout_registration_failure_logs_nsu(selfcheckout, env, monkeypatch):
    _, services, home = env
    scan(selfcheckout, "000154")

    def boom(*a, **k):
        raise RuntimeError("banco caiu")
    monkeypatch.setattr(selfcheckout.services.commands, "register_payment", boom)
    selfcheckout.pay_buttons["PIX"].click()
    assert wait_until(lambda: selfcheckout.stack.currentIndex() == sc.DONE)
    assert "Chame um atendente" in selfcheckout.done_msg.text() and "SIM000001" in selfcheckout.done_msg.text()
    log = (home / "pagamentos_pendentes.log").read_text(encoding="utf-8")
    assert "comanda=000154" in log and "SIM000001" in log


def _two_open_for_cpf(services):
    op = services.auth.self_service_operator()
    codes = []
    for _ in range(2):
        c = services.commands.start_command(op.id, CPF, allow_duplicate_cpf=True)
        services.commands.add_unit_product(c.id, op.id, "002")
        codes.append(c.code)
    return codes


def test_cashier_warns_when_cpf_has_several_open_commands(cashier, env):
    _, services, _ = env
    older, newer = _two_open_for_cpf(services)
    scan(cashier, CPF)
    assert cashier.command.code == newer                                   # mais recente
    assert "mais 1 comanda" in cashier.scan_msg.text() and older in cashier.scan_msg.text()


def test_selfcheckout_refuses_to_guess_between_commands(selfcheckout, env):
    _, services, _ = env
    _two_open_for_cpf(services)
    scan(selfcheckout, CPF)
    assert selfcheckout.stack.currentIndex() == sc.WELCOME
    assert "mais de uma comanda" in selfcheckout.welcome_msg.text()
    assert selfcheckout.command is None                                    # nada foi cobrado

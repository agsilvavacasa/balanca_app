"""Percorre a tela como o operador, sobre a balança simulada (Qt offscreen)."""
import os
import sys
from decimal import Decimal

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from app.bootstrap import build_services
from app.config.settings import AppSettings
from app.services.weighing_service import WeighingState
from app.ui import dialogs, main_window
from app.ui.theme import apply_theme


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    apply_theme(app)
    return app


@pytest.fixture
def window(qapp, tmp_path, monkeypatch):
    monkeypatch.setenv("BALANCA_HOME", str(tmp_path))
    settings = AppSettings(database_url=f"sqlite:///{tmp_path / 'ui.db'}")
    settings.scale.poll_ms = 30
    services = build_services(settings)
    operator = services.auth.authenticate(
        next(o.id for o in services.auth.list_operators() if o.name == "Operador 1"), "1111")
    win = main_window.MainWindow(settings, services, operator)
    win.show()
    assert wait_until(lambda: win.link_ok, 5000)
    yield win
    win.close()
    services.db.dispose()


def wait_until(condition, ms=3000):
    """Espera em passos curtos: um QTest.qWait longo não solta o GIL do Python e deixaria
    a thread da balança parada durante a espera (artefato do teste, não do app)."""
    waited = 0
    while not condition() and waited < ms:
        QTest.qWait(10)
        waited += 10
    return condition()


def wait_state(win, state, ms=3000):
    assert wait_until(lambda: win.state is state, ms), f"estado {win.state}, esperado {state}"


def scan(win, code):
    win.command_input.setText(code)
    win.command_input.returnPressed.emit()


def test_full_weighing_flow(window, monkeypatch):
    win = window
    sim = win.scale.simulator
    assert win.link_ok and win.scale_chip.text() == "BALANÇA SIMULADA"
    assert not win.register_btn.isEnabled()

    scan(win, "000154")
    assert win.command.status == "OPEN"
    assert win.total_label.text() == "R$ 20,00"

    sim.place_weight(360)                      # prato vazio
    win.tare_btn.click()                       # tara enviada pelo sistema (opção B)
    assert wait_until(lambda: win.tare_sent_g == 360)
    assert sim.tare_g == 360

    sim.place_weight(860)                      # cliente monta o prato
    wait_state(win, WeighingState.STABLE)
    assert win.weight == Decimal("0.500")
    assert win.weight_label.text() == "0,500 kg"
    assert win.value_label.text() == "R$ 39,95"
    assert win.register_btn.isEnabled()

    monkeypatch.setattr(dialogs.ConfirmConsumptionDialog, "exec",
                        lambda self: self.DialogCode.Accepted)
    win.register_btn.click()
    assert win.total_label.text() == "R$ 59,95"          # 8,00 + 12,00 + 39,95
    assert win.table.rowCount() == 3
    assert not win.register_btn.isEnabled()              # mesmo prato: não registra de novo

    sim.place_weight(0)                                   # tira o prato -> negativo (tara ativa)
    wait_state(win, WeighingState.NEGATIVE)
    assert win.armed                                      # prato saiu: pode registrar de novo
    sim.place_weight(860)                                 # próximo cliente, mesma tara memorizada
    wait_state(win, WeighingState.STABLE)
    assert win.register_btn.isEnabled()


def test_instability_blocks_registration(window):
    win = window
    scan(win, "000155")
    sim = win.scale.simulator
    sim.place_weight(500)
    wait_state(win, WeighingState.STABLE)
    assert win.register_btn.isEnabled()
    sim.unstable = True
    wait_state(win, WeighingState.SETTLING)
    assert not win.register_btn.isEnabled()
    assert "estabilização" in win.weight_msg.text()
    sim.unstable = False
    sim.place_weight(40_000)
    wait_state(win, WeighingState.OVERLOAD)
    assert not win.register_btn.isEnabled()
    assert win.weight_msg.text() == "Peso acima da capacidade da balança."


def test_closed_and_unknown_command(window):
    win = window
    scan(win, "000156")
    assert win.command.status == "PAID"
    assert not win.register_btn.isEnabled()
    assert all(not b.isEnabled() for b in win.product_buttons)
    scan(win, "999999")
    assert win.command is None
    assert "não cadastrada" in win.command_msg.text().lower()


def test_cancel_item_keeps_history(window, monkeypatch):
    win = window
    scan(win, "000154")
    win.table.selectRow(0)
    assert win.cancel_btn.isEnabled()
    monkeypatch.setattr(dialogs.CancelConsumptionDialog, "exec",
                        lambda self: self.DialogCode.Accepted)
    monkeypatch.setattr(dialogs.CancelConsumptionDialog, "reason_text",
                        property(lambda self: "Cliente desistiu"))
    win.cancel_btn.click()
    assert win.total_label.text() == "R$ 12,00"
    assert win.table.rowCount() == 2                     # continua listado, marcado como cancelado
    assert win.table.item(0, 4).text() == "Cancelado"


def test_no_scale_message(qapp, tmp_path, monkeypatch):
    monkeypatch.setenv("BALANCA_HOME", str(tmp_path))
    settings = AppSettings(database_url=f"sqlite:///{tmp_path / 'x.db'}")
    settings.scale.mode = "serial"
    settings.scale.port = "COM99" if sys.platform == "win32" else "/dev/porta_que_nao_existe"
    settings.scale.poll_ms = 30
    services = build_services(settings)
    op = services.auth.list_operators()[0]
    win = main_window.MainWindow(settings, services,
                                 services.auth.authenticate(op.id, "1111") or op)
    win.show()
    assert wait_until(lambda: win.scale_chip.text() == "BALANÇA DESCONECTADA")
    assert not win.link_ok
    assert "Verifique" in win.weight_msg.text()
    assert not win.tare_btn.isEnabled()
    win.close()
    services.db.dispose()

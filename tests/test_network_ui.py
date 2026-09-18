"""Terminais reais (telas) falando com o servidor pela rede."""
import os
from decimal import Decimal

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

import main as entry
from app.bootstrap import build_services
from app.config.settings import AppSettings
from app.net.client import build_remote_services
from app.net.server import ServerHost
from app.ui import kiosk_window as kw
from app.ui.connection_dialog import ConnectionDialog
from app.ui.server_window import ServerWindow
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
def lan(qapp, tmp_path, monkeypatch):
    """Servidor com dados locais + configuração de um terminal apontando para ele."""
    monkeypatch.setenv("BALANCA_HOME", str(tmp_path))
    server_settings = AppSettings(database_url=f"sqlite:///{tmp_path / 'srv.db'}")
    local = build_services(server_settings)
    host = ServerHost(local, "CODIGO23", host="127.0.0.1", port=0, name="Caixa")
    host.start()
    yield host, local, tmp_path
    host.stop()
    local.db.dispose()


def terminal_settings(host, tmp_path, name="k"):
    s = AppSettings()
    s.scale.poll_ms = 30
    s.printing.pdf_dir = str(tmp_path / f"tickets_{name}")
    s.kiosk.done_screen_s = 1
    s.connection.mode, s.connection.host = "remote", "127.0.0.1"
    s.connection.port, s.connection.access_key = host.port, "CODIGO23"
    return s


def test_kiosk_over_network_creates_command_seen_by_server(lan):
    host, local, tmp_path = lan
    s = terminal_settings(host, tmp_path)
    remote = build_remote_services("127.0.0.1", host.port, "CODIGO23", "autoatendimento@kiosk1")
    win = kw.KioskWindow(s, remote)
    win.show()
    assert wait_until(lambda: win.link_ok)
    win.new_btn.click()
    for ch in "52998224725":
        win.cpf.keys[ch].click()
    win.cpf_ok.click()
    assert win.stack.currentIndex() == kw.NEWDONE
    code = win.new_code.text()
    seen = local.commands.find(code)                        # o servidor (outro PC) enxerga
    assert seen.status == "OPEN" and seen.customer_cpf == "52998224725"
    assert os.listdir(s.printing.pdf_dir)[0].startswith(f"comanda_{code}")   # e a impressão é local

    win._finish_session()
    win.scan_input.setText(code)
    win.scan_input.returnPressed.emit()
    win.scale.simulator.place_weight(860)
    assert wait_until(lambda: win.state.value == "STABLE")
    win.register_btn.click()
    win._bump("003", 2)
    win.extras_ok.click()
    assert local.commands.find(code).total == Decimal("47.95")   # 39,95 + 2 x 4,00
    win.close()


def test_two_kiosks_share_one_server(lan):
    host, local, tmp_path = lan
    wins = []
    for name in ("kiosk1", "kiosk2"):
        remote = build_remote_services("127.0.0.1", host.port, "CODIGO23", f"autoatendimento@{name}")
        win = kw.KioskWindow(terminal_settings(host, tmp_path, name), remote)
        win.show()
        wins.append(win)
    for i, win in enumerate(wins):
        assert wait_until(lambda w=win: w.link_ok)
        win.new_btn.click()
        for ch in ("52998224725", "11144477735")[i]:
            win.cpf.keys[ch].click()
        win.cpf_ok.click()
    codes = {w.new_code.text() for w in wins}
    assert len(codes) == 2
    assert {c.name for c in host.active_clients()} == {"autoatendimento@kiosk1", "autoatendimento@kiosk2"}
    for w in wins:
        w.close()


def test_kiosk_shows_friendly_message_when_server_goes_away(lan):
    host, local, tmp_path = lan
    remote = build_remote_services("127.0.0.1", host.port, "CODIGO23", "kiosk")
    win = kw.KioskWindow(terminal_settings(host, tmp_path), remote)
    win.show()
    host.stop()
    win.new_btn.click()
    for ch in "52998224725":
        win.cpf.keys[ch].click()
    win.cpf_ok.click()
    assert win.stack.currentIndex() == kw.CPF                        # não avançou
    assert "Sem conexão com o servidor" in win.cpf_msg.text()
    win.close()


def test_connection_dialog_tests_and_saves(lan, monkeypatch):
    host, _, tmp_path = lan
    dialog = ConnectionDialog(AppSettings(), "teste")
    assert dialog.remote_radio.isChecked()
    dialog._save()
    assert "Informe o IP" in dialog.result.text() and dialog.settings.connection.mode == ""
    dialog.host.setText("127.0.0.1")
    dialog.port.setValue(host.port)
    dialog.key.setText("errado")
    assert dialog._test() is None and "incorreto" in dialog.result.text()
    dialog.key.setText("codigo23")                                   # minúsculas: normaliza
    assert dialog._test() == "ok" and "Conectado" in dialog.result.text()
    dialog._save()
    conn = dialog.settings.connection
    assert (conn.mode, conn.host, conn.access_key) == ("remote", "127.0.0.1", "CODIGO23")
    dialog.local_radio.setChecked(True)
    dialog._save()
    assert dialog.settings.connection.mode == "local"


def test_server_window_shows_code_and_clients(qapp, tmp_path, monkeypatch):
    monkeypatch.setenv("BALANCA_HOME", str(tmp_path))
    settings = AppSettings(database_url=f"sqlite:///{tmp_path / 's.db'}")
    services = build_services(settings)
    opened = []
    win = ServerWindow(settings, services, opener=lambda m: opened.append(m), port=0)
    win.show()
    assert win.status.text() == "SERVIDOR ATIVO"
    key = settings.server.access_key
    assert len(key) == 8 and win.code.text() == key
    remote = build_remote_services("127.0.0.1", win.host.port, key, "caixa@PC2")
    remote.auth.list_operators()
    win._refresh()
    assert "caixa@PC2" in win.clients.item(0).text()
    win._open("caixa")
    assert opened == ["caixa"]
    win.host.active_clients = lambda *a, **k: []                     # fecha sem confirmação
    win.close()
    services.db.dispose()


def test_open_window_server_mode(qapp, tmp_path, monkeypatch):
    monkeypatch.setenv("BALANCA_HOME", str(tmp_path))
    settings = AppSettings(database_url=f"sqlite:///{tmp_path / 'o.db'}")
    settings.server.port = 0
    services = build_services(settings)
    window = entry.open_window("servidor", settings, services, windowed=True)
    assert isinstance(window, ServerWindow) and window.host.running
    window.host.active_clients = lambda *a, **k: []
    window.close()
    services.db.dispose()

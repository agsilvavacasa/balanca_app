import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

import main as entry
from app.config.settings import AppSettings, load_settings, save_settings
from app.database.connection import check_connection
from app.ui.db_dialog import DatabaseDialog, build_mysql_url


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def test_parse_args():
    args = entry.parse_args(["--modo", "caixa", "--checkout", "auto", "--janela"])
    assert (args.modo, args.checkout, args.janela) == ("caixa", "auto", True)
    assert entry.parse_args([]).modo is None
    with pytest.raises(SystemExit):
        entry.parse_args(["--modo", "invalido"])


def test_mysql_url_escapes_special_password_chars():
    url = build_mysql_url("192.168.0.10", 3306, "restaurante", "app", "p@ss:w/rd#1")
    assert url.startswith("mysql+pymysql://app:") and "@192.168.0.10:3306/restaurante" in url
    assert "p@ss:w/rd#1" not in url                          # caracteres especiais escapados
    from sqlalchemy.engine import make_url
    assert make_url(url).password == "p@ss:w/rd#1"           # e recuperados intactos


def test_database_test_sqlite_ok_and_failure(tmp_path):
    ok, msg = check_connection(f"sqlite:///{tmp_path / 'x.db'}")
    assert ok and "estabelecida" in msg
    ok, msg = check_connection("sqlite:////nao/existe/pasta/x.db")
    assert not ok and msg
    ok, msg = check_connection("mysql+pymysql://u:p@127.0.0.1:1/x", timeout_s=1)     # ninguém escutando
    assert not ok and msg


def test_settings_roundtrip_with_new_sections(tmp_path, monkeypatch):
    monkeypatch.setenv("BALANCA_HOME", str(tmp_path))
    s = AppSettings()
    s.role = "caixa"
    s.checkout.mode = "auto"
    s.kiosk.require_cpf = False
    s.printing.printer_name = "@default"
    save_settings(s)
    loaded = load_settings()
    assert (loaded.role, loaded.checkout.mode, loaded.kiosk.require_cpf, loaded.printing.printer_name) == (
        "caixa", "auto", False, "@default")


def test_old_config_without_new_sections_still_loads(tmp_path, monkeypatch):
    monkeypatch.setenv("BALANCA_HOME", str(tmp_path))
    (tmp_path / "config.json").write_text('{"database_url": null, "scale": {"mode": "simulated"}}',
                                          encoding="utf-8")
    loaded = load_settings()
    assert loaded.role == "" and loaded.checkout.mode == "manual" and loaded.kiosk.fullscreen


def test_db_dialog_builds_and_validates(qapp, tmp_path, monkeypatch):
    monkeypatch.setenv("BALANCA_HOME", str(tmp_path))
    dialog = DatabaseDialog(AppSettings())
    dialog.kind.setCurrentIndex(0)
    assert not dialog._valid_form()                         # falta servidor/usuário
    dialog.host.setText("10.0.0.5")
    dialog.user.setText("app")
    dialog.password.setText("segredo")
    assert dialog._valid_form()
    assert dialog.current_url().startswith("mysql+pymysql://app:segredo@10.0.0.5:3306/restaurante")
    dialog.kind.setCurrentIndex(1)
    assert dialog.current_url().startswith("sqlite:///")


def test_open_window_builds_each_mode(qapp, tmp_path, monkeypatch):
    from app.bootstrap import build_services
    from app.ui import cashier_window, kiosk_window, main_window, selfcheckout_window
    monkeypatch.setenv("BALANCA_HOME", str(tmp_path))
    settings = AppSettings(database_url=f"sqlite:///{tmp_path / 'm.db'}")
    settings.scale.poll_ms = 50
    services = build_services(settings)
    operator = services.auth.list_operators()[0]
    monkeypatch.setattr(entry, "login", lambda _services: operator)
    expected = [("autoatendimento", "manual", kiosk_window.KioskWindow),
                ("caixa", "manual", cashier_window.CashierWindow),
                ("caixa", "auto", selfcheckout_window.SelfCheckoutWindow),
                ("operador", "manual", main_window.MainWindow)]
    for mode, checkout, cls in expected:
        settings.checkout.mode = checkout
        window = entry.open_window(mode, settings, services, windowed=True)
        assert isinstance(window, cls), (mode, checkout)
        window.close()
    monkeypatch.setattr(entry, "login", lambda _services: None)         # login cancelado
    assert entry.open_window("caixa", settings, services, windowed=True) is None
    services.db.dispose()


def test_unhandled_error_is_logged_and_reported(qapp, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    from app.services.errors import BusinessError
    monkeypatch.setenv("BALANCA_HOME", str(tmp_path))
    shown = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a: shown.append(("warning", a[2])))
    monkeypatch.setattr(QMessageBox, "critical", lambda *a: shown.append(("critical", a[2])))
    try:
        raise BusinessError("Sem conexão com o servidor.")
    except BusinessError as exc:
        entry.handle_exception(type(exc), exc, exc.__traceback__)
    try:
        raise RuntimeError("bug")
    except RuntimeError as exc:
        entry.handle_exception(type(exc), exc, exc.__traceback__)
    assert shown[0] == ("warning", "Sem conexão com o servidor.")
    assert shown[1][0] == "critical" and "erros.log" in shown[1][1]
    log = (tmp_path / "erros.log").read_text(encoding="utf-8")
    assert "BusinessError" in log and "RuntimeError: bug" in log


def test_block_duplicate_cpf_defaults_on_and_persists(tmp_path, monkeypatch):
    monkeypatch.setenv("BALANCA_HOME", str(tmp_path))
    assert AppSettings().kiosk.block_duplicate_cpf is True
    s = AppSettings()
    s.kiosk.block_duplicate_cpf = False
    save_settings(s)
    assert load_settings().kiosk.block_duplicate_cpf is False

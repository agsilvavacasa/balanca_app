"""Restaurante por quilo — servidor, autoatendimento, caixa e operador (Toledo Prix 3 Fit).

Uso:  python main.py [--modo servidor|autoatendimento|caixa|operador] [--checkout manual|auto] [--janela]
Sem --modo usa o `role` do config.json; se estiver vazio, pergunta.

Arquitetura: UM PC roda o SERVIDOR (guarda os dados e aceita os terminais). Autoatendimento, caixa e
operador em outros PCs perguntam o IP e o código do servidor na primeira vez."""
import argparse
import socket
import sys
import traceback
from datetime import datetime

from PySide6.QtWidgets import QApplication, QMessageBox

from app.bootstrap import Services, build_services
from app.config.settings import AppSettings, config_dir, load_settings, save_settings
from app.net.client import build_remote_services
from app.services.errors import BusinessError
from app.ui.connection_dialog import ConnectionDialog
from app.ui.db_dialog import DatabaseDialog
from app.ui.dialogs import LoginDialog
from app.ui.theme import apply_theme

MODES = ("servidor", "autoatendimento", "caixa", "operador")


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--modo", choices=MODES, help="função deste computador")
    parser.add_argument("--checkout", choices=("manual", "auto"),
                        help="caixa: 'manual' (operador) ou 'auto' (cliente paga no TEF)")
    parser.add_argument("--abrir", choices=("caixa", "operador"),
                        help="no modo servidor, abre esta tela junto com o servidor")
    parser.add_argument("--janela", action="store_true", help="não abrir em tela cheia")
    return parser.parse_args(argv)


_showing_error = False


def handle_exception(exc_type, exc, tb) -> None:
    """Erro não tratado numa tela: registra em erros.log e avisa, em vez de falhar em silêncio
    (ex.: a rede caiu no meio de uma operação)."""
    global _showing_error
    try:
        with open(config_dir() / "erros.log", "a", encoding="utf-8") as fh:
            fh.write(f"--- {datetime.now().isoformat(timespec='seconds')}\n")
            fh.write("".join(traceback.format_exception(exc_type, exc, tb)))
    except OSError:
        pass
    if _showing_error or QApplication.instance() is None:
        return
    _showing_error = True
    try:
        if isinstance(exc, BusinessError):
            QMessageBox.warning(None, "Aviso", str(exc))
        else:
            QMessageBox.critical(None, "Erro inesperado",
                                 f"Ocorreu um erro: {exc}\n\nOs detalhes foram gravados em erros.log.")
    finally:
        _showing_error = False


def client_name(mode: str) -> str:
    return f"{mode}@{socket.gethostname()}"


def connect_local(settings: AppSettings) -> Services | None:
    """Abre o banco deste PC; se falhar, deixa corrigir a configuração e tentar de novo."""
    while True:
        try:
            return build_services(settings)
        except Exception as exc:
            box = QMessageBox(QMessageBox.Icon.Critical, "Banco de dados indisponível",
                              f"Não foi possível abrir o banco:\n{settings.effective_database_url}\n\n{exc}")
            configure = box.addButton("Configurar banco…", QMessageBox.ButtonRole.AcceptRole)
            box.addButton("Sair", QMessageBox.ButtonRole.RejectRole)
            box.exec()
            if box.clickedButton() is not configure:
                return None
            dialog = DatabaseDialog(settings)
            if dialog.exec() == dialog.DialogCode.Accepted and dialog.url:
                settings.database_url = dialog.url
                save_settings(settings)


def connect_remote(settings: AppSettings, mode: str) -> Services | None:
    conn = settings.connection
    while True:
        try:
            return build_remote_services(conn.host, conn.port, conn.access_key, client_name(mode))
        except BusinessError as exc:
            box = QMessageBox(QMessageBox.Icon.Warning, "Servidor indisponível",
                              f"{exc}\n\nServidor configurado: {conn.host}:{conn.port}")
            retry = box.addButton("Tentar de novo", QMessageBox.ButtonRole.AcceptRole)
            configure = box.addButton("Alterar conexão…", QMessageBox.ButtonRole.ActionRole)
            box.addButton("Sair", QMessageBox.ButtonRole.RejectRole)
            box.exec()
            clicked = box.clickedButton()
            if clicked is configure:
                if ConnectionDialog(settings, client_name(mode)).exec() != ConnectionDialog.DialogCode.Accepted:
                    return None
                if settings.connection.mode == "local":
                    return connect_local(settings)
            elif clicked is not retry:
                return None


def connect_services(settings: AppSettings, mode: str) -> Services | None:
    if mode == "servidor":                      # o servidor sempre guarda os dados neste PC
        return connect_local(settings)
    if settings.connection.mode == "":          # primeira vez: perguntar onde estão os dados
        dialog = ConnectionDialog(settings, client_name(mode))
        if dialog.exec() != dialog.DialogCode.Accepted:
            return None
    if settings.connection.mode == "remote":
        return connect_remote(settings, mode)
    return connect_local(settings)


def login(services: Services):
    dialog = LoginDialog(services.auth.list_operators(), services.auth.authenticate)
    return dialog.operator if dialog.exec() == dialog.DialogCode.Accepted else None


def open_window(mode: str, settings: AppSettings, services: Services, windowed: bool, open_after=None):
    if mode == "servidor":
        from app.ui.server_window import ServerWindow
        window = ServerWindow(settings, services, opener=lambda m: open_window(
            m, settings, services, windowed))
        window.show()
        if open_after:
            window._open(open_after)
        return window
    if mode == "autoatendimento":
        from app.ui.kiosk_window import KioskWindow
        window = KioskWindow(settings, services)
        fullscreen = settings.kiosk.fullscreen and not windowed
    elif mode == "caixa" and settings.checkout.mode == "auto":
        from app.ui.selfcheckout_window import SelfCheckoutWindow
        window = SelfCheckoutWindow(settings, services)
        fullscreen = settings.kiosk.fullscreen and not windowed
    else:
        operator = login(services)
        if operator is None:
            return None
        if mode == "caixa":
            from app.ui.cashier_window import CashierWindow
            window = CashierWindow(settings, services, operator)
        else:
            from app.ui.main_window import MainWindow
            window = MainWindow(settings, services, operator)
        fullscreen = False
    window.showFullScreen() if fullscreen else window.show()
    return window


def main(argv=None) -> int:
    args = parse_args(argv)
    app = QApplication(sys.argv[:1])
    app.setApplicationName("Restaurante por Quilo")
    apply_theme(app)
    sys.excepthook = handle_exception

    settings = load_settings()
    if args.checkout:
        settings.checkout.mode = args.checkout
    mode = args.modo or settings.role
    if mode not in MODES:
        from app.ui.launcher import ModeDialog
        chooser = ModeDialog(settings)
        if chooser.exec() != chooser.DialogCode.Accepted or chooser.mode is None:
            return 0
        mode = chooser.mode

    services = connect_services(settings, mode)
    if services is None:
        return 1
    window = open_window(mode, settings, services, args.janela, open_after=args.abrir)
    if window is None:
        return 0
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())

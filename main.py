"""Restaurante por quilo — registro de consumo com balança Toledo Prix 3 Fit."""
import sys

from PySide6.QtWidgets import QApplication, QMessageBox

from app.bootstrap import build_services
from app.config.settings import load_settings
from app.ui.dialogs import LoginDialog
from app.ui.main_window import MainWindow
from app.ui.theme import apply_theme


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Restaurante por Quilo")
    apply_theme(app)

    settings = load_settings()
    try:
        services = build_services(settings)
    except Exception as exc:   # MySQL fora do ar, credencial errada etc.
        QMessageBox.critical(None, "Banco de dados indisponível",
                             f"Não foi possível abrir o banco:\n{settings.effective_database_url}\n\n{exc}")
        return 1

    login = LoginDialog(services.auth.list_operators(), services.auth.authenticate)
    if login.exec() != login.DialogCode.Accepted or login.operator is None:
        return 0

    window = MainWindow(settings, services, login.operator)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())

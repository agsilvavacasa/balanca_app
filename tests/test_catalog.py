"""Cadastro de produtos e preços: só gerente, validado no servidor."""
from decimal import Decimal

import pytest

from app.net import protocol
from app.net.client import build_remote_services
from app.net.server import ServerHost
from app.services import auth_service, dto, errors

ADMIN = "9999"       # PIN de gerente do seed
OPERATOR = "1111"    # PIN de operador comum


def test_only_manager_pin_is_accepted(services):
    catalog = services["catalog"]
    calls = [lambda pin: catalog.list_products(pin),
             lambda pin: catalog.create_product(pin, "SUCO", Decimal("7")),
             lambda pin: catalog.set_price(pin, "001", Decimal("90"))]
    for pin, call in zip(("", "0000", OPERATOR), calls):       # 3 erros: abaixo do limite de tentativas
        with pytest.raises(errors.NotAuthorized, match="PIN de gerente"):
            call(pin)
    assert services["pricing"].current_price("001") == Decimal("79.90")   # nada mudou


def test_list_products_includes_inactive_and_current_price(services):
    items = services["catalog"].list_products(ADMIN)
    assert [(p.code, p.description, p.price) for p in items] == [
        ("001", "COMIDA POR KG", Decimal("79.90")), ("002", "REFRIGERANTE", Decimal("8.00")),
        ("003", "ÁGUA", Decimal("4.00")), ("004", "SOBREMESA", Decimal("12.00"))]
    assert items[0].type == "WEIGHT" and all(p.active for p in items)


def test_create_product_generates_code_and_shows_in_kiosk_list(services):
    created = services["catalog"].create_product(ADMIN, "  suco   de  laranja ", Decimal("7,5".replace(",", ".")))
    assert (created.code, created.description, created.price, created.active) == (
        "005", "SUCO DE LARANJA", Decimal("7.50"), True)
    kiosk_view = services["commands"].unit_products()
    assert kiosk_view[-1].description == "SUCO DE LARANJA" and kiosk_view[-1].price == Decimal("7.50")


@pytest.mark.parametrize("desc,price,message", [
    ("", "5", "nome"), ("A", "5", "nome"), ("X" * 41, "5", "no máximo 40"),
    ("SUCO", "0", "maior que zero"), ("SUCO", "-1", "maior que zero"), ("SUCO", "10000", "9.999,99"),
    ("refrigerante", "5", "Já existe"),
])
def test_create_product_validation(services, desc, price, message):
    with pytest.raises(errors.BusinessError, match=message):
        services["catalog"].create_product(ADMIN, desc, Decimal(price))
    assert len(services["catalog"].list_products(ADMIN)) == 4


def test_rename_and_duplicate_rename(services):
    catalog = services["catalog"]
    assert catalog.rename_product(ADMIN, 3, "água mineral").description == "ÁGUA MINERAL"
    with pytest.raises(errors.BusinessError, match="Já existe"):
        catalog.rename_product(ADMIN, 3, "sobremesa")
    with pytest.raises(errors.BusinessError, match="não encontrado"):
        catalog.rename_product(ADMIN, 999, "X1")


def test_deactivate_hides_from_kiosk_but_keeps_history(services, operator):
    catalog, cmds = services["catalog"], services["commands"]
    c = cmds.find("000154")                                     # tem REFRIGERANTE lançado
    refri = next(p for p in catalog.list_products(ADMIN) if p.code == "002")
    catalog.set_active(ADMIN, refri.id, False)
    assert "REFRIGERANTE" not in [p.description for p in cmds.unit_products()]
    assert [i.description for i in cmds.get(c.id).items][0] == "REFRIGERANTE"   # histórico intacto
    assert cmds.get(c.id).total == Decimal("20.00")
    assert not next(p for p in catalog.list_products(ADMIN) if p.code == "002").active
    catalog.set_active(ADMIN, refri.id, True)                   # dá para reativar
    assert "REFRIGERANTE" in [p.description for p in cmds.unit_products()]


def test_weighed_product_cannot_be_deactivated(services):
    with pytest.raises(errors.BusinessError, match="comida por quilo"):
        services["catalog"].set_active(ADMIN, 1, False)


def test_set_price_keeps_history_and_old_consumptions(services, operator):
    catalog, cmds = services["catalog"], services["commands"]
    c = cmds.find("000155")
    cmds.add_weighed_consumption(c.id, operator.id, Decimal("0.500"))
    updated = catalog.set_price(ADMIN, "001", Decimal("84.90"))
    assert updated.price == Decimal("84.90")
    assert cmds.get(c.id).items[0].total_price == Decimal("39.95")                  # antigo intacto
    assert cmds.add_weighed_consumption(c.id, operator.id, Decimal("0.500")).total_price == Decimal("42.45")
    for bad in ("0", "-5", "10000"):
        with pytest.raises(errors.BusinessError):
            catalog.set_price(ADMIN, "001", Decimal(bad))
    with pytest.raises(errors.PriceNotFound):
        catalog.set_price(ADMIN, "999", Decimal("5"))


def test_price_change_records_the_manager(services):
    from app.database.models import ProductPrice
    services["catalog"].set_price(ADMIN, "004", Decimal("13.00"))
    with services["db"].session() as s:
        rows = s.query(ProductPrice).filter_by(product_id=4).order_by(ProductPrice.id).all()
        assert [r.price for r in rows] == [Decimal("12.00"), Decimal("13.00")]
        assert rows[0].valid_until is not None and rows[1].valid_until is None
        assert rows[1].created_by_id is not None


# ---- limite de tentativas do PIN de gerente -------------------------------------------------
def test_admin_pin_lockout_after_repeated_failures(services, monkeypatch):
    auth = services["auth"]
    clock = [1000.0]
    monkeypatch.setattr(auth_service.time, "monotonic", lambda: clock[0])
    for _ in range(auth_service.MAX_ADMIN_FAILS):
        assert auth.authenticate_admin("0000") is None
    with pytest.raises(errors.NotAuthorized, match="Muitas tentativas"):
        auth.authenticate_admin(ADMIN)                          # travado, mesmo com o PIN certo
    clock[0] += auth_service.ADMIN_LOCK_SECONDS + 1
    assert auth.authenticate_admin(ADMIN).name == "Gerente"     # destrava
    assert auth.authenticate_admin("0000") is None              # e o contador recomeçou
    assert auth.authenticate_admin(ADMIN) is not None


# ---- pela rede ---------------------------------------------------------------------------------
@pytest.fixture
def net(tmp_path):
    from app.bootstrap import build_services
    from app.config.settings import AppSettings
    local = build_services(AppSettings(database_url=f"sqlite:///{tmp_path / 'c.db'}"))
    host = ServerHost(local, "CATALOGO", host="127.0.0.1", port=0)
    host.start()
    yield build_remote_services("127.0.0.1", host.port, "CATALOGO", "gerente"), local
    host.stop()
    local.db.dispose()


def test_catalog_over_network_needs_pin_and_changes_prices(net):
    remote, local = net
    with pytest.raises(errors.NotAuthorized):
        remote.catalog.set_price("1234", "001", Decimal("99"))
    assert local.pricing.current_price("001") == Decimal("79.90")
    remote.catalog.set_price(ADMIN, "001", Decimal("81.90"))
    assert local.pricing.current_price("001") == Decimal("81.90")
    created = remote.catalog.create_product(ADMIN, "Suco", Decimal("7"))
    assert isinstance(created, dto.ProductAdminInfo) and created.code == "005"
    assert remote.catalog.list_products(ADMIN)[-1].price == Decimal("7.00")


def test_pricing_set_price_is_no_longer_exposed_over_network(net):
    remote, local = net
    op = remote.auth.self_service_operator()
    with pytest.raises(AttributeError):                            # o cliente nem oferece mais o método
        remote.pricing.set_price("001", Decimal("1.00"), op.id)
    raw = remote.pricing._client
    with pytest.raises(errors.BusinessError):
        raw.call("pricing", "set_price", ("001", Decimal("1.00"), op.id), {})
    assert local.pricing.current_price("001") == Decimal("79.90")
    assert "set_price" not in protocol.ALLOWED["pricing"]


# ---- telas ---------------------------------------------------------------------------------------
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication
    from app.ui.theme import apply_theme
    app = QApplication.instance() or QApplication([])
    apply_theme(app)
    return app


def _service_bundle(services):
    from types import SimpleNamespace
    return SimpleNamespace(catalog=services["catalog"], commands=services["commands"])


def test_catalog_dialog_lists_and_edits(qapp, services, monkeypatch):
    from app.ui import catalog_dialog as cd
    dialog = cd.CatalogDialog(_service_bundle(services), ADMIN)
    assert dialog.table.rowCount() == 4
    assert dialog.table.item(0, 3).text() == "R$ 79,90/kg" and dialog.table.item(1, 3).text() == "R$ 8,00"
    assert not dialog.price_btn.isEnabled()                        # nada selecionado

    changes = []
    dialog.changed.connect(lambda: changes.append(1))

    def fake_form(name=None, price=None):
        def exec_(self):
            self.value_name, self.value_price = name, (Decimal(price) if price else None)
            return self.DialogCode.Accepted
        monkeypatch.setattr(cd.ProductFormDialog, "exec", exec_)

    fake_form(name="Suco", price="7.00")
    dialog._create()                                                # novo produto
    assert dialog.table.rowCount() == 5 and dialog.table.item(4, 1).text() == "SUCO"
    assert dialog.table.item(4, 3).text() == "R$ 7,00" and changes == [1]

    dialog.table.selectRow(4)
    fake_form(price="7.50")
    dialog._price()
    assert dialog.table.item(4, 3).text() == "R$ 7,50"
    fake_form(name="Suco natural")
    dialog._rename()
    assert dialog.table.item(4, 1).text() == "SUCO NATURAL"
    monkeypatch.setattr(cd.QMessageBox, "question", lambda *a, **k: cd.QMessageBox.StandardButton.Yes)
    dialog._toggle()
    assert dialog.table.item(4, 4).text() == "Desativado" and dialog.toggle_btn.text() == "Ativar"
    assert "SUCO NATURAL" not in [p.description for p in services["commands"].unit_products()]
    dialog.table.selectRow(0)
    assert not dialog.toggle_btn.isEnabled()                        # comida por kg não desativa


def test_catalog_dialog_shows_server_errors(qapp, services, monkeypatch):
    from app.ui import catalog_dialog as cd
    shown = []
    monkeypatch.setattr(cd.QMessageBox, "warning", lambda *a: shown.append(a[2]))
    dialog = cd.CatalogDialog(_service_bundle(services), ADMIN)

    def exec_(self):
        self.value_name, self.value_price = "REFRIGERANTE", Decimal("5")
        return self.DialogCode.Accepted
    monkeypatch.setattr(cd.ProductFormDialog, "exec", exec_)
    dialog._create()
    assert shown and "Já existe" in shown[0] and dialog.table.rowCount() == 4


def test_catalog_dialog_refuses_wrong_pin(qapp, services):
    from app.ui import catalog_dialog as cd
    with pytest.raises(errors.NotAuthorized):
        cd.CatalogDialog(_service_bundle(services), "0000")


def test_operator_catalog_button_updates_screen_products(qapp, tmp_path, monkeypatch):
    from app.bootstrap import build_services
    from app.config.settings import AppSettings
    from app.ui import main_window as mw
    monkeypatch.setenv("BALANCA_HOME", str(tmp_path))
    settings = AppSettings(database_url=f"sqlite:///{tmp_path / 'op.db'}")
    services = build_services(settings)
    operator = services.auth.authenticate(services.auth.list_operators()[0].id, "1111") \
        or services.auth.list_operators()[0]
    win = mw.MainWindow(settings, services, operator)
    assert len(win.product_buttons) == 3
    services.catalog.create_product(ADMIN, "Suco", Decimal("7"))       # outro terminal/gerente cadastrou
    win._after_command_loaded() if win.command else None
    win.command = services.commands.find("000155")
    win._after_command_loaded()                                        # ler uma comanda recarrega
    assert len(win.product_buttons) == 4 and "SUCO" in win.product_buttons[-1].text()
    win.close()
    services.db.dispose()

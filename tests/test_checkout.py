"""Comanda criada pelo sistema, CPF, envio ao caixa e pagamentos."""
from decimal import Decimal
from threading import Thread

import pytest

from app.database.connection import Database
from app.domain.cpf import format_cpf, is_valid_cpf, mask_cpf
from app.payments.gateway import SimulatedTefGateway, build_gateway
from app.services.command_service import CommandService
from app.services.errors import (BusinessError, CommandClosed, DuplicateOpenCommand, InvalidCpf,
                                 PaymentError)
from app.services.pricing_service import PricingService

CPF_A = "529.982.247-25"      # CPFs válidos de exemplo
CPF_B = "111.444.777-35"


# ---- CPF --------------------------------------------------------------------
@pytest.mark.parametrize("cpf,ok", [(CPF_A, True), ("52998224725", True), (CPF_B, True),
                                    ("529.982.247-24", False), ("111.111.111-11", False),
                                    ("123", False), ("", False), ("abcdefghijk", False)])
def test_cpf_validation(cpf, ok):
    assert is_valid_cpf(cpf) is ok


def test_cpf_formatting_and_masking():
    assert format_cpf("52998224725") == "529.982.247-25"
    assert mask_cpf("52998224725") == "***.982.247-**"
    assert "529" not in mask_cpf(CPF_A)


# ---- criar comanda ----------------------------------------------------------
def test_start_command_sequential_codes_and_cpf(services, selfservice):
    cmds = services["commands"]
    first = cmds.start_command(selfservice.id, CPF_A)
    second = cmds.start_command(selfservice.id, CPF_B)
    assert first.status == "OPEN" and first.customer_cpf == "52998224725"
    assert int(second.code) == int(first.code) + 1
    assert first.code == "000157"                    # depois das comandas do seed (000154-000156)


def test_start_command_rejects_invalid_cpf(services, selfservice):
    with pytest.raises(InvalidCpf):
        services["commands"].start_command(selfservice.id, "123.456.789-00")


def test_one_open_command_per_cpf_and_lookup(services, selfservice):
    cmds = services["commands"]
    first = cmds.start_command(selfservice.id, CPF_A)
    with pytest.raises(DuplicateOpenCommand) as exc:
        cmds.start_command(selfservice.id, "529.982.247-25")
    assert exc.value.existing_code == first.code
    found = cmds.open_commands_by_cpf(CPF_A)
    assert [c.code for c in found] == [first.code]
    assert cmds.open_commands_by_cpf(CPF_B) == []
    cmds.cancel_command(first.id, selfservice.id, only_if_empty=True)      # libera o CPF
    assert cmds.open_commands_by_cpf(CPF_A) == []
    assert cmds.start_command(selfservice.id, CPF_A).code != first.code


def test_command_without_cpf_allowed(services, selfservice):
    info = services["commands"].start_command(selfservice.id)
    assert info.customer_cpf is None


def test_concurrent_start_gives_unique_codes(tmp_path):
    db = Database(f"sqlite:///{tmp_path / 'c.db'}")
    db.create_all()
    from app.database.seed import seed_if_empty
    from app.services.auth_service import AuthService
    seed_if_empty(db)
    op = AuthService(db).self_service_operator()
    cmds = CommandService(db, PricingService(db))
    codes, errors = [], []

    def worker():
        try:
            for _ in range(5):
                codes.append(cmds.start_command(op.id).code)
        except Exception as exc:          # SQLite pode recusar por lock; o que não pode é duplicar
            errors.append(exc)

    threads = [Thread(target=worker) for _ in range(4)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert len(codes) == len(set(codes))
    db.dispose()


# ---- dois "PCs": dois motores de banco independentes sobre o mesmo arquivo ---------------
def test_two_stations_share_data(tmp_path):
    url = f"sqlite:///{tmp_path / 'shared.db'}"
    from app.database.seed import seed_if_empty
    from app.services.auth_service import AuthService
    pc1, pc2 = Database(url), Database(url)
    pc1.create_all()
    seed_if_empty(pc1)
    kiosk = CommandService(pc1, PricingService(pc1))
    cashier = CommandService(pc2, PricingService(pc2))
    op = AuthService(pc1).self_service_operator()
    cash_op = AuthService(pc2).list_operators()[0]

    comanda = kiosk.start_command(op.id, CPF_A)                         # PC 1: cliente abre comanda
    kiosk.add_weighed_consumption(comanda.id, op.id, Decimal("0.500"))  # PC 1: pesa o prato
    kiosk.add_unit_product(comanda.id, op.id, "003", 2)                 # PC 1: 2 águas
    seen = cashier.find(comanda.code)                                   # PC 2: lê a comanda
    assert seen.total == Decimal("47.95")
    lost = cashier.open_commands_by_cpf(CPF_A)                          # PC 2: achou pelo CPF
    assert lost[0].code == comanda.code
    paid = cashier.register_payment(comanda.id, cash_op.id, "PIX", seen.total, reference="E123")
    assert paid.status == "PAID"
    with pytest.raises(CommandClosed):                                  # PC 1 já não consegue lançar
        kiosk.add_unit_product(comanda.id, op.id, "003")
    pc1.dispose()
    pc2.dispose()


# ---- ciclo: enviar ao caixa / reabrir / cancelar -------------------------------------------
def test_send_to_payment_requires_items(services, selfservice):
    cmds = services["commands"]
    empty = cmds.start_command(selfservice.id)
    with pytest.raises(BusinessError):
        cmds.send_to_payment(empty.id)


def test_awaiting_payment_list_and_reopen(services, selfservice):
    cmds = services["commands"]
    assert cmds.list_awaiting_payment() == []
    c154 = cmds.find("000154")
    cmds.send_to_payment(c154.id)
    listed = cmds.list_awaiting_payment()
    assert [(c.code, c.total, c.item_count) for c in listed] == [("000154", Decimal("20.00"), 2)]
    assert cmds.reopen_command(c154.id).status == "OPEN"
    assert cmds.list_awaiting_payment() == []


def test_cannot_reopen_after_partial_payment(services, operator):
    cmds = services["commands"]
    c = cmds.find("000154")
    cmds.send_to_payment(c.id)
    cmds.register_payment(c.id, operator.id, "CASH", Decimal("5.00"))
    with pytest.raises(BusinessError):
        cmds.reopen_command(c.id)


def test_cancel_command_with_items_needs_reason(services, operator):
    cmds = services["commands"]
    c = cmds.find("000154")
    with pytest.raises(BusinessError):
        cmds.cancel_command(c.id, operator.id, only_if_empty=True)
    with pytest.raises(BusinessError):
        cmds.cancel_command(c.id, operator.id, "")
    cmds.cancel_command(c.id, operator.id, "Cliente saiu sem consumir")
    after = cmds.get(c.id)
    assert after.status == "CANCELLED" and after.total == Decimal("0.00")
    assert all(i.status == "CANCELLED" for i in after.items)


# ---- pagamentos ---------------------------------------------------------------------------
def test_cash_with_change_pays_off(services, operator):
    cmds = services["commands"]
    c = cmds.find("000154")                                   # R$ 20,00, ainda OPEN
    paid = cmds.register_payment(c.id, operator.id, "CASH", Decimal("20.00"), tendered=Decimal("50"))
    assert paid.status == "PAID" and paid.remaining == Decimal("0.00")
    assert paid.payments[0].change == Decimal("30.00")


def test_first_payment_locks_open_command(services, operator):
    cmds = services["commands"]
    c = cmds.find("000154")
    part = cmds.register_payment(c.id, operator.id, "DEBIT", Decimal("5.00"), reference="NSU1")
    assert part.status == "AWAITING_PAYMENT" and part.remaining == Decimal("15.00")
    with pytest.raises(CommandClosed):
        cmds.add_unit_product(c.id, operator.id, "003")


def test_split_payment_across_methods(services, operator):
    cmds = services["commands"]
    c = cmds.find("000154")
    cmds.register_payment(c.id, operator.id, "CASH", Decimal("8.00"))
    done = cmds.register_payment(c.id, operator.id, "CREDIT", Decimal("12.00"), reference="NSU2")
    assert done.status == "PAID"
    assert [p.method for p in done.payments] == ["CASH", "CREDIT"]
    assert done.paid == Decimal("20.00")


@pytest.mark.parametrize("kwargs,message", [
    ({"method": "CASH", "amount": Decimal("0")}, "maior que zero"),
    ({"method": "CASH", "amount": Decimal("25.00")}, "excede"),
    ({"method": "CASH", "amount": Decimal("20.00"), "tendered": Decimal("10")}, "menor"),
    ({"method": "CHEQUE", "amount": Decimal("5")}, "inválida"),
])
def test_payment_validation(services, operator, kwargs, message):
    c = services["commands"].find("000154")
    with pytest.raises(PaymentError, match=message):
        services["commands"].register_payment(c.id, operator.id, **kwargs)
    assert services["commands"].get(c.id).paid == Decimal("0.00")     # nada foi gravado


def test_cannot_pay_twice_or_cancelled(services, operator):
    cmds = services["commands"]
    paid = cmds.find("000156")                                # PAID no seed
    with pytest.raises(PaymentError, match="já está paga"):
        cmds.register_payment(paid.id, operator.id, "CASH", Decimal("1"))
    c = cmds.find("000155")                                   # vazia
    with pytest.raises(PaymentError, match="sem itens|não possui itens"):
        cmds.register_payment(c.id, operator.id, "CASH", Decimal("1"))


def test_self_service_operator_hidden_from_login(services):
    ops = [o.name for o in services["auth"].list_operators()]
    assert "Autoatendimento" not in ops
    info = services["auth"].self_service_operator()
    assert services["auth"].self_service_operator().id == info.id       # idempotente
    assert services["auth"].authenticate(info.id, "") is None


# ---- gateway TEF ----------------------------------------------------------------------------
def test_simulated_gateway_approves_and_declines():
    gw = SimulatedTefGateway(delay_s=0)
    ok = gw.charge("CREDIT", Decimal("10"))
    assert ok.approved and ok.reference.startswith("SIM")
    gw.decline_next = True
    assert not gw.charge("CREDIT", Decimal("10")).approved
    assert gw.charge("CREDIT", Decimal("10")).approved         # só a próxima é recusada


def test_real_tef_not_implemented_but_explicit():
    with pytest.raises(NotImplementedError):
        build_gateway("tef").charge("CREDIT", Decimal("1"))
    with pytest.raises(ValueError):
        build_gateway("xyz")


# ---- migração de banco antigo ------------------------------------------------------------------
def test_migration_adds_cpf_column_to_old_database(tmp_path):
    from sqlalchemy import create_engine, inspect, text
    url = f"sqlite:///{tmp_path / 'old.db'}"
    engine = create_engine(url)
    with engine.begin() as conn:      # esquema da v1: sem customer_cpf
        conn.execute(text("CREATE TABLE command (id INTEGER PRIMARY KEY, code VARCHAR(20) UNIQUE, "
                          "status VARCHAR(9), opened_at DATETIME, closed_at DATETIME, "
                          "created_at DATETIME, updated_at DATETIME)"))
    engine.dispose()
    db = Database(url)
    db.create_all()
    cols = {c["name"] for c in inspect(db.engine).get_columns("command")}
    assert "customer_cpf" in cols
    db.create_all()                   # idempotente
    db.dispose()

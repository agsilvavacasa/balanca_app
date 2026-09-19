"""Terminais falam com o servidor pela rede (HTTP em localhost), como dois PCs."""
from datetime import datetime
from decimal import Decimal

import pytest

from app.bootstrap import build_services
from app.config.settings import AppSettings
from app.net import protocol
from app.net.client import (RemoteClient, ServerRejected, ServerUnavailable, build_remote_services)
from app.net.server import ServerHost, local_ips, new_access_key
from app.services import dto, errors

CPF = "529.982.247-25"
KEY = "TESTE234"


@pytest.fixture
def server(tmp_path):
    settings = AppSettings(database_url=f"sqlite:///{tmp_path / 'srv.db'}")
    local = build_services(settings)
    host = ServerHost(local, KEY, host="127.0.0.1", port=0, name="Caixa")
    host.start()
    yield host, local
    host.stop()
    local.db.dispose()


def remote(host, key=KEY, name="Autoatendimento"):
    return build_remote_services("127.0.0.1", host.port, key, name)


# ---- codec --------------------------------------------------------------------------------
def test_codec_roundtrips_dtos_decimals_dates_and_tuples():
    now = datetime(2026, 9, 18, 14, 38, 5)
    item = dto.ItemInfo(1, "COMIDA POR KG", "WEIGHT", Decimal("1"), Decimal("0.500"), Decimal("79.90"),
                        Decimal("39.95"), "ACTIVE", now, "Op")
    pay = dto.PaymentInfo(1, "CASH", Decimal("20.00"), Decimal("50"), Decimal("30.00"), None, now, "Caixa")
    info = dto.CommandInfo(7, "000157", "OPEN", Decimal("39.95"), (item,), Decimal("0.00"), (pay,),
                           "52998224725", now)
    back = protocol.loads(protocol.dumps({"a": [info], "b": Decimal("1.10")}))
    assert back["a"][0] == info and back["b"] == Decimal("1.10")
    assert isinstance(back["a"][0].items, tuple) and back["a"][0].remaining == info.remaining
    assert isinstance(back["a"][0].items[0].weight_kg, Decimal)


def test_codec_rejects_float_and_unknown_types():
    with pytest.raises(TypeError):
        protocol.dumps(0.1)
    with pytest.raises(TypeError):
        protocol.dumps(object())


# ---- ida e volta pela rede ------------------------------------------------------------------
def test_full_flow_over_the_network(server):
    host, local = server
    terminal = remote(host)
    op = terminal.auth.self_service_operator()
    assert op.name == "Autoatendimento"

    created = terminal.commands.start_command(op.id, CPF)                   # terminal cria a comanda
    terminal.commands.add_weighed_consumption(created.id, op.id, Decimal("0.500"), 360, "02 30 30")
    terminal.commands.add_unit_product(created.id, op.id, "002", 2)
    assert terminal.pricing.current_price("001") == Decimal("79.90")
    assert [p.description for p in terminal.commands.unit_products()][0] == "REFRIGERANTE"

    seen = local.commands.find(created.code)                                # o servidor enxerga na hora
    assert seen.total == Decimal("55.95") and seen.customer_cpf == "52998224725"

    cashier = remote(host, name="Caixa")                                    # outro terminal (caixa)
    found = cashier.commands.open_commands_by_cpf(CPF)
    assert found[0].code == created.code
    paid = cashier.commands.register_payment(created.id, op.id, "CASH", Decimal("55.95"), Decimal("100"))
    assert paid.status == "PAID" and paid.payments[0].change == Decimal("44.05")
    assert local.commands.find(created.code).status == "PAID"


def test_business_errors_keep_their_type_and_message(server):
    host, _ = server
    terminal = remote(host)
    op = terminal.auth.self_service_operator()
    with pytest.raises(errors.CommandNotFound, match="999999"):
        terminal.commands.find("999999")
    with pytest.raises(errors.InvalidCpf):
        terminal.commands.start_command(op.id, "123.456.789-00")
    first = terminal.commands.start_command(op.id, CPF)
    terminal.commands.add_unit_product(first.id, op.id, "002")             # R$ 8,00
    with pytest.raises(errors.DuplicateOpenCommand) as exc:
        terminal.commands.start_command(op.id, CPF)
    assert exc.value.existing_code == first.code
    with pytest.raises(errors.PaymentError, match="excede"):
        terminal.commands.register_payment(first.id, op.id, "CASH", Decimal("50"))
    with pytest.raises(errors.PaymentError, match="inválida"):
        terminal.commands.register_payment(first.id, op.id, "CHEQUE", Decimal("5"))


def test_wrong_access_key_is_rejected(server):
    host, _ = server
    with pytest.raises(ServerRejected):
        build_remote_services("127.0.0.1", host.port, "ERRADO", "Invasor")
    assert any("Recusado" in e for e in host.events)


def test_unknown_or_private_methods_are_blocked(server):
    host, _ = server
    client = RemoteClient("127.0.0.1", host.port, KEY)
    for service, method in (("commands", "_load"), ("commands", "__init__"), ("db", "dispose"),
                            ("auth", "verify_pin"), ("commands", "nao_existe")):
        with pytest.raises(errors.BusinessError):
            client.call(service, method, (), {})


def test_server_down_gives_friendly_error(server):
    host, _ = server
    port = host.port
    host.stop()
    with pytest.raises(ServerUnavailable, match="Sem conexão"):
        build_remote_services("127.0.0.1", port, KEY, "X")


def test_server_lists_connected_clients(server):
    host, _ = server
    remote(host, name="Autoatendimento")
    remote(host, name="Caixa")
    remote(host, name="Autoatendimento 2")                              # segundo kiosk
    names = [c.name for c in host.active_clients()]
    assert names == ["Autoatendimento", "Autoatendimento 2", "Caixa"]   # todos aparecem, mesmo do mesmo IP
    assert all(c.requests >= 1 for c in host.active_clients())
    assert any("Conectou" in e for e in host.events)


def test_two_kiosks_and_a_cashier_at_once(server):
    """Dois autoatendimentos criando comandas e o caixa cobrando, ao mesmo tempo."""
    from threading import Thread
    host, local = server
    results = {}

    def kiosk(name, cpf):
        t = remote(host, name=name)
        op = t.auth.self_service_operator()
        c = t.commands.start_command(op.id, cpf)
        t.commands.add_weighed_consumption(c.id, op.id, Decimal("0.400"), 360)
        t.commands.add_unit_product(c.id, op.id, "003")
        results[name] = t.commands.get(c.id)

    threads = [Thread(target=kiosk, args=("Kiosk A", "529.982.247-25")),
               Thread(target=kiosk, args=("Kiosk B", "111.444.777-35"))]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert {r.code for r in results.values()} != {None} and len({r.code for r in results.values()}) == 2
    assert all(r.total == Decimal("35.96") for r in results.values())      # 0,400 x 79,90 + 4,00
    cashier = remote(host, name="Caixa")
    for cpf, name in (("529.982.247-25", "Kiosk A"), ("111.444.777-35", "Kiosk B")):
        found = cashier.commands.open_commands_by_cpf(cpf)[0]
        assert found.code == results[name].code                            # cada CPF acha a sua comanda


def test_concurrent_terminals_get_distinct_codes(server):
    from threading import Thread
    host, _ = server
    codes, errs = [], []

    def worker(name):
        try:
            t = remote(host, name=name)
            op = t.auth.self_service_operator()
            for _ in range(3):
                codes.append(t.commands.start_command(op.id).code)
        except Exception as exc:
            errs.append(exc)

    threads = [Thread(target=worker, args=(f"T{i}",)) for i in range(4)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert not errs and len(codes) == 12 and len(set(codes)) == 12


def test_helpers():
    key = new_access_key()
    assert len(key) == 8 and not set(key) & set("01OIl")
    assert new_access_key() != new_access_key()
    assert local_ips()


def test_allow_duplicate_cpf_flag_travels_over_the_network(server):
    host, _ = server
    terminal = remote(host)
    op = terminal.auth.self_service_operator()
    first = terminal.commands.start_command(op.id, CPF)
    with pytest.raises(errors.DuplicateOpenCommand):
        terminal.commands.start_command(op.id, CPF)
    second = terminal.commands.start_command(op.id, CPF, allow_duplicate_cpf=True)
    assert second.code != first.code

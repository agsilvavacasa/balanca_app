from decimal import Decimal

import pytest

from app.domain.money import calculate_total, format_brl, format_kg, to_decimal
from app.hardware.scale import ScaleReading, WeightStatus
from app.services.command_service import normalize_code
from app.services.errors import (BusinessError, CommandClosed, CommandNotFound, InvalidWeight,
                                 PriceNotFound)
from app.services.weighing_service import StabilityTracker, WeighingState


# ---- dinheiro ---------------------------------------------------------------
def test_document_calculation():
    assert calculate_total(Decimal("0.500"), Decimal("79.90")) == Decimal("39.95")


def test_rn003_rounding_half_up():
    assert calculate_total(Decimal("0.333"), Decimal("79.90")) == Decimal("26.61")
    # meio centavo exato sobe (ROUND_HALF_EVEN daria 0.12)
    assert calculate_total(Decimal("0.005"), Decimal("25.00")) == Decimal("0.13")


def test_float_is_rejected():
    with pytest.raises(TypeError):
        to_decimal(79.9)
    assert to_decimal("79,90") == Decimal("79.90")


def test_formatting():
    assert format_brl(Decimal("1234.5")) == "R$ 1.234,50"
    assert format_kg(Decimal("0.5")) == "0,500 kg"


# ---- comanda ----------------------------------------------------------------
@pytest.mark.parametrize("raw,expected", [("000154", "000154"), ("154", "000154"),
                                          ("COMANDA: 000154\r\n", "000154"), ("", "")])
def test_normalize_code(raw, expected):
    assert normalize_code(raw) == expected


def test_seed_matches_document_example(services):
    info = services["commands"].find("000154")
    assert info.status == "OPEN"
    assert info.total == Decimal("20.00")
    assert [i.description for i in info.items] == ["REFRIGERANTE", "SOBREMESA"]


def test_unknown_and_closed_commands(services, operator):
    cmds = services["commands"]
    with pytest.raises(CommandNotFound):
        cmds.find("999999")
    closed = cmds.find("000156")
    assert closed.status == "PAID"
    with pytest.raises(CommandClosed):
        cmds.add_weighed_consumption(closed.id, operator.id, Decimal("0.5"))
    with pytest.raises(CommandClosed):
        cmds.add_unit_product(closed.id, operator.id, "002")


def test_weighed_consumption_recomputed_and_stored(services, operator):
    cmds = services["commands"]
    command = cmds.find("000154")
    item = cmds.add_weighed_consumption(command.id, operator.id, Decimal("0.500"),
                                        tare_g=360, raw_response="02 30 30 35 30 30 03")
    assert item.total_price == Decimal("39.95")
    after = cmds.find("000154")
    assert after.total == Decimal("59.95")      # 8,00 + 12,00 + 39,95 (exemplo da seção 5)
    with services["db"].session() as s:
        from app.database.models import Weighing
        w = s.query(Weighing).one()
        assert (w.gross_weight_kg, w.tare_weight_kg, w.net_weight_kg) == (
            Decimal("0.860"), Decimal("0.360"), Decimal("0.500"))
        assert w.raw_response == "02 30 30 35 30 30 03"


def test_invalid_weight_rejected(services, operator):
    command = services["commands"].find("000155")
    for bad in (Decimal("0"), Decimal("-0.1"), None):
        with pytest.raises(InvalidWeight):
            services["commands"].add_weighed_consumption(command.id, operator.id, bad)


def test_price_change_does_not_alter_past_consumptions(services, operator):
    cmds, pricing = services["commands"], services["pricing"]
    command = cmds.find("000155")
    cmds.add_weighed_consumption(command.id, operator.id, Decimal("0.500"))
    pricing.set_price("001", Decimal("89.90"), operator.id)
    assert pricing.current_price("001") == Decimal("89.90")
    item = cmds.find("000155").items[0]
    assert item.unit_price == Decimal("79.90") and item.total_price == Decimal("39.95")
    new_item = cmds.add_weighed_consumption(command.id, operator.id, Decimal("0.500"))
    assert new_item.total_price == Decimal("44.95")


def test_price_validation(services, operator):
    with pytest.raises(BusinessError):
        services["pricing"].set_price("001", Decimal("0"), operator.id)
    with pytest.raises(PriceNotFound):
        services["pricing"].current_price("999")


def test_cancel_keeps_record_and_updates_total(services, operator):
    cmds = services["commands"]
    command = cmds.find("000154")
    refri = command.items[0]
    with pytest.raises(BusinessError):
        cmds.cancel_consumption(refri.id, operator.id, " ")
    cmds.cancel_consumption(refri.id, operator.id, "Lançado por engano")
    after = cmds.find("000154")
    assert after.total == Decimal("12.00")
    cancelled = after.items[0]
    assert cancelled.status == "CANCELLED" and cancelled.cancel_reason == "Lançado por engano"
    with pytest.raises(BusinessError):
        cmds.cancel_consumption(refri.id, operator.id, "de novo")


def test_send_to_payment_blocks_new_items(services, operator):
    cmds = services["commands"]
    command = cmds.find("000154")
    assert cmds.send_to_payment(command.id).status == "AWAITING_PAYMENT"
    with pytest.raises(CommandClosed):
        cmds.add_unit_product(command.id, operator.id, "003")


# ---- autenticação -----------------------------------------------------------
def test_auth(services):
    auth = services["auth"]
    ops = {o.name: o for o in auth.list_operators()}
    assert auth.authenticate(ops["Operador 1"].id, "0000") is None
    assert auth.authenticate_admin("1111") is None       # operador comum não autoriza
    assert auth.authenticate_admin("9999").name == "Gerente"


# ---- estabilidade -----------------------------------------------------------
def _ok(kg):
    return ScaleReading(WeightStatus.OK, Decimal(kg))


def test_stability_requires_three_equal_reads():
    t = StabilityTracker(required=3)
    assert t.evaluate(_ok("0.500"))[0] is WeighingState.SETTLING
    assert t.evaluate(_ok("0.500"))[0] is WeighingState.SETTLING
    assert t.evaluate(_ok("0.500"))[0] is WeighingState.STABLE
    assert t.evaluate(_ok("0.502"))[0] is WeighingState.SETTLING      # mudou: desestabiliza


def test_stability_states():
    t = StabilityTracker(required=2, capacity_kg=Decimal("32"))
    assert t.evaluate(None)[0] is WeighingState.NO_SCALE
    assert t.evaluate(_ok("0.000"))[0] is WeighingState.EMPTY
    assert t.evaluate(ScaleReading(WeightStatus.UNSTABLE, None))[0] is WeighingState.SETTLING
    assert t.evaluate(ScaleReading(WeightStatus.NEGATIVE, None))[0] is WeighingState.NEGATIVE
    assert t.evaluate(ScaleReading(WeightStatus.OVERLOAD, None))[0] is WeighingState.OVERLOAD
    assert t.evaluate(_ok("32.010"))[0] is WeighingState.OVERLOAD


def test_instability_resets_streak():
    t = StabilityTracker(required=2)
    t.evaluate(_ok("1.000"))
    t.evaluate(ScaleReading(WeightStatus.UNSTABLE, None))
    assert t.evaluate(_ok("1.000"))[0] is WeighingState.SETTLING

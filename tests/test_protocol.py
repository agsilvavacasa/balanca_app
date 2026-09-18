from decimal import Decimal

import pytest

from app.hardware import prt5
from app.hardware.prix3fit import ToledoPrix3Fit
from app.hardware.scale import (ScaleNotConnected, ScaleProtocolError, ScaleTimeout,
                                WeightStatus)
from app.hardware.simulator import SimulatedSerial


# Exemplos literais do manual (MU-3-Fit, págs. 15-16) --------------------------
def test_manual_weight_example_14_385():
    reading = prt5.parse_weight_response(b"\x0214385\x03")
    assert reading.status is WeightStatus.OK
    assert reading.weight_kg == Decimal("14.385")


def test_document_example_bytes_0_500():
    reading = prt5.parse_weight_response(bytes.fromhex("02 30 30 35 30 30 03"))
    assert reading.weight_kg == Decimal("0.500")
    assert reading.raw_hex == "02 30 30 35 30 30 03"


def test_manual_price_example_16_58():
    assert prt5.build_price_frame(Decimal("16.58")) == b"\x02001658\x03"


def test_price_79_90():
    assert prt5.build_price_frame(Decimal("79.90")) == b"\x02007990\x03"


def test_manual_tare_example_360g():
    frame = prt5.build_tare_frame(360)
    assert frame == b"\x01000360\x03"
    assert frame.hex(" ") == "01 30 30 30 33 36 30 03"


def test_nack_is_0x21():
    assert prt5.NACK == b"\x21"
    assert prt5.parse_ack(b"\x06") is True
    assert prt5.parse_ack(b"\x21") is False
    with pytest.raises(ScaleProtocolError):
        prt5.parse_ack(b"\x15")   # NAK "clássico" não é o que o manual define


@pytest.mark.parametrize("payload,status", [
    ("IIIII", WeightStatus.UNSTABLE), ("NNNNN", WeightStatus.NEGATIVE),
    ("SSSSS", WeightStatus.OVERLOAD)])
def test_special_states(payload, status):
    reading = prt5.parse_weight_response(b"\x02" + payload.encode() + b"\x03")
    assert reading.status is status
    assert reading.weight_kg is None


@pytest.mark.parametrize("bad", [b"", b"\x0200500", b"00500\x03", b"\x021234\x03",
                                 b"\x02ABCDE\x03", b"\x02123456\x03"])
def test_invalid_frames_raise(bad):
    with pytest.raises(ScaleProtocolError):
        prt5.parse_weight_response(bad)


def test_noise_before_stx_is_discarded():
    assert prt5.parse_weight_response(b"\x00\xff\x0200500\x03").weight_kg == Decimal("0.500")


def test_weight_is_decimal_not_float():
    assert isinstance(prt5.parse_weight_response(b"\x0200500\x03").weight_kg, Decimal)


def test_frame_builders_reject_out_of_range():
    with pytest.raises(ValueError):
        prt5.build_price_frame(Decimal("10000"))
    with pytest.raises(ValueError):
        prt5.build_tare_frame(-1)
    with pytest.raises(TypeError):
        prt5.build_tare_frame(0.36)


# Driver sobre a balança simulada ---------------------------------------------
@pytest.fixture
def scale():
    sim = SimulatedSerial()
    driver = ToledoPrix3Fit(lambda: sim)
    driver.connect()
    driver.sim = sim
    return driver


def test_driver_reads_weight(scale):
    scale.sim.place_weight(500)
    reading = scale.get_weight()
    assert reading.weight_kg == Decimal("0.500")


def test_driver_tare_flow_matches_document_example(scale):
    """Prato 360 g + comida = 860 g bruto -> 0,500 kg líquido."""
    scale.sim.place_weight(860)
    assert scale.set_tare(360) is True
    assert scale.get_weight().weight_kg == Decimal("0.500")


def test_driver_physical_tare_key(scale):
    scale.sim.place_weight(360)
    scale.sim.press_tare_key()
    scale.sim.place_weight(860)
    assert scale.get_weight().weight_kg == Decimal("0.500")


def test_driver_negative_after_plate_removed(scale):
    scale.sim.place_weight(360)
    scale.set_tare(360)
    scale.sim.place_weight(0)
    assert scale.get_weight().status is WeightStatus.NEGATIVE


def test_driver_unstable_and_overload(scale):
    scale.sim.unstable = True
    assert scale.get_weight().status is WeightStatus.UNSTABLE
    scale.sim.unstable = False
    scale.sim.place_weight(33_000)
    assert scale.get_weight().status is WeightStatus.OVERLOAD


def test_driver_price_ack_and_tare_nack(scale):
    assert scale.set_price_per_kg(Decimal("79.90")) is True
    assert scale.sim.price_per_kg == Decimal("79.90")
    assert scale.set_tare(40_000) is False      # acima da capacidade -> NACK


def test_resolution_bands(scale):
    scale.sim.place_weight(501)       # até 6 kg: passo de 2 g
    assert scale.get_weight().weight_kg == Decimal("0.502")
    scale.sim.place_weight(10_003)    # até 15 kg: passo de 5 g
    assert scale.get_weight().weight_kg == Decimal("10.005")
    scale.sim.place_weight(20_004)    # até 32 kg: passo de 10 g
    assert scale.get_weight().weight_kg == Decimal("20.000")


def test_driver_requires_connection():
    driver = ToledoPrix3Fit(SimulatedSerial)
    with pytest.raises(ScaleNotConnected):
        driver.get_weight()


def test_driver_timeout_when_scale_silent():
    class Silent(SimulatedSerial):
        def write(self, data):
            return len(data)
    driver = ToledoPrix3Fit(Silent)
    driver.connect()
    with pytest.raises(ScaleTimeout):
        driver.get_weight()
    with pytest.raises(ScaleTimeout):
        driver.set_tare(360)

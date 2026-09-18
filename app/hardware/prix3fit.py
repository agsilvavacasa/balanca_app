"""Driver da Toledo Prix 3 Fit sobre uma porta serial (ou compatível)."""
from decimal import Decimal
from typing import Callable, Optional

from . import prt5
from .scale import (Scale, ScaleNotConnected, ScaleReading, ScaleTimeout)

# Fábrica de "porta": devolve um objeto com a API do pyserial.Serial
# (write, read, read_until, reset_input_buffer, close, is_open).
SerialFactory = Callable[[], object]


def pyserial_factory(port: str, baudrate: int, data_bits: int = 8,
                     parity: str = "N", stop_bits: int = 1, timeout: float = 1.0) -> SerialFactory:
    def factory():
        import serial  # import tardio: o app abre em modo simulado sem hardware
        return serial.Serial(
            port=port,
            baudrate=baudrate,
            bytesize={7: serial.SEVENBITS, 8: serial.EIGHTBITS}[data_bits],
            parity={"N": serial.PARITY_NONE, "E": serial.PARITY_EVEN}[parity],
            stopbits=serial.STOPBITS_ONE if stop_bits == 1 else serial.STOPBITS_TWO,
            timeout=timeout,
        )
    return factory


class ToledoPrix3Fit(Scale):
    def __init__(self, serial_factory: SerialFactory):
        self._factory = serial_factory
        self._port: Optional[object] = None

    def connect(self) -> None:
        if self._port is None:
            self._port = self._factory()

    def disconnect(self) -> None:
        if self._port is not None:
            try:
                self._port.close()
            finally:
                self._port = None

    def is_connected(self) -> bool:
        return self._port is not None and getattr(self._port, "is_open", True)

    def _require_port(self):
        if not self.is_connected():
            raise ScaleNotConnected("Balança não conectada")
        return self._port

    def get_weight(self) -> ScaleReading:
        port = self._require_port()
        port.reset_input_buffer()
        port.write(prt5.build_weight_request())
        response = port.read_until(prt5.ETX)
        if not response:
            raise ScaleTimeout("A balança não respondeu ao ENQ")
        return prt5.parse_weight_response(response)

    def _write_and_ack(self, frame: bytes) -> bool:
        port = self._require_port()
        port.reset_input_buffer()
        port.write(frame)
        answer = port.read(1)
        if not answer:
            raise ScaleTimeout("A balança não confirmou o comando (ACK/NACK)")
        return prt5.parse_ack(answer)

    def set_tare(self, grams: int) -> bool:
        return self._write_and_ack(prt5.build_tare_frame(grams))

    def set_price_per_kg(self, price: Decimal) -> bool:
        return self._write_and_ack(prt5.build_price_frame(price))

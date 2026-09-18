"""Balança simulada que fala Prt5 byte a byte.

Implementa só o que o driver usa da API do pyserial, então o ToledoPrix3Fit roda
sobre ela sem nenhuma alteração: o protocolo real é exercitado mesmo sem hardware.
"""
import threading
from decimal import Decimal

from . import prt5

CAPACITY_G = 32_000


def _resolution(grams: int) -> int:
    """Faixas da Prix 3 Fit: 2 g até 6 kg, 5 g até 15 kg, 10 g até 32 kg."""
    if grams <= 6_000:
        return 2
    if grams <= 15_000:
        return 5
    return 10


class SimulatedSerial:
    def __init__(self):
        self._lock = threading.Lock()
        self._rx = bytearray()      # bytes que a "balança" devolve ao PC
        self.is_open = True
        self.gross_g = 0            # peso físico sobre o prato
        self.tare_g = 0             # tara memorizada
        self.unstable = False
        self.price_per_kg = Decimal("0")

    # ---- controles do simulador (usados pela interface) ---------------------
    def place_weight(self, grams: int) -> None:
        self.gross_g = max(0, int(grams))

    def press_tare_key(self) -> None:
        """Equivale a apertar a tecla de tara na balança (opção A do documento)."""
        self.tare_g = self.gross_g

    # ---- API estilo pyserial -----------------------------------------------
    def reset_input_buffer(self) -> None:
        with self._lock:
            self._rx.clear()

    def write(self, data: bytes) -> int:
        with self._lock:
            if data == prt5.ENQ:
                self._rx += self._weight_frame()
            elif data[:1] == prt5.SOH and data[-1:] == prt5.ETX and len(data) == 8:
                self._rx += self._handle_tare(data[1:-1])
            elif data[:1] == prt5.STX and data[-1:] == prt5.ETX and len(data) == 8:
                self._rx += self._handle_price(data[1:-1])
            else:
                self._rx += prt5.NACK
        return len(data)

    def read(self, size: int = 1) -> bytes:
        with self._lock:
            chunk, self._rx = bytes(self._rx[:size]), self._rx[size:]
        return chunk

    def read_until(self, terminator: bytes = b"\n") -> bytes:
        with self._lock:
            idx = self._rx.find(terminator)
            if idx < 0:
                return b""       # simula timeout sem resposta completa
            end = idx + len(terminator)
            chunk, self._rx = bytes(self._rx[:end]), self._rx[end:]
        return chunk

    def close(self) -> None:
        self.is_open = False

    # ---- lógica da balança --------------------------------------------------
    def _weight_frame(self) -> bytes:
        if self.unstable:
            return prt5.STX + prt5.UNSTABLE.encode() + prt5.ETX
        net = self.gross_g - self.tare_g
        if self.gross_g > CAPACITY_G:
            return prt5.STX + prt5.OVERLOAD.encode() + prt5.ETX
        if net < 0:
            return prt5.STX + prt5.NEGATIVE.encode() + prt5.ETX
        step = _resolution(net)
        net = (net + step // 2) // step * step   # meio para cima, só com inteiros
        return prt5.STX + f"{net:05d}".encode() + prt5.ETX

    def _handle_tare(self, digits: bytes) -> bytes:
        if not digits.isdigit():
            return prt5.NACK
        grams = int(digits)
        if grams > CAPACITY_G:
            return prt5.NACK
        self.tare_g = grams
        return prt5.ACK

    def _handle_price(self, digits: bytes) -> bytes:
        if not digits.isdigit():
            return prt5.NACK
        self.price_per_kg = Decimal(int(digits)) / 100
        return prt5.ACK

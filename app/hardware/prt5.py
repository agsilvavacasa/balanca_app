"""Protocolo Prt5 da Toledo Prix 3 Fit (manual MU-3-Fit, seção 5.3.4, págs. 15-16).

Funções puras de montagem/interpretação de pacotes, sem I/O, para poderem ser
testadas sem balança.

  Peso   : PC -> ENQ                         balança -> STX ppppp ETX
           ppppp = 5 dígitos, 2 inteiros + 3 decimais (kg); ou IIIII / NNNNN / SSSSS
  Preço  : PC -> STX PPPPPP ETX              balança -> ACK | NACK   (4 int + 2 dec)
  Tara   : PC -> SOH TTTTTT ETX              balança -> ACK | NACK   (gramas)
"""
from decimal import Decimal, ROUND_HALF_UP

from .scale import ScaleProtocolError, ScaleReading, WeightStatus

SOH = b"\x01"
STX = b"\x02"
ETX = b"\x03"
ENQ = b"\x05"
ACK = b"\x06"
NACK = b"\x21"   # o manual define NACK = 21h (não 15h)

UNSTABLE = "IIIII"
NEGATIVE = "NNNNN"
OVERLOAD = "SSSSS"


def build_weight_request() -> bytes:
    return ENQ


def build_price_frame(price_per_kg: Decimal) -> bytes:
    cents = int((price_per_kg * 100).to_integral_value(rounding=ROUND_HALF_UP))
    if not 0 <= cents <= 999_999:
        raise ValueError(f"Preço/kg fora da faixa do protocolo (0 a 9999,99): {price_per_kg}")
    return STX + f"{cents:06d}".encode("ascii") + ETX


def build_tare_frame(grams: int) -> bytes:
    if not isinstance(grams, int) or isinstance(grams, bool):
        raise TypeError("A tara deve ser informada em gramas inteiras")
    if not 0 <= grams <= 999_999:
        raise ValueError(f"Tara fora da faixa do protocolo: {grams} g")
    return SOH + f"{grams:06d}".encode("ascii") + ETX


def parse_weight_response(response: bytes) -> ScaleReading:
    """Interpreta STX + 5 caracteres + ETX. Ruído antes do último STX é descartado."""
    start = response.rfind(STX)
    if start < 0 or not response.endswith(ETX):
        raise ScaleProtocolError(f"Pacote inválido: {response!r}")
    frame = response[start:]
    payload = frame[1:-1]
    if len(payload) != 5:
        raise ScaleProtocolError(f"Campo de peso deveria ter 5 caracteres: {frame!r}")
    try:
        text = payload.decode("ascii")
    except UnicodeDecodeError as exc:
        raise ScaleProtocolError(f"Caracteres não ASCII: {frame!r}") from exc

    if text == UNSTABLE:
        return ScaleReading(WeightStatus.UNSTABLE, None, frame)
    if text == NEGATIVE:
        return ScaleReading(WeightStatus.NEGATIVE, None, frame)
    if text == OVERLOAD:
        return ScaleReading(WeightStatus.OVERLOAD, None, frame)
    if not text.isdigit():
        raise ScaleProtocolError(f"Peso não numérico: {frame!r}")
    return ScaleReading(WeightStatus.OK, Decimal(text).scaleb(-3), frame)  # 3 casas fixas


def parse_ack(response: bytes) -> bool:
    if response == ACK:
        return True
    if response == NACK:
        return False
    raise ScaleProtocolError(f"Resposta desconhecida da balança: {response!r}")

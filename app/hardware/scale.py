"""Contrato comum para balanças (seção 12 do documento)."""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Optional


class ScaleError(Exception):
    """Erro genérico de balança."""


class ScaleNotConnected(ScaleError):
    pass


class ScaleTimeout(ScaleError):
    """A balança não respondeu no tempo esperado."""


class ScaleProtocolError(ScaleError):
    """Resposta fora do formato do protocolo."""


class WeightStatus(str, Enum):
    OK = "OK"
    UNSTABLE = "UNSTABLE"    # IIIII
    NEGATIVE = "NEGATIVE"    # NNNNN
    OVERLOAD = "OVERLOAD"    # SSSSS


@dataclass(frozen=True)
class ScaleReading:
    status: WeightStatus
    weight_kg: Optional[Decimal]   # None quando status != OK
    raw: bytes = b""
    at: datetime = field(default_factory=datetime.now)

    @property
    def raw_hex(self) -> str:
        return " ".join(f"{b:02X}" for b in self.raw)


class Scale(ABC):
    @abstractmethod
    def connect(self) -> None: ...

    @abstractmethod
    def disconnect(self) -> None: ...

    @abstractmethod
    def is_connected(self) -> bool: ...

    @abstractmethod
    def get_weight(self) -> ScaleReading: ...

    @abstractmethod
    def set_tare(self, grams: int) -> bool: ...

    @abstractmethod
    def set_price_per_kg(self, price: Decimal) -> bool: ...

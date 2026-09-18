"""Regras de validação da leitura da balança (etapa 5 do fluxo, RN007 e RN008).

Não faz I/O: recebe leituras e diz se o valor pode ser usado."""
from collections import deque
from decimal import Decimal
from enum import Enum
from typing import Optional

from ..hardware.scale import ScaleReading, WeightStatus


class WeighingState(str, Enum):
    NO_SCALE = "NO_SCALE"
    EMPTY = "EMPTY"            # peso zero
    SETTLING = "SETTLING"      # instável ou ainda sem leituras iguais suficientes
    STABLE = "STABLE"
    NEGATIVE = "NEGATIVE"
    OVERLOAD = "OVERLOAD"


MESSAGES = {
    WeighingState.NO_SCALE: "Balança não conectada.",
    WeighingState.EMPTY: "Coloque o prato na balança.",
    WeighingState.SETTLING: "Aguardando estabilização da balança...",
    WeighingState.STABLE: "Peso estável.",
    WeighingState.NEGATIVE: "Peso inválido. Verifique o prato da balança.",
    WeighingState.OVERLOAD: "Peso acima da capacidade da balança.",
}


class StabilityTracker:
    """Só considera o peso estável após N leituras válidas e iguais em sequência.

    O ENQ do Prt5 responde IIIII quando a balança está em movimento, mas uma leitura
    isolada não garante que o valor cobrado é o final; exigir repetição protege o cliente."""

    def __init__(self, required: int = 3, capacity_kg: Decimal = Decimal("32")):
        self.required = max(1, required)
        self.capacity_kg = capacity_kg
        self._recent: deque[Decimal] = deque(maxlen=self.required)

    def reset(self) -> None:
        self._recent.clear()

    def evaluate(self, reading: Optional[ScaleReading]) -> tuple[WeighingState, Optional[Decimal]]:
        if reading is None:
            self.reset()
            return WeighingState.NO_SCALE, None
        if reading.status is WeightStatus.OVERLOAD:
            self.reset()
            return WeighingState.OVERLOAD, None
        if reading.status is WeightStatus.NEGATIVE:
            self.reset()
            return WeighingState.NEGATIVE, None
        if reading.status is WeightStatus.UNSTABLE:
            self.reset()
            return WeighingState.SETTLING, None

        weight = reading.weight_kg
        if weight > self.capacity_kg:
            self.reset()
            return WeighingState.OVERLOAD, None
        if weight == 0:
            self.reset()
            return WeighingState.EMPTY, weight

        self._recent.append(weight)
        stable = len(self._recent) == self.required and len(set(self._recent)) == 1
        return (WeighingState.STABLE if stable else WeighingState.SETTLING), weight

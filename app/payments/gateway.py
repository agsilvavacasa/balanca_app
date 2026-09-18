"""Cobrança eletrônica (TEF). O sistema só conhece esta interface; cada fornecedor real
(Sitef, PayGo, Stone, Cielo...) entra como uma subclasse em `tef.py` sem mexer no resto."""
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional


@dataclass(frozen=True)
class PaymentResult:
    approved: bool
    reference: Optional[str] = None     # NSU / código de autorização / id do PIX
    message: str = ""


class PaymentGateway(ABC):
    name = "gateway"

    @abstractmethod
    def charge(self, method: str, amount: Decimal, description: str = "") -> PaymentResult:
        """Bloqueia até a operadora responder. Chame fora da thread da interface."""


class SimulatedTefGateway(PaymentGateway):
    """Aprova depois de uma pequena espera. `decline_next` força a próxima cobrança a falhar
    (útil para testar o fluxo de recusa)."""
    name = "simulado"

    def __init__(self, delay_s: float = 1.2):
        self.delay_s = delay_s
        self.decline_next = False
        self._counter = 0
        self._lock = threading.Lock()

    def charge(self, method: str, amount: Decimal, description: str = "") -> PaymentResult:
        time.sleep(self.delay_s)
        with self._lock:
            self._counter += 1
            number = self._counter
            decline, self.decline_next = self.decline_next, False
        if decline:
            return PaymentResult(False, None, "Pagamento recusado pela operadora.")
        return PaymentResult(True, f"SIM{number:06d}", "Pagamento aprovado.")


def build_gateway(kind: str) -> PaymentGateway:
    if kind == "simulated":
        return SimulatedTefGateway()
    if kind == "tef":
        from .tef import TefGateway
        return TefGateway()
    raise ValueError(f"Gateway de pagamento desconhecido: {kind}")

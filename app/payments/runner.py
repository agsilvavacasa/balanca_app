"""Executa a cobrança numa thread do pool: o TEF real bloqueia esperando o cartão/PIX."""
from decimal import Decimal

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

from .gateway import PaymentGateway, PaymentResult


class _Signals(QObject):
    done = Signal(object)      # PaymentResult


class _Job(QRunnable):
    def __init__(self, gateway: PaymentGateway, method: str, amount: Decimal, description: str,
                 signals: _Signals):
        super().__init__()
        self._args = (gateway, method, amount, description)
        self._signals = signals

    def run(self) -> None:
        gateway, method, amount, description = self._args
        try:
            result = gateway.charge(method, amount, description)
        except Exception as exc:                   # falha do SDK, timeout, NotImplementedError...
            result = PaymentResult(False, None, str(exc) or exc.__class__.__name__)
        self._signals.done.emit(result)


class ChargeRunner(QObject):
    finished = Signal(object)          # PaymentResult

    def __init__(self, gateway: PaymentGateway, parent: QObject | None = None):
        super().__init__(parent)
        self.gateway = gateway
        self.busy = False
        self._signals = _Signals()
        self._signals.done.connect(self._on_done)

    def start(self, method: str, amount: Decimal, description: str = "") -> None:
        if self.busy:
            return
        self.busy = True
        QThreadPool.globalInstance().start(
            _Job(self.gateway, method, amount, description, self._signals))

    def _on_done(self, result: PaymentResult) -> None:
        self.busy = False
        self.finished.emit(result)

"""A balança é lida numa QThread própria: a interface nunca espera pela serial (RNF008).
O worker é o único dono da porta; comandos chegam por sinais (fila) e são
executados entre uma leitura e outra."""
from decimal import Decimal
from typing import Callable, Optional

from PySide6.QtCore import QMetaObject, QObject, Qt, QThread, QTimer, Signal, Slot

from ..config.settings import ScaleSettings
from ..hardware.prix3fit import ToledoPrix3Fit, pyserial_factory
from ..hardware.scale import Scale, ScaleError, ScaleNotConnected
from ..hardware.simulator import SimulatedSerial

RECONNECT_EVERY_MS = 3000


class ScaleWorker(QObject):
    reading = Signal(object)                 # ScaleReading | None (falha)
    link_changed = Signal(bool, str)          # conectada?, detalhe
    command_result = Signal(str, bool, str)   # "tare"|"price", ok, mensagem

    def __init__(self, factory: Callable[[], Scale], poll_ms: int):
        super().__init__()
        self._factory = factory
        self._poll_ms = poll_ms
        self._scale: Optional[Scale] = None
        self._timer: Optional[QTimer] = None
        self._connected = False
        self._since_reconnect = 0

    @Slot()
    def start(self) -> None:
        self._scale = self._factory()
        self._timer = QTimer(self)
        self._timer.setInterval(self._poll_ms)
        self._timer.timeout.connect(self._poll)
        self._try_connect()
        self._timer.start()

    @Slot()
    def shutdown(self) -> None:
        if self._timer:
            self._timer.stop()
        if self._scale:
            try:
                self._scale.disconnect()
            except Exception:
                pass
        self._connected = False

    def _try_connect(self) -> None:
        try:
            self._scale.connect()
            self._connected = True
            self.link_changed.emit(True, "")
        except Exception as exc:
            self._connected = False
            self.link_changed.emit(False, self._describe(exc))

    @staticmethod
    def _describe(exc: Exception) -> str:
        text = str(exc).strip()
        return text or exc.__class__.__name__

    def _drop_link(self, exc: Exception) -> None:
        try:
            self._scale.disconnect()
        except Exception:
            pass
        self._connected = False
        self.link_changed.emit(False, self._describe(exc))

    @Slot()
    def _poll(self) -> None:
        if not self._connected:
            self._since_reconnect += self._poll_ms
            self.reading.emit(None)
            if self._since_reconnect >= RECONNECT_EVERY_MS:
                self._since_reconnect = 0
                self._try_connect()
            return
        try:
            self.reading.emit(self._scale.get_weight())
        except ScaleNotConnected as exc:
            self._drop_link(exc)
            self.reading.emit(None)
        except ScaleError as exc:                 # timeout / pacote inválido: segue tentando
            self.link_changed.emit(True, self._describe(exc))
            self.reading.emit(None)
        except Exception as exc:                  # SerialException etc.: porta caiu
            self._drop_link(exc)
            self.reading.emit(None)

    @Slot(int)
    def apply_tare(self, grams: int) -> None:
        self._run("tare", lambda: self._scale.set_tare(grams))

    @Slot(object)
    def send_price(self, price: Decimal) -> None:
        self._run("price", lambda: self._scale.set_price_per_kg(price))

    def _run(self, name: str, action: Callable[[], bool]) -> None:
        if not self._connected:
            self.command_result.emit(name, False, "Balança não conectada.")
            return
        try:
            ok = action()
            self.command_result.emit(name, ok, "" if ok else "A balança recusou o comando (NACK).")
        except Exception as exc:
            self.command_result.emit(name, False, self._describe(exc))


class ScaleController(QObject):
    """Fachada usada pela interface: esconde a thread e a fábrica do driver."""
    reading = Signal(object)
    link_changed = Signal(bool, str)
    command_result = Signal(str, bool, str)
    _tare = Signal(int)
    _price = Signal(object)

    def __init__(self, settings: ScaleSettings, parent: QObject | None = None):
        super().__init__(parent)
        self.settings = settings
        self.simulator: Optional[SimulatedSerial] = (
            SimulatedSerial() if settings.mode == "simulated" else None)
        self._thread: Optional[QThread] = None
        self._worker: Optional[ScaleWorker] = None

    def _build_scale(self) -> Scale:
        cfg = self.settings
        if self.simulator is not None:
            sim = self.simulator

            def open_sim():
                sim.is_open = True
                return sim
            return ToledoPrix3Fit(open_sim)
        return ToledoPrix3Fit(pyserial_factory(
            cfg.port, cfg.baudrate, cfg.data_bits, cfg.parity, cfg.stop_bits, cfg.timeout_s))

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = QThread()
        self._worker = ScaleWorker(self._build_scale, self.settings.poll_ms)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.start)
        self._worker.reading.connect(self.reading)
        self._worker.link_changed.connect(self.link_changed)
        self._worker.command_result.connect(self.command_result)
        self._tare.connect(self._worker.apply_tare)
        self._price.connect(self._worker.send_price)
        self._thread.start()

    def stop(self) -> None:
        if self._thread is None:
            return
        QMetaObject.invokeMethod(self._worker, "shutdown", Qt.ConnectionType.BlockingQueuedConnection)
        self._thread.quit()
        self._thread.wait(3000)
        self._worker.deleteLater()
        self._thread.deleteLater()
        self._thread = self._worker = None

    def request_tare(self, grams: int) -> None:
        self._tare.emit(grams)

    def request_price(self, price: Decimal) -> None:
        self._price.emit(price)

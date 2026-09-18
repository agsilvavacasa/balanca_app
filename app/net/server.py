"""Servidor embutido: aceita conexões dos terminais na rede local e executa as chamadas nos serviços
locais (que falam com o banco). Sem dependências extras (biblioteca padrão)."""
import hmac
import json
import logging
import secrets
import socket
import threading
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional

from ..bootstrap import Services
from ..services.errors import BusinessError
from . import protocol

log = logging.getLogger("balanca.server")
_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"      # sem 0/O/1/I para ditar o código sem confusão


def new_access_key(length: int = 8) -> str:
    return "".join(secrets.choice(_ALPHABET) for _ in range(length))


def local_ips() -> list[str]:
    """IPs deste PC na rede (o que o terminal deve digitar)."""
    found: list[str] = []
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))          # não envia nada; só descobre a interface de saída
            found.append(s.getsockname()[0])
    except OSError:
        pass
    try:
        for ip in socket.gethostbyname_ex(socket.gethostname())[2]:
            if ip not in found and not ip.startswith("127."):
                found.append(ip)
    except OSError:
        pass
    return found or ["127.0.0.1"]


@dataclass
class ClientInfo:
    address: str
    name: str
    last_seen: datetime
    requests: int = 0


class ServerHost:
    def __init__(self, services: Services, access_key: str, host: str = "0.0.0.0",
                 port: int = protocol.DEFAULT_PORT, name: str = "Servidor"):
        self.services = services
        self.access_key = access_key
        self.host = host
        self.port = port
        self.name = name
        self.clients: dict[str, ClientInfo] = {}
        self.events: deque[str] = deque(maxlen=200)
        self._lock = threading.Lock()
        self._httpd: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None

    # ---------------------------------------------------------------- ciclo de vida
    def start(self) -> int:
        """Começa a escutar e devolve a porta efetiva (útil com porta 0 nos testes)."""
        host = self

        class Handler(_Handler):
            server_host = host

        self._httpd = ThreadingHTTPServer((self.host, self.port), Handler)
        self._httpd.daemon_threads = True
        self.port = self._httpd.server_address[1]
        self._thread = threading.Thread(target=self._httpd.serve_forever, name="balanca-server", daemon=True)
        self._thread.start()
        self._event(f"Servidor iniciado na porta {self.port}")
        return self.port

    def stop(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None
            self._event("Servidor parado")

    @property
    def running(self) -> bool:
        return self._httpd is not None

    # ---------------------------------------------------------------- registro
    def _event(self, text: str) -> None:
        with self._lock:
            self.events.append(f"{datetime.now():%H:%M:%S}  {text}")

    def touch(self, address: str, name: str) -> None:
        with self._lock:
            key = f"{address}|{name}"
            info = self.clients.get(key)
            if info is None:
                info = self.clients[key] = ClientInfo(address, name, datetime.now())
                self.events.append(f"{datetime.now():%H:%M:%S}  Conectou: {name} ({address})")
            info.name, info.last_seen = name, datetime.now()
            info.requests += 1

    def active_clients(self, within_s: int = 30) -> list[ClientInfo]:
        limit = datetime.now().timestamp() - within_s
        with self._lock:
            return sorted((c for c in self.clients.values() if c.last_seen.timestamp() >= limit),
                          key=lambda c: (c.name, c.address))

    def valid_key(self, presented: str) -> bool:
        return bool(self.access_key) and hmac.compare_digest(presented.encode(), self.access_key.encode())

    # ---------------------------------------------------------------- execução
    def dispatch(self, service: str, method: str, args: list, kwargs: dict):
        if method not in protocol.ALLOWED.get(service, frozenset()):
            raise LookupError(f"método não permitido: {service}.{method}")
        return getattr(getattr(self.services, service), method)(*args, **kwargs)


class _Handler(BaseHTTPRequestHandler):
    server_host: ServerHost
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args) -> None:        # silencia o log padrão no stderr
        pass

    def _reply(self, status: int, body: dict) -> None:
        raw = json.dumps(body, ensure_ascii=False).encode("utf-8") if not isinstance(body, bytes) else body
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _authorized(self) -> bool:
        if not self.server_host.valid_key(self.headers.get(protocol.KEY_HEADER, "")):
            self.server_host._event(f"Recusado (código incorreto): {self.client_address[0]}")
            self._reply(401, {"ok": False, "error": {"type": "Unauthorized",
                                                     "message": "Código de acesso incorreto."}})
            return False
        return True

    def do_GET(self) -> None:
        if self.path != "/ping":
            return self._reply(404, {"ok": False, "error": {"type": "NotFound", "message": "Rota inexistente."}})
        if self._authorized():
            self.server_host.touch(self.client_address[0], self.headers.get(protocol.CLIENT_HEADER, "?"))
            self._reply(200, {"ok": True, "server": self.server_host.name, "version": protocol.VERSION})

    def do_POST(self) -> None:
        if self.path != "/rpc":
            return self._reply(404, {"ok": False, "error": {"type": "NotFound", "message": "Rota inexistente."}})
        if not self._authorized():
            return
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > protocol.MAX_BODY:
            return self._reply(413, {"ok": False, "error": {"type": "BadRequest", "message": "Corpo inválido."}})
        self.server_host.touch(self.client_address[0], self.headers.get(protocol.CLIENT_HEADER, "?"))
        try:
            call = protocol.loads(self.rfile.read(length))
            result = self.server_host.dispatch(call["service"], call["method"],
                                               call.get("args", []), call.get("kwargs", {}))
            self._reply(200, {"ok": True, "result": protocol.to_json(result)})
        except BusinessError as exc:                   # regra de negócio: o terminal mostra a mensagem
            self._reply(200, {"ok": False, "error": protocol.error_to_payload(exc)})
        except (LookupError, KeyError, TypeError, ValueError) as exc:
            log.warning("chamada inválida de %s: %s", self.client_address[0], exc)
            self._reply(400, {"ok": False, "error": {"type": "BadRequest", "message": "Chamada inválida."}})
        except Exception:
            log.exception("erro interno no servidor")
            self.server_host._event("Erro interno (veja o log do servidor)")
            self._reply(500, {"ok": False, "error": {"type": "ServerError",
                                                     "message": "Erro interno no servidor."}})

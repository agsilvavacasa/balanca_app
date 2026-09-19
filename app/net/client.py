"""Cliente do servidor: parece um serviço local (mesmos métodos), mas chama o PC servidor pela rede."""
import json
import socket
import urllib.error
import urllib.request
from typing import Any, Optional

from ..bootstrap import Services
from ..services.errors import BusinessError
from . import protocol


class ServerUnavailable(BusinessError):
    """Não foi possível falar com o servidor (desligado, IP errado, rede, firewall)."""


class ServerRejected(BusinessError):
    """O servidor recusou a conexão (código de acesso incorreto)."""


class RemoteClient:
    def __init__(self, host: str, port: int, access_key: str, client_name: str = "Terminal",
                 timeout: float = 8.0):
        self.base = f"http://{host}:{port}"
        self.host, self.port = host, port
        self.access_key = access_key
        self.client_name = client_name
        self.timeout = timeout

    def _open(self, request: urllib.request.Request) -> dict:
        request.add_header(protocol.KEY_HEADER, self.access_key)
        request.add_header(protocol.CLIENT_HEADER, self.client_name)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code == 401:
                raise ServerRejected("Código de acesso do servidor incorreto.") from None
            try:
                body = json.loads(exc.read().decode("utf-8"))
                raise BusinessError(body.get("error", {}).get("message", f"Erro {exc.code} no servidor.")) from None
            except (ValueError, UnicodeDecodeError):
                raise BusinessError(f"Erro {exc.code} no servidor.") from None
        except (urllib.error.URLError, socket.timeout, ConnectionError, OSError) as exc:
            raise ServerUnavailable(
                f"Sem conexão com o servidor ({self.host}:{self.port}). Verifique se ele está ligado e na mesma rede."
            ) from exc

    def ping(self) -> dict:
        return self._open(urllib.request.Request(f"{self.base}/ping"))

    def call(self, service: str, method: str, args: tuple, kwargs: dict) -> Any:
        body = protocol.dumps({"service": service, "method": method, "args": list(args), "kwargs": kwargs})
        request = urllib.request.Request(f"{self.base}/rpc", data=body, method="POST",
                                         headers={"Content-Type": "application/json"})
        reply = self._open(request)
        if reply.get("ok"):
            return protocol.from_json(reply["result"])
        raise protocol.payload_to_error(reply.get("error", {}))


class RemoteService:
    def __init__(self, client: RemoteClient, name: str):
        self._client = client
        self._name = name

    def __getattr__(self, method: str):
        if method.startswith("_") or method not in protocol.ALLOWED[self._name]:
            raise AttributeError(method)

        def call(*args, **kwargs):
            return self._client.call(self._name, method, args, kwargs)
        call.__name__ = method
        return call


def build_remote_services(host: str, port: int, access_key: str,
                          client_name: str = "Terminal", check: bool = True) -> Services:
    client = RemoteClient(host, port, access_key, client_name)
    if check:
        client.ping()
    return Services(db=None, auth=RemoteService(client, "auth"),
                    pricing=RemoteService(client, "pricing"), commands=RemoteService(client, "commands"),
                    catalog=RemoteService(client, "catalog"))

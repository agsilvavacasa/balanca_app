"""Contrato de rede entre o PC servidor (donos dos dados) e os terminais.

O terminal chama os MESMOS métodos dos serviços locais (auth, pricing, commands); o que muda é que a
chamada viaja por HTTP/JSON. Só métodos da lista abaixo são expostos."""
import dataclasses
import json
from datetime import datetime
from decimal import Decimal
from typing import Any

from ..services import dto, errors

VERSION = 1
KEY_HEADER = "X-Access-Key"
CLIENT_HEADER = "X-Client-Name"
DEFAULT_PORT = 8765
MAX_BODY = 1_000_000

ALLOWED: dict[str, frozenset[str]] = {
    "auth": frozenset({"list_operators", "authenticate", "authenticate_admin", "self_service_operator"}),
    "pricing": frozenset({"current_price", "set_price"}),
    "commands": frozenset({
        "start_command", "find", "get", "open_commands_by_cpf", "list_awaiting_payment", "unit_products",
        "add_weighed_consumption", "add_unit_product", "cancel_consumption", "send_to_payment",
        "reopen_command", "cancel_command", "register_payment"}),
}

_DTOS = {cls.__name__: cls for cls in (dto.OperatorInfo, dto.ProductInfo, dto.ItemInfo, dto.PaymentInfo,
                                       dto.CommandInfo, dto.CommandSummary)}
_ERRORS = {cls.__name__: cls for cls in vars(errors).values()
           if isinstance(cls, type) and issubclass(cls, errors.BusinessError)}


# ---------------------------------------------------------------- JSON <-> objetos
def to_json(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        raise TypeError("float não trafega na rede (use Decimal)")
    if isinstance(value, Decimal):
        return {"__t": "dec", "v": str(value)}
    if isinstance(value, datetime):
        return {"__t": "dt", "v": value.isoformat()}
    if isinstance(value, tuple):
        return {"__t": "tuple", "v": [to_json(v) for v in value]}
    if isinstance(value, list):
        return [to_json(v) for v in value]
    if isinstance(value, dict):
        return {"__t": "dict", "v": {str(k): to_json(v) for k, v in value.items()}}
    if dataclasses.is_dataclass(value) and type(value).__name__ in _DTOS:
        return {"__t": "dc", "c": type(value).__name__,
                "f": {f.name: to_json(getattr(value, f.name)) for f in dataclasses.fields(value)}}
    raise TypeError(f"tipo não serializável: {type(value).__name__}")


def from_json(value: Any) -> Any:
    if isinstance(value, list):
        return [from_json(v) for v in value]
    if not isinstance(value, dict):
        return value
    kind = value.get("__t")
    if kind == "dec":
        return Decimal(value["v"])
    if kind == "dt":
        return datetime.fromisoformat(value["v"])
    if kind == "tuple":
        return tuple(from_json(v) for v in value["v"])
    if kind == "dict":
        return {k: from_json(v) for k, v in value["v"].items()}
    if kind == "dc":
        cls = _DTOS.get(value["c"])
        if cls is None:
            raise ValueError(f"DTO desconhecido: {value['c']}")
        return cls(**{k: from_json(v) for k, v in value["f"].items()})
    raise ValueError("objeto JSON inesperado")


def dumps(value: Any) -> bytes:
    return json.dumps(to_json(value), ensure_ascii=False).encode("utf-8")


def loads(raw: bytes) -> Any:
    return from_json(json.loads(raw.decode("utf-8")))


# ---------------------------------------------------------------- erros de negócio pela rede
def error_to_payload(exc: errors.BusinessError) -> dict:
    payload = {"type": type(exc).__name__, "message": str(exc)}
    if isinstance(exc, errors.DuplicateOpenCommand):
        payload["existing_code"] = exc.existing_code
    return payload


def payload_to_error(payload: dict) -> errors.BusinessError:
    cls = _ERRORS.get(payload.get("type", ""), errors.BusinessError)
    message = payload.get("message", "")
    if cls is errors.DuplicateOpenCommand:
        return errors.DuplicateOpenCommand(payload.get("existing_code", ""))
    exc = cls(message)
    return exc

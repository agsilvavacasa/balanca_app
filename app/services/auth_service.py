from typing import Optional

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from ..database.connection import Database
from ..database.models import Operator
from .dto import OperatorInfo
import os

from .security import hash_pin, verify_pin

SELF_SERVICE_NAME = "Autoatendimento"


class AuthService:
    def __init__(self, db: Database):
        self._db = db

    def list_operators(self) -> list[OperatorInfo]:
        with self._db.session() as s:
            rows = s.scalars(select(Operator).where(Operator.active).order_by(Operator.is_admin, Operator.name)).all()
            return [OperatorInfo(o.id, o.name, o.is_admin) for o in rows]

    def authenticate(self, operator_id: int, pin: str) -> Optional[OperatorInfo]:
        with self._db.session() as s:
            op = s.get(Operator, operator_id)
            if op and op.active and verify_pin(pin, op.pin_salt, op.pin_hash):
                return OperatorInfo(op.id, op.name, op.is_admin)
        return None

    def self_service_operator(self) -> OperatorInfo:
        """Operador técnico que assina os lançamentos feitos pelo cliente.

        Fica inativo: não aparece na tela de login e não autentica com PIN nenhum. A criação é
        segura contra corrida: dois terminais podem pedi-lo ao mesmo tempo num banco novo."""
        for _ in range(3):
            try:
                with self._db.session() as s:
                    op = s.scalar(select(Operator).where(Operator.name == SELF_SERVICE_NAME))
                    if op is None:
                        salt, digest = hash_pin(os.urandom(16).hex())
                        op = Operator(name=SELF_SERVICE_NAME, pin_salt=salt, pin_hash=digest,
                                      is_admin=False, active=False)
                        s.add(op)
                        s.flush()
                    return OperatorInfo(op.id, op.name, False)
            except IntegrityError:          # outro terminal criou primeiro: lê o que ele criou
                continue
        raise RuntimeError("Não foi possível obter o operador do autoatendimento.")

    def authenticate_admin(self, pin: str) -> Optional[OperatorInfo]:
        """Autorização de gerente (RF019): qualquer administrador ativo com esse PIN."""
        with self._db.session() as s:
            for op in s.scalars(select(Operator).where(Operator.active, Operator.is_admin)):
                if verify_pin(pin, op.pin_salt, op.pin_hash):
                    return OperatorInfo(op.id, op.name, op.is_admin)
        return None

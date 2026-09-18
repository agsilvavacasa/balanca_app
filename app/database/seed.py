"""Dados iniciais de demonstração (só cria se o banco estiver vazio)."""
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select

from ..services.security import hash_pin
from .connection import Database
from .models import (Command, CommandStatus, Consumption, Operator, Product, ProductPrice,
                     ProductType, Scale)


def seed_if_empty(db: Database) -> None:
    with db.session() as s:
        if s.scalar(select(Operator.id).limit(1)) is not None:
            return

        for name, pin, admin in (("Operador 1", "1111", False), ("Gerente", "9999", True)):
            salt, digest = hash_pin(pin)
            s.add(Operator(name=name, pin_salt=salt, pin_hash=digest, is_admin=admin))

        s.add(Scale(name="Balança 1", model="Toledo Prix 3 Fit", port=""))

        now = datetime.now()
        products = [
            ("001", "COMIDA POR KG", ProductType.WEIGHT, "KG", "79.90"),
            ("002", "REFRIGERANTE", ProductType.UNIT, "UN", "8.00"),
            ("003", "ÁGUA", ProductType.UNIT, "UN", "4.00"),
            ("004", "SOBREMESA", ProductType.UNIT, "UN", "12.00"),
        ]
        by_code = {}
        for code, desc, ptype, unit, price in products:
            product = Product(code=code, description=desc, type=ptype, unit=unit)
            s.add(product)
            s.flush()
            s.add(ProductPrice(product_id=product.id, price=Decimal(price), valid_from=now))
            by_code[code] = product

        op = s.scalar(select(Operator).where(Operator.name == "Operador 1"))
        # 000154 reproduz o exemplo do documento (bebida + sobremesa = R$ 20,00)
        c154 = Command(code="000154", status=CommandStatus.OPEN, opened_at=now)
        s.add_all([c154,
                   Command(code="000155", status=CommandStatus.OPEN, opened_at=now),
                   Command(code="000156", status=CommandStatus.PAID, opened_at=now, closed_at=now)])
        s.flush()
        for code, price in (("002", "8.00"), ("004", "12.00")):
            s.add(Consumption(command_id=c154.id, product_id=by_code[code].id,
                              type=ProductType.UNIT, quantity=Decimal("1"),
                              unit_price=Decimal(price), total_price=Decimal(price),
                              operator_id=op.id))

from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import or_, select

from ..database.connection import Database
from ..database.models import Product, ProductPrice
from ..domain.money import round_money
from .errors import BusinessError, PriceNotFound


class PricingService:
    def __init__(self, db: Database):
        self._db = db

    @staticmethod
    def _current_price_query(product_id: int, at: datetime):
        return (select(ProductPrice)
                .where(ProductPrice.product_id == product_id,
                       ProductPrice.active,
                       ProductPrice.valid_from <= at,
                       or_(ProductPrice.valid_until.is_(None), ProductPrice.valid_until > at))
                .order_by(ProductPrice.valid_from.desc(), ProductPrice.id.desc())
                .limit(1))

    def current_price(self, product_code: str, at: Optional[datetime] = None) -> Decimal:
        at = at or datetime.now()
        with self._db.session() as s:
            product = s.scalar(select(Product).where(Product.code == product_code))
            if product is None:
                raise PriceNotFound(f"Produto {product_code} não cadastrado.")
            price = s.scalar(self._current_price_query(product.id, at))
            if price is None:
                raise PriceNotFound(f"Sem preço vigente para {product.description}.")
            return price.price

    def set_price(self, product_code: str, new_price: Decimal, operator_id: int) -> None:
        """Encerra o preço vigente e abre um novo: consumos antigos não mudam (RN006)."""
        new_price = round_money(new_price)
        if new_price <= 0:
            raise BusinessError("O preço deve ser maior que zero.")
        now = datetime.now()
        with self._db.session() as s:
            product = s.scalar(select(Product).where(Product.code == product_code))
            if product is None:
                raise PriceNotFound(f"Produto {product_code} não cadastrado.")
            current = s.scalar(self._current_price_query(product.id, now))
            if current is not None:
                current.valid_until = now
            s.add(ProductPrice(product_id=product.id, price=new_price, valid_from=now,
                               created_by_id=operator_id))

"""Cadastro de produtos e preços (só gerente). O PIN de gerente é conferido AQUI, no servidor, a cada
chamada: um terminal com o código de acesso não consegue alterar preços sem ele."""
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import func, select

from ..database.connection import Database
from ..database.models import Product, ProductPrice, ProductType
from ..domain.money import round_money
from .auth_service import AuthService
from .command_service import WEIGHED_PRODUCT_CODE
from .dto import ProductAdminInfo
from .errors import BusinessError, NotAuthorized
from .pricing_service import PricingService

MAX_PRICE = Decimal("9999.99")
MAX_DESCRIPTION = 40         # cabe no ticket de 80 mm e no botão do kiosk


class CatalogService:
    def __init__(self, db: Database, pricing: PricingService, auth: AuthService):
        self._db = db
        self._pricing = pricing
        self._auth = auth

    def _require_admin(self, pin: str):
        admin = self._auth.authenticate_admin(pin or "")
        if admin is None:
            raise NotAuthorized("PIN de gerente inválido.")
        return admin

    @staticmethod
    def _clean_description(text: str) -> str:
        text = " ".join((text or "").split()).upper()
        if len(text) < 2:
            raise BusinessError("Informe o nome do produto.")
        if len(text) > MAX_DESCRIPTION:
            raise BusinessError(f"O nome deve ter no máximo {MAX_DESCRIPTION} caracteres.")
        return text

    @staticmethod
    def _clean_price(price: Decimal) -> Decimal:
        price = round_money(Decimal(price))
        if price <= 0 or price > MAX_PRICE:
            raise BusinessError("O preço deve ser maior que zero e no máximo R$ 9.999,99.")
        return price

    def _info(self, s, product: Product) -> ProductAdminInfo:
        now = datetime.now()
        current = s.scalar(self._pricing._current_price_query(product.id, now))
        return ProductAdminInfo(product.id, product.code, product.description, product.type.value,
                                product.unit, product.active,
                                current.price if current else None,
                                current.valid_from if current else None)

    # ------------------------------------------------------------------ consulta
    def list_products(self, admin_pin: str) -> list[ProductAdminInfo]:
        self._require_admin(admin_pin)
        with self._db.session() as s:
            products = s.scalars(select(Product).order_by(Product.code)).all()
            return [self._info(s, p) for p in products]

    # ------------------------------------------------------------------ alterações
    def create_product(self, admin_pin: str, description: str, price: Decimal,
                       unit: str = "UN") -> ProductAdminInfo:
        """Cria um produto vendido por unidade, com o primeiro preço. O código é gerado."""
        admin = self._require_admin(admin_pin)
        description = self._clean_description(description)
        price = self._clean_price(price)
        with self._db.session() as s:
            if s.scalar(select(Product.id).where(func.upper(Product.description) == description)):
                raise BusinessError(f"Já existe um produto chamado {description}.")
            last = s.scalar(select(func.max(Product.code)))
            number = int(last) + 1 if last and last.isdigit() else 1
            if number > 999:
                raise BusinessError("Limite de códigos de produto atingido.")
            product = Product(code=f"{number:03d}", description=description, type=ProductType.UNIT,
                              unit=(unit or "UN").upper()[:5], active=True)
            s.add(product)
            s.flush()
            s.add(ProductPrice(product_id=product.id, price=price, valid_from=datetime.now(),
                               created_by_id=admin.id))
            s.flush()
            return self._info(s, product)

    def rename_product(self, admin_pin: str, product_id: int, description: str) -> ProductAdminInfo:
        self._require_admin(admin_pin)
        description = self._clean_description(description)
        with self._db.session() as s:
            product = s.get(Product, product_id)
            if product is None:
                raise BusinessError("Produto não encontrado.")
            clash = s.scalar(select(Product.id).where(func.upper(Product.description) == description,
                                                      Product.id != product_id))
            if clash:
                raise BusinessError(f"Já existe um produto chamado {description}.")
            product.description = description        # lançamentos antigos guardam só o id: mostram o nome novo
            s.flush()
            return self._info(s, product)

    def set_active(self, admin_pin: str, product_id: int, active: bool) -> ProductAdminInfo:
        """Desativar tira o produto do kiosk sem apagar o histórico das vendas."""
        self._require_admin(admin_pin)
        with self._db.session() as s:
            product = s.get(Product, product_id)
            if product is None:
                raise BusinessError("Produto não encontrado.")
            if product.code == WEIGHED_PRODUCT_CODE and not active:
                raise BusinessError("A comida por quilo não pode ser desativada.")
            product.active = bool(active)
            s.flush()
            return self._info(s, product)

    def set_price(self, admin_pin: str, product_code: str, new_price: Decimal) -> ProductAdminInfo:
        """Encerra o preço vigente e abre outro; consumos já registrados não mudam (RN006)."""
        admin = self._require_admin(admin_pin)
        price = self._clean_price(new_price)
        self._pricing.set_price(product_code, price, admin.id)
        with self._db.session() as s:
            product = s.scalar(select(Product).where(Product.code == product_code))
            return self._info(s, product)

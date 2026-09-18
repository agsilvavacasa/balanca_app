from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Optional


@dataclass(frozen=True)
class OperatorInfo:
    id: int
    name: str
    is_admin: bool


@dataclass(frozen=True)
class ProductInfo:
    id: int
    code: str
    description: str
    type: str
    unit: str
    price: Decimal


@dataclass(frozen=True)
class ItemInfo:
    id: int
    description: str
    type: str
    quantity: Decimal
    weight_kg: Optional[Decimal]
    unit_price: Decimal
    total_price: Decimal
    status: str
    created_at: datetime
    operator_name: str
    cancel_reason: Optional[str] = None


@dataclass(frozen=True)
class PaymentInfo:
    id: int
    method: str
    amount: Decimal
    tendered: Optional[Decimal]
    change: Optional[Decimal]
    reference: Optional[str]
    paid_at: datetime
    operator_name: str


@dataclass(frozen=True)
class CommandInfo:
    id: int
    code: str
    status: str
    total: Decimal
    items: tuple[ItemInfo, ...]
    paid: Decimal = Decimal("0.00")
    payments: tuple[PaymentInfo, ...] = ()
    customer_cpf: Optional[str] = None
    opened_at: Optional[datetime] = None

    @property
    def remaining(self) -> Decimal:
        return max(self.total - self.paid, Decimal("0.00"))

    @property
    def active_items(self) -> tuple[ItemInfo, ...]:
        return tuple(i for i in self.items if i.status == "ACTIVE")


@dataclass(frozen=True)
class CommandSummary:
    id: int
    code: str
    status: str
    total: Decimal
    paid: Decimal
    opened_at: Optional[datetime]
    closed_at: Optional[datetime]
    customer_cpf: Optional[str]
    item_count: int

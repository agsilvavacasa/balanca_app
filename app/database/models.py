"""Modelo de dados (seção 14 do documento), com os ajustes da revisão:
 - cancelamento guarda motivo/data/operador (RN005);
 - weighing.gross_weight_kg é opcional (a balança só devolve o peso do display);
 - preço fica em product_price, nunca em product (RN006)."""
import enum
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (Boolean, DateTime, Enum, ForeignKey, Integer, Numeric, String, Text,
                        UniqueConstraint)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class CommandStatus(str, enum.Enum):
    OPEN = "OPEN"                          # cliente ainda se servindo / lançando itens
    AWAITING_PAYMENT = "AWAITING_PAYMENT"  # enviada ao caixa: não recebe mais itens
    PAID = "PAID"
    CANCELLED = "CANCELLED"
    CLOSED = "CLOSED"                      # legado da v1 (encerrada sem pagamento registrado)


class PaymentMethod(str, enum.Enum):
    CASH = "CASH"
    PIX = "PIX"
    CREDIT = "CREDIT"
    DEBIT = "DEBIT"


class ProductType(str, enum.Enum):
    WEIGHT = "WEIGHT"    # vendido por quilo, precisa de pesagem
    UNIT = "UNIT"        # vendido por unidade


class ConsumptionStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    CANCELLED = "CANCELLED"


class Operator(Base):
    __tablename__ = "operator"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True)
    pin_salt: Mapped[str] = mapped_column(String(32))
    pin_hash: Mapped[str] = mapped_column(String(64))
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Scale(Base):
    __tablename__ = "scale"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True)
    model: Mapped[str] = mapped_column(String(80))
    port: Mapped[str] = mapped_column(String(80), default="")


class Command(Base):
    __tablename__ = "command"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    status: Mapped[CommandStatus] = mapped_column(Enum(CommandStatus), default=CommandStatus.OPEN)
    customer_cpf: Mapped[Optional[str]] = mapped_column(String(11), nullable=True, index=True)
    opened_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)
    consumptions: Mapped[list["Consumption"]] = relationship(back_populates="command",
                                                             order_by="Consumption.id")
    payments: Mapped[list["Payment"]] = relationship(back_populates="command", order_by="Payment.id")


class Product(Base):
    __tablename__ = "product"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(10), unique=True)
    description: Mapped[str] = mapped_column(String(80))
    type: Mapped[ProductType] = mapped_column(Enum(ProductType))
    unit: Mapped[str] = mapped_column(String(5), default="UN")
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class ProductPrice(Base):
    __tablename__ = "product_price"
    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("product.id"), index=True)
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    valid_from: Mapped[datetime] = mapped_column(DateTime)
    valid_until: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by_id: Mapped[Optional[int]] = mapped_column(ForeignKey("operator.id"), nullable=True)
    product: Mapped[Product] = relationship()


class Consumption(Base):
    __tablename__ = "consumption"
    id: Mapped[int] = mapped_column(primary_key=True)
    command_id: Mapped[int] = mapped_column(ForeignKey("command.id"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("product.id"))
    type: Mapped[ProductType] = mapped_column(Enum(ProductType))
    quantity: Mapped[Decimal] = mapped_column(Numeric(10, 3), default=Decimal("1"))
    weight_kg: Mapped[Optional[Decimal]] = mapped_column(Numeric(8, 3), nullable=True)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(10, 2))   # R$/kg ou R$/un, congelado (RN006)
    total_price: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    tare_kg: Mapped[Optional[Decimal]] = mapped_column(Numeric(8, 3), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    operator_id: Mapped[int] = mapped_column(ForeignKey("operator.id"))
    status: Mapped[ConsumptionStatus] = mapped_column(Enum(ConsumptionStatus),
                                                      default=ConsumptionStatus.ACTIVE)
    cancel_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    cancelled_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    cancelled_by_id: Mapped[Optional[int]] = mapped_column(ForeignKey("operator.id"), nullable=True)

    command: Mapped[Command] = relationship(back_populates="consumptions")
    product: Mapped[Product] = relationship()
    operator: Mapped[Operator] = relationship(foreign_keys=[operator_id])
    weighing: Mapped[Optional["Weighing"]] = relationship(back_populates="consumption", uselist=False)


class Weighing(Base):
    __tablename__ = "weighing"
    id: Mapped[int] = mapped_column(primary_key=True)
    consumption_id: Mapped[int] = mapped_column(ForeignKey("consumption.id"), unique=True)
    gross_weight_kg: Mapped[Optional[Decimal]] = mapped_column(Numeric(8, 3), nullable=True)
    tare_weight_kg: Mapped[Optional[Decimal]] = mapped_column(Numeric(8, 3), nullable=True)
    net_weight_kg: Mapped[Decimal] = mapped_column(Numeric(8, 3))
    price_per_kg: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    total_price: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    scale_id: Mapped[Optional[int]] = mapped_column(ForeignKey("scale.id"), nullable=True)
    measured_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    status: Mapped[str] = mapped_column(String(20), default="CONFIRMED")
    raw_response: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    consumption: Mapped[Consumption] = relationship(back_populates="weighing")


class Payment(Base):
    __tablename__ = "payment"
    id: Mapped[int] = mapped_column(primary_key=True)
    command_id: Mapped[int] = mapped_column(ForeignKey("command.id"), index=True)
    method: Mapped[PaymentMethod] = mapped_column(Enum(PaymentMethod))
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2))            # valor abatido da comanda
    tendered: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), nullable=True)   # dinheiro recebido
    change_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), nullable=True)
    reference: Mapped[Optional[str]] = mapped_column(String(60), nullable=True)  # NSU/autorização TEF, id do PIX
    operator_id: Mapped[int] = mapped_column(ForeignKey("operator.id"))
    paid_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    command: Mapped[Command] = relationship(back_populates="payments")
    operator: Mapped[Operator] = relationship()

import re
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from ..database.connection import Database
from ..database.models import (Command, CommandStatus, Consumption, ConsumptionStatus, Operator,
                               Payment, PaymentMethod, Product, ProductType, Weighing)
from ..domain.cpf import is_valid_cpf, only_digits
from ..domain.money import calculate_total, format_brl, round_money
from .dto import CommandInfo, CommandSummary, ItemInfo, PaymentInfo, ProductInfo
from .errors import (BusinessError, CommandClosed, CommandNotFound, DuplicateOpenCommand,
                     InvalidCpf, InvalidWeight, PaymentError)
from .pricing_service import PricingService

WEIGHED_PRODUCT_CODE = "001"   # COMIDA POR KG
CODE_LENGTH = 6
MAX_CODE = 10 ** CODE_LENGTH - 1


def normalize_code(raw: str) -> str:
    """Aceita '000154', '154' e 'COMANDA: 000154' (o leitor pode mandar prefixo)."""
    digits = re.sub(r"\D", "", raw or "")
    if not digits:
        return ""
    return digits.zfill(CODE_LENGTH)


class CommandService:
    def __init__(self, db: Database, pricing: PricingService):
        self._db = db
        self._pricing = pricing

    # ------------------------------------------------------------------ criação
    def start_command(self, operator_id: int, cpf: Optional[str] = None) -> CommandInfo:
        """Cria uma comanda nova, com código sequencial. O CPF (opcional) permite recuperá-la
        se o cliente perder a comanda; só pode haver uma comanda em aberto por CPF."""
        cpf_digits = only_digits(cpf) if cpf else None
        if cpf_digits is not None and not is_valid_cpf(cpf_digits):
            raise InvalidCpf("CPF inválido. Confira os números digitados.")
        if cpf_digits:
            existing = self.open_commands_by_cpf(cpf_digits)
            if existing:
                raise DuplicateOpenCommand(existing[0].code)
        for _ in range(5):
            try:
                with self._db.session() as s:
                    last = s.scalar(select(func.max(Command.code)))
                    number = int(last) + 1 if last and last.isdigit() else 1
                    if number > MAX_CODE:
                        raise BusinessError("Limite de códigos de comanda atingido.")
                    command = Command(code=f"{number:0{CODE_LENGTH}d}", status=CommandStatus.OPEN,
                                      opened_at=datetime.now(), customer_cpf=cpf_digits)
                    s.add(command)
                    s.flush()
                    return self._to_info(s, command)
            except IntegrityError:      # dois terminais pegaram o mesmo número: tenta o próximo
                continue
        raise BusinessError("Não foi possível gerar uma nova comanda. Tente novamente.")

    # ------------------------------------------------------------------ consulta
    def find(self, raw_code: str) -> CommandInfo:
        code = normalize_code(raw_code)
        with self._db.session() as s:
            command = s.scalar(select(Command).where(Command.code == code)) if code else None
            if command is None:
                raise CommandNotFound(f"Comanda não cadastrada.\nCódigo: {raw_code.strip() or '(vazio)'}")
            return self._to_info(s, command)

    def get(self, command_id: int) -> CommandInfo:
        with self._db.session() as s:
            command = s.get(Command, command_id)
            if command is None:
                raise CommandNotFound("Comanda não cadastrada.")
            return self._to_info(s, command)

    def open_commands_by_cpf(self, cpf: str) -> list[CommandSummary]:
        """Comandas ainda não pagas do CPF (em atendimento ou aguardando pagamento)."""
        cpf_digits = only_digits(cpf)
        if not is_valid_cpf(cpf_digits):
            raise InvalidCpf("CPF inválido. Confira os números digitados.")
        active = (CommandStatus.OPEN, CommandStatus.AWAITING_PAYMENT)
        with self._db.session() as s:
            rows = s.scalars(select(Command).where(Command.customer_cpf == cpf_digits,
                                                   Command.status.in_(active))
                             .order_by(Command.id.desc())).all()
            return [self._to_summary(s, c) for c in rows]

    def list_awaiting_payment(self) -> list[CommandSummary]:
        with self._db.session() as s:
            rows = s.scalars(select(Command).where(Command.status == CommandStatus.AWAITING_PAYMENT)
                             .order_by(Command.closed_at, Command.id)).all()
            return [self._to_summary(s, c) for c in rows]

    def _load(self, s, command_id: int) -> Command:
        # with_for_update evita lançamentos/pagamentos simultâneos na mesma comanda (MySQL);
        # o SQLite ignora a cláusula.
        command = s.scalar(select(Command).where(Command.id == command_id).with_for_update())
        if command is None:
            raise CommandNotFound("Comanda não cadastrada.")
        return command

    @staticmethod
    def _require_open(command: Command) -> None:
        if command.status is not CommandStatus.OPEN:
            raise CommandClosed(f"A comanda {command.code} está encerrada.\n"
                                "Não é possível registrar novos consumos.")

    @staticmethod
    def _active_total(s, command_id: int) -> Decimal:
        total = s.scalar(select(func.coalesce(func.sum(Consumption.total_price), 0))
                         .where(Consumption.command_id == command_id,
                                Consumption.status == ConsumptionStatus.ACTIVE))
        return round_money(Decimal(total))

    @staticmethod
    def _paid_total(s, command_id: int) -> Decimal:
        paid = s.scalar(select(func.coalesce(func.sum(Payment.amount), 0))
                        .where(Payment.command_id == command_id))
        return round_money(Decimal(paid))

    def _to_summary(self, s, command: Command) -> CommandSummary:
        count = s.scalar(select(func.count(Consumption.id))
                         .where(Consumption.command_id == command.id,
                                Consumption.status == ConsumptionStatus.ACTIVE))
        return CommandSummary(command.id, command.code, command.status.value,
                              self._active_total(s, command.id), self._paid_total(s, command.id),
                              command.opened_at, command.closed_at, command.customer_cpf, int(count))

    @staticmethod
    def _to_info(s, command: Command) -> CommandInfo:
        rows = s.execute(
            select(Consumption, Product.description, Operator.name)
            .join(Product, Product.id == Consumption.product_id)
            .join(Operator, Operator.id == Consumption.operator_id)
            .where(Consumption.command_id == command.id)
            .order_by(Consumption.id)).all()
        items = tuple(ItemInfo(
            id=c.id, description=desc, type=c.type.value, quantity=c.quantity,
            weight_kg=c.weight_kg, unit_price=c.unit_price, total_price=c.total_price,
            status=c.status.value, created_at=c.created_at, operator_name=op_name,
            cancel_reason=c.cancel_reason) for c, desc, op_name in rows)
        total = sum((i.total_price for i in items if i.status == ConsumptionStatus.ACTIVE.value),
                    Decimal("0.00"))
        pay_rows = s.execute(
            select(Payment, Operator.name).join(Operator, Operator.id == Payment.operator_id)
            .where(Payment.command_id == command.id).order_by(Payment.id)).all()
        payments = tuple(PaymentInfo(p.id, p.method.value, p.amount, p.tendered, p.change_amount,
                                     p.reference, p.paid_at, name) for p, name in pay_rows)
        paid = sum((p.amount for p in payments), Decimal("0.00"))
        return CommandInfo(command.id, command.code, command.status.value, round_money(total), items,
                           round_money(paid), payments, command.customer_cpf, command.opened_at)

    def unit_products(self) -> list[ProductInfo]:
        with self._db.session() as s:
            products = s.scalars(select(Product).where(Product.active,
                                                       Product.type == ProductType.UNIT)
                                 .order_by(Product.code)).all()
            return [ProductInfo(p.id, p.code, p.description, p.type.value, p.unit,
                                self._pricing.current_price(p.code)) for p in products]

    # ------------------------------------------------------------------ lançamentos
    def add_weighed_consumption(self, command_id: int, operator_id: int, net_kg: Decimal,
                                tare_g: Optional[int] = None, raw_response: Optional[str] = None,
                                scale_id: Optional[int] = None) -> ItemInfo:
        """Registra a comida por quilo. O total é SEMPRE recalculado aqui, com o preço
        vigente; nunca se aceita um valor pronto da interface."""
        if net_kg is None or net_kg <= 0:
            raise InvalidWeight("Peso inválido. Verifique o prato da balança.")
        price = self._pricing.current_price(WEIGHED_PRODUCT_CODE)
        total = calculate_total(net_kg, price)
        tare_kg = (Decimal(tare_g) / 1000) if tare_g else None
        with self._db.session() as s:
            command = self._load(s, command_id)
            self._require_open(command)
            product = s.scalar(select(Product).where(Product.code == WEIGHED_PRODUCT_CODE))
            consumption = Consumption(
                command_id=command.id, product_id=product.id, type=ProductType.WEIGHT,
                quantity=Decimal("1"), weight_kg=net_kg, unit_price=price, total_price=total,
                tare_kg=tare_kg, operator_id=operator_id)
            s.add(consumption)
            s.flush()
            s.add(Weighing(
                consumption_id=consumption.id,
                # a balança só devolve o peso do display; o bruto só é conhecido se a
                # tara foi enviada por software
                gross_weight_kg=(net_kg + tare_kg) if tare_kg is not None else None,
                tare_weight_kg=tare_kg, net_weight_kg=net_kg, price_per_kg=price,
                total_price=total, scale_id=scale_id, raw_response=raw_response))
            operator = s.get(Operator, operator_id)
            return ItemInfo(consumption.id, product.description, "WEIGHT", Decimal("1"), net_kg,
                            price, total, ConsumptionStatus.ACTIVE.value, consumption.created_at
                            or datetime.now(), operator.name if operator else "")

    def add_unit_product(self, command_id: int, operator_id: int, product_code: str,
                         quantity: int = 1) -> ItemInfo:
        if quantity < 1:
            raise BusinessError("Quantidade inválida.")
        price = self._pricing.current_price(product_code)
        with self._db.session() as s:
            command = self._load(s, command_id)
            self._require_open(command)
            product = s.scalar(select(Product).where(Product.code == product_code))
            if product is None or product.type is not ProductType.UNIT:
                raise BusinessError("Produto inválido para lançamento por unidade.")
            total = round_money(price * quantity)
            consumption = Consumption(
                command_id=command.id, product_id=product.id, type=ProductType.UNIT,
                quantity=Decimal(quantity), unit_price=price, total_price=total,
                operator_id=operator_id)
            s.add(consumption)
            s.flush()
            operator = s.get(Operator, operator_id)
            return ItemInfo(consumption.id, product.description, "UNIT", Decimal(quantity), None,
                            price, total, ConsumptionStatus.ACTIVE.value, consumption.created_at
                            or datetime.now(), operator.name if operator else "")

    def cancel_consumption(self, consumption_id: int, operator_id: int, reason: str) -> None:
        """Nunca apaga: marca CANCELLED e guarda motivo, data e operador (RN005)."""
        reason = (reason or "").strip()
        if len(reason) < 3:
            raise BusinessError("Informe o motivo do cancelamento.")
        with self._db.session() as s:
            consumption = s.get(Consumption, consumption_id)
            if consumption is None:
                raise BusinessError("Lançamento não encontrado.")
            command = self._load(s, consumption.command_id)
            self._require_open(command)
            if consumption.status is ConsumptionStatus.CANCELLED:
                raise BusinessError("Lançamento já cancelado.")
            consumption.status = ConsumptionStatus.CANCELLED
            consumption.cancel_reason = reason
            consumption.cancelled_at = datetime.now()
            consumption.cancelled_by_id = operator_id
            if consumption.weighing is not None:
                consumption.weighing.status = "CANCELLED"

    # ------------------------------------------------------------------ ciclo da comanda
    def send_to_payment(self, command_id: int) -> CommandInfo:
        """Fecha os lançamentos e envia a comanda ao caixa (OPEN -> AWAITING_PAYMENT)."""
        with self._db.session() as s:
            command = self._load(s, command_id)
            self._require_open(command)
            if self._active_total(s, command.id) <= 0:
                raise BusinessError("A comanda não possui itens para pagar.")
            command.status = CommandStatus.AWAITING_PAYMENT
            command.closed_at = datetime.now()
            s.flush()
            return self._to_info(s, command)

    def reopen_command(self, command_id: int) -> CommandInfo:
        """Devolve ao atendimento uma comanda enviada ao caixa que ainda não recebeu pagamento
        (cliente desistiu de pagar, quer pegar mais algo etc.)."""
        with self._db.session() as s:
            command = self._load(s, command_id)
            if command.status is not CommandStatus.AWAITING_PAYMENT:
                raise BusinessError("Só é possível reabrir comandas que aguardam pagamento.")
            if self._paid_total(s, command.id) > 0:
                raise BusinessError("A comanda já recebeu pagamento parcial e não pode ser reaberta.")
            command.status = CommandStatus.OPEN
            command.closed_at = None
            s.flush()
            return self._to_info(s, command)

    def cancel_command(self, command_id: int, operator_id: int, reason: str = "",
                       only_if_empty: bool = False) -> None:
        with self._db.session() as s:
            command = self._load(s, command_id)
            if command.status is not CommandStatus.OPEN:
                raise BusinessError("Só é possível cancelar comandas em atendimento.")
            active = [c for c in command.consumptions if c.status is ConsumptionStatus.ACTIVE]
            if only_if_empty and active:
                raise BusinessError("A comanda já possui itens.")
            reason = (reason or "").strip() or ("Comanda vazia" if not active else "")
            if len(reason) < 3:
                raise BusinessError("Informe o motivo do cancelamento.")
            now = datetime.now()
            for consumption in active:
                consumption.status = ConsumptionStatus.CANCELLED
                consumption.cancel_reason = f"Comanda cancelada: {reason}"
                consumption.cancelled_at = now
                consumption.cancelled_by_id = operator_id
            command.status = CommandStatus.CANCELLED
            command.closed_at = now

    # ------------------------------------------------------------------ pagamento
    def register_payment(self, command_id: int, operator_id: int, method: str, amount: Decimal,
                         tendered: Optional[Decimal] = None,
                         reference: Optional[str] = None) -> CommandInfo:
        """Registra um pagamento (total ou parcial). Quando o restante zera, a comanda vira PAID.

        Uma comanda ainda em atendimento (OPEN) é enviada ao caixa no primeiro pagamento: quem
        lê a comanda na saída e paga não precisa de um passo separado. Dinheiro aceita valor
        recebido maior que o cobrado e calcula o troco."""
        try:
            method_enum = PaymentMethod(method)
        except ValueError:
            raise PaymentError("Forma de pagamento inválida.") from None
        amount = round_money(amount)
        if amount <= 0:
            raise PaymentError("O valor do pagamento deve ser maior que zero.")
        with self._db.session() as s:
            command = self._load(s, command_id)
            if command.status is CommandStatus.PAID:
                raise PaymentError(f"A comanda {command.code} já está paga.")
            if command.status not in (CommandStatus.OPEN, CommandStatus.AWAITING_PAYMENT):
                raise PaymentError(f"A comanda {command.code} não aceita pagamento.")
            total = self._active_total(s, command.id)
            if total <= 0:
                raise PaymentError("A comanda não possui itens para pagar.")
            remaining = total - self._paid_total(s, command.id)
            if amount > remaining:
                raise PaymentError(f"O valor excede o restante da comanda ({format_brl(remaining)}).")

            change = None
            if method_enum is PaymentMethod.CASH:
                tendered = round_money(tendered) if tendered is not None else amount
                if tendered < amount:
                    raise PaymentError("O valor recebido é menor que o valor a pagar.")
                change = tendered - amount
            else:
                tendered = None
            s.add(Payment(command_id=command.id, method=method_enum, amount=amount,
                          tendered=tendered, change_amount=change,
                          reference=(reference or "").strip()[:60] or None, operator_id=operator_id))
            if command.status is CommandStatus.OPEN:
                command.status = CommandStatus.AWAITING_PAYMENT
                command.closed_at = datetime.now()
            s.flush()
            if amount == remaining:
                command.status = CommandStatus.PAID
            s.flush()
            return self._to_info(s, command)

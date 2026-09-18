"""Valores monetários e de peso: sempre Decimal, nunca float (RNF007)."""
from decimal import Decimal, ROUND_HALF_UP

CENT = Decimal("0.01")
GRAM = Decimal("0.001")


def to_decimal(value) -> Decimal:
    """Converte str/int/Decimal (e "79,90") em Decimal. Rejeita float."""
    if isinstance(value, float):
        raise TypeError("float não é permitido em valores monetários; use str ou Decimal")
    if isinstance(value, str):
        value = value.strip().replace("R$", "").replace(" ", "").replace(",", ".")
    return Decimal(value)


def round_money(value: Decimal) -> Decimal:
    """Arredonda para 2 casas, sempre ROUND_HALF_UP (RN003)."""
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def calculate_total(weight_kg: Decimal, price_per_kg: Decimal) -> Decimal:
    return round_money(weight_kg * price_per_kg)


def format_brl(value: Decimal) -> str:
    """Decimal('1234.5') -> 'R$ 1.234,50'."""
    text = f"{round_money(value):,.2f}"
    return "R$ " + text.replace(",", "X").replace(".", ",").replace("X", ".")


def format_kg(value: Decimal) -> str:
    """Decimal('0.5') -> '0,500 kg'."""
    return f"{value.quantize(GRAM):.3f}".replace(".", ",") + " kg"

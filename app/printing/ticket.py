"""Comanda e comprovante para impressora térmica/comum.

`build_ticket` monta um modelo puro (testável); `render_text` dá a versão em texto; o
desenho no papel fica em `printer.py`."""
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Optional

from ..domain.cpf import mask_cpf
from ..domain.money import format_brl, format_kg
from ..domain.payment import METHOD_LABELS
from ..services.dto import CommandInfo

KIND_COMMAND = "comanda"
KIND_RECEIPT = "comprovante"


@dataclass
class Ticket:
    kind: str
    title: str
    heading: str
    code: str
    header_lines: list[str] = field(default_factory=list)
    rows: list[tuple[str, str]] = field(default_factory=list)     # itens (esquerda, direita)
    total: Optional[Decimal] = None
    payment_rows: list[tuple[str, str]] = field(default_factory=list)
    footer_lines: list[str] = field(default_factory=list)
    barcode: Optional[str] = None


def build_ticket(info: CommandInfo, kind: str, title: str = "RESTAURANTE",
                 now: Optional[datetime] = None) -> Ticket:
    now = now or datetime.now()
    ticket = Ticket(kind=kind, title=title, code=info.code,
                    heading="COMANDA" if kind == KIND_COMMAND else "COMPROVANTE")
    ticket.header_lines.append(now.strftime("%d/%m/%Y %H:%M"))
    if info.customer_cpf:
        ticket.header_lines.append(f"CPF {mask_cpf(info.customer_cpf)}")

    if kind == KIND_COMMAND:
        ticket.barcode = info.code
        ticket.footer_lines = ["Apresente esta comanda no caixa", "ao sair do restaurante.",
                               "Perdeu? Informe seu CPF no caixa."]
        return ticket

    for item in info.active_items:
        if item.weight_kg is not None:
            left = f"{item.description} {format_kg(item.weight_kg)}"
        else:
            left = f"{int(item.quantity)}x {item.description}"
        ticket.rows.append((left, format_brl(item.total_price)))
    ticket.total = info.total
    for pay in info.payments:
        ticket.payment_rows.append((METHOD_LABELS.get(pay.method, pay.method), format_brl(pay.amount)))
        if pay.change:
            ticket.payment_rows.append(("  Troco", format_brl(pay.change)))
    ticket.footer_lines = ["Obrigado pela preferência!"]
    return ticket


def render_text(ticket: Ticket, width: int = 42) -> str:
    """Prévia em texto monoespaçado (também usada nos testes)."""
    def row(left: str, right: str) -> str:
        if len(left) + len(right) < width:
            return f"{left}{' ' * (width - len(left) - len(right))}{right}"
        return f"{left[:width - len(right) - 1]} {right}"

    lines = [ticket.title.center(width), f"{ticket.heading} {ticket.code}".center(width),
             *[l.center(width) for l in ticket.header_lines], "-" * width]
    lines.extend(row(l, r) for l, r in ticket.rows)
    if ticket.total is not None:
        lines.append("-" * width)
        lines.append(row("TOTAL", format_brl(ticket.total)))
        lines.extend(row(l, r) for l, r in ticket.payment_rows)
    if ticket.barcode:
        lines.append(f"[código de barras: {ticket.barcode}]".center(width))
    lines.append("-" * width)
    lines.extend(l.center(width) for l in ticket.footer_lines)
    return "\n".join(lines)

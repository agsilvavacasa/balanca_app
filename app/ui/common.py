"""Trechos de interface compartilhados entre operador, autoatendimento e caixa."""
from decimal import Decimal
from typing import Iterable, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QAbstractItemView, QHeaderView, QTableWidget, QTableWidgetItem)

from ..domain.money import format_brl, format_kg
from ..services.dto import ItemInfo

# status da comanda -> (texto, tom do chip)
STATUS_VIEW = {
    "OPEN": ("COMANDA ABERTA", "ok"),
    "AWAITING_PAYMENT": ("AGUARDANDO PAGAMENTO", "warn"),
    "PAID": ("COMANDA PAGA", "info"),
    "CANCELLED": ("COMANDA CANCELADA", "error"),
    "CLOSED": ("COMANDA ENCERRADA", "muted"),
}

# mensagem para quem tenta usar uma comanda que não está mais em atendimento
NOT_OPEN_MESSAGE = {
    "AWAITING_PAYMENT": "Esta comanda já foi enviada ao caixa. Procure o caixa para pagar.",
    "PAID": "Esta comanda já foi paga.",
    "CANCELLED": "Esta comanda foi cancelada.",
    "CLOSED": "Esta comanda está encerrada.",
}


def quantity_text(item: ItemInfo) -> str:
    return format_kg(item.weight_kg) if item.weight_kg is not None else f"{int(item.quantity)} un"


def unit_price_text(item: ItemInfo) -> str:
    return format_brl(item.unit_price) + ("/kg" if item.type == "WEIGHT" else "")


class ItemsTable(QTableWidget):
    """Tabela somente leitura dos lançamentos de uma comanda."""

    HEADERS = ["ITEM", "PESO / QTD", "PREÇO", "TOTAL"]

    def __init__(self, row_height: int = 44, font_px: Optional[int] = None, parent=None):
        super().__init__(0, len(self.HEADERS), parent)
        self._row_height = row_height
        self.setHorizontalHeaderLabels(self.HEADERS)
        self.verticalHeader().setVisible(False)
        self.setShowGrid(False)
        self.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        head = self.horizontalHeader()
        head.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for i in (1, 2, 3):
            head.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
        for index in range(len(self.HEADERS)):
            header_item = self.horizontalHeaderItem(index)
            right = index > 0
            header_item.setTextAlignment((Qt.AlignmentFlag.AlignRight if right else Qt.AlignmentFlag.AlignLeft)
                                         | Qt.AlignmentFlag.AlignVCenter)
        if font_px:
            self.setStyleSheet(f"QTableWidget {{ font-size: {font_px}px; }}")

    def set_items(self, items: Iterable[ItemInfo], include_cancelled: bool = False) -> None:
        rows = [i for i in items if include_cancelled or i.status == "ACTIVE"]
        self.setRowCount(len(rows))
        for row, item in enumerate(rows):
            cancelled = item.status == "CANCELLED"
            cells = [item.description, quantity_text(item), unit_price_text(item),
                     format_brl(item.total_price)]
            for col, text in enumerate(cells):
                cell = QTableWidgetItem(text)
                if col:
                    cell.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                if cancelled:
                    font = QFont(cell.font())
                    font.setStrikeOut(True)
                    cell.setFont(font)
                    cell.setForeground(Qt.GlobalColor.gray)
                self.setItem(row, col, cell)
            self.setRowHeight(row, self._row_height)
        self.scrollToBottom()


def sum_items(items: Iterable[ItemInfo]) -> Decimal:
    return sum((i.total_price for i in items if i.status == "ACTIVE"), Decimal("0.00"))

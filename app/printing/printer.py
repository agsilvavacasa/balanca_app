"""Impressão de tickets via Qt (QPrinter): funciona com qualquer impressora instalada no
Windows, inclusive térmicas de bobina com driver, e também gera PDF (teste/fallback)."""
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QMarginsF, QRectF, QSizeF, Qt
from PySide6.QtGui import QFont, QFontDatabase, QPageLayout, QPageSize, QPainter
from PySide6.QtPrintSupport import QPrinter, QPrinterInfo

from ..config.settings import PrintSettings, config_dir
from .barcode import code128_modules
from .ticket import Ticket

DEFAULT_PRINTER = "@default"
MARGIN_MM = 3.0


@dataclass
class PrintResult:
    ok: bool
    destination: str             # nome da impressora ou caminho do PDF
    message: str = ""
    pdf_path: Optional[Path] = None


class TicketPrinter:
    def __init__(self, settings: PrintSettings):
        self.settings = settings

    # ------------------------------------------------------------------ destino
    def _pdf_dir(self) -> Path:
        path = Path(self.settings.pdf_dir) if self.settings.pdf_dir else config_dir() / "tickets"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _resolve_printer(self) -> Optional[str]:
        """Nome da impressora física a usar, ou None para gerar PDF."""
        name = self.settings.printer_name.strip()
        if not name:
            return None
        available = QPrinterInfo.availablePrinterNames()
        if name == DEFAULT_PRINTER:
            default = QPrinterInfo.defaultPrinterName()
            return default if default else None
        return name if name in available else None

    # ------------------------------------------------------------------ altura do rolo
    @staticmethod
    def _height_mm(ticket: Ticket) -> float:
        height = 8 + 6 + 8                       # título, cabeçalho da comanda, margens
        height += 5 * len(ticket.header_lines) + 4
        height += 6 * (len(ticket.rows) + len(ticket.payment_rows))
        height += 10 if ticket.total is not None else 0
        height += 30 if ticket.barcode else 0
        height += 5 * len(ticket.footer_lines) + 6
        return max(height, 60.0)

    # ------------------------------------------------------------------ impressão
    def print_ticket(self, ticket: Ticket) -> PrintResult:
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        physical = self._resolve_printer()
        pdf_path: Optional[Path] = None
        if physical:
            printer.setPrinterName(physical)
            destination = physical
        else:
            pdf_path = self._pdf_dir() / (
                f"{ticket.kind}_{ticket.code}_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.pdf")
            printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
            printer.setOutputFileName(str(pdf_path))
            destination = str(pdf_path)
        printer.setPageSize(QPageSize(QSizeF(self.settings.paper_width_mm, self._height_mm(ticket)),
                                      QPageSize.Unit.Millimeter))
        printer.setPageMargins(QMarginsF(MARGIN_MM, MARGIN_MM, MARGIN_MM, MARGIN_MM),
                               QPageLayout.Unit.Millimeter)
        painter = QPainter()
        if not painter.begin(printer):
            return PrintResult(False, destination, "Não foi possível iniciar a impressão.")
        try:
            self._draw(painter, printer, ticket)
        finally:
            painter.end()
        message = ""
        if not physical and self.settings.printer_name.strip():
            message = f"Impressora '{self.settings.printer_name}' não encontrada; gerado PDF."
        return PrintResult(True, destination, message, pdf_path)

    # ------------------------------------------------------------------ desenho
    def _draw(self, painter: QPainter, printer: QPrinter, ticket: Ticket) -> None:
        dpi = printer.resolution()
        mm = lambda v: v * dpi / 25.4                       # noqa: E731
        page = printer.pageRect(QPrinter.Unit.DevicePixel)
        width = page.width()
        y = 0.0

        mono = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont).family()

        def font(size: float, bold: bool = False, family: Optional[str] = None) -> QFont:
            f = QFont(family or mono)
            f.setPointSizeF(size)
            f.setBold(bold)
            return f

        def centered(text: str, size: float, bold: bool = False, gap: float = 1.5) -> None:
            nonlocal y
            painter.setFont(font(size, bold))
            h = painter.fontMetrics().height()
            painter.drawText(QRectF(0, y, width, h), Qt.AlignmentFlag.AlignCenter, text)
            y += h + mm(gap)

        def separator() -> None:
            nonlocal y
            painter.drawLine(0, int(y), int(width), int(y))
            y += mm(2)

        centered(ticket.title, 12, True, 1)
        centered(f"{ticket.heading} {ticket.code}", 15, True, 1.5)
        for line in ticket.header_lines:
            centered(line, 9, False, 0.5)
        y += mm(1)
        separator()

        painter.setFont(font(9))
        for left, right in ticket.rows:
            h = painter.fontMetrics().height()
            right_w = painter.fontMetrics().horizontalAdvance(right) + mm(1)
            elided = painter.fontMetrics().elidedText(left, Qt.TextElideMode.ElideRight,
                                                      int(width - right_w))
            painter.drawText(QRectF(0, y, width - right_w, h), Qt.AlignmentFlag.AlignLeft, elided)
            painter.drawText(QRectF(0, y, width, h), Qt.AlignmentFlag.AlignRight, right)
            y += h + mm(1)

        if ticket.total is not None:
            separator()
            from ..domain.money import format_brl
            painter.setFont(font(12, True))
            h = painter.fontMetrics().height()
            painter.drawText(QRectF(0, y, width, h), Qt.AlignmentFlag.AlignLeft, "TOTAL")
            painter.drawText(QRectF(0, y, width, h), Qt.AlignmentFlag.AlignRight,
                             format_brl(ticket.total))
            y += h + mm(2)
            painter.setFont(font(9))
            for left, right in ticket.payment_rows:
                h = painter.fontMetrics().height()
                painter.drawText(QRectF(0, y, width, h), Qt.AlignmentFlag.AlignLeft, left)
                painter.drawText(QRectF(0, y, width, h), Qt.AlignmentFlag.AlignRight, right)
                y += h + mm(1)

        if ticket.barcode:
            y += mm(2)
            modules = code128_modules(ticket.barcode)
            module_w = min(width / (len(modules) + 20), mm(0.5))     # margem de silêncio
            bars_w = module_w * len(modules)
            x0 = (width - bars_w) / 2
            bar_h = mm(16)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(Qt.GlobalColor.black)
            for i, bit in enumerate(modules):
                if bit == "1":
                    painter.drawRect(QRectF(x0 + i * module_w, y, module_w, bar_h))
            painter.setPen(Qt.GlobalColor.black)
            y += bar_h + mm(1)
            centered(ticket.barcode, 12, True, 2)

        y += mm(1)
        separator()
        for line in ticket.footer_lines:
            centered(line, 8, False, 0.5)

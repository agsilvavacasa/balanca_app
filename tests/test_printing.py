import os
from datetime import datetime
from decimal import Decimal

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from app.config.settings import PrintSettings
from app.printing.barcode import code128_modules
from app.printing.printer import TicketPrinter
from app.printing.ticket import KIND_COMMAND, KIND_RECEIPT, build_ticket, render_text
from app.services.dto import CommandInfo, ItemInfo, PaymentInfo

NOW = datetime(2026, 9, 18, 14, 38)


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _info():
    items = (ItemInfo(1, "REFRIGERANTE", "UNIT", Decimal(1), None, Decimal("8.00"), Decimal("8.00"),
                      "ACTIVE", NOW, "x"),
             ItemInfo(2, "COMIDA POR KG", "WEIGHT", Decimal(1), Decimal("0.500"), Decimal("79.90"),
                      Decimal("39.95"), "ACTIVE", NOW, "x"),
             ItemInfo(3, "ÁGUA", "UNIT", Decimal(1), None, Decimal("4.00"), Decimal("4.00"),
                      "CANCELLED", NOW, "x"))
    pay = (PaymentInfo(1, "CASH", Decimal("47.95"), Decimal("50.00"), Decimal("2.05"), None, NOW, "C"),)
    return CommandInfo(1, "000157", "PAID", Decimal("47.95"), items, Decimal("47.95"), pay,
                       "52998224725", NOW)


def test_command_ticket_has_barcode_and_masked_cpf_only():
    text = render_text(build_ticket(_info(), KIND_COMMAND, now=NOW))
    assert "COMANDA 000157" in text and "[código de barras: 000157]" in text
    assert "***.982.247-**" in text and "52998224725" not in text and "529.982" not in text


def test_receipt_lists_active_items_total_and_change():
    text = render_text(build_ticket(_info(), KIND_RECEIPT, now=NOW))
    assert "COMIDA POR KG 0,500 kg" in text and "R$ 39,95" in text
    assert "ÁGUA" not in text                                   # item cancelado não aparece
    assert "TOTAL" in text and "R$ 47,95" in text
    assert "Dinheiro" in text and "Troco" in text and "R$ 2,05" in text


def test_code128_modules_shape():
    bits = code128_modules("000157")
    assert set(bits) <= {"0", "1"} and bits.startswith("11010") and bits.endswith("1100011101011")


@pytest.mark.parametrize("kind", [KIND_COMMAND, KIND_RECEIPT])
def test_print_to_pdf(qapp, tmp_path, kind):
    result = TicketPrinter(PrintSettings(printer_name="", pdf_dir=str(tmp_path))).print_ticket(
        build_ticket(_info(), kind, now=NOW))
    assert result.ok and result.pdf_path.exists() and result.pdf_path.stat().st_size > 1000
    assert result.pdf_path.read_bytes().startswith(b"%PDF")


def test_missing_printer_falls_back_to_pdf(qapp, tmp_path):
    result = TicketPrinter(PrintSettings(printer_name="Impressora Que Nao Existe",
                                         pdf_dir=str(tmp_path))).print_ticket(
        build_ticket(_info(), KIND_COMMAND, now=NOW))
    assert result.ok and result.pdf_path and "não encontrada" in result.message

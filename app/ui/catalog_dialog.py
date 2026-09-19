"""Produtos e preços (só gerente). O PIN é conferido no servidor a cada alteração."""
from decimal import InvalidOperation
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
                               QTableWidget, QTableWidgetItem, QAbstractItemView, QHeaderView,
                               QVBoxLayout)

from ..domain.money import format_brl, to_decimal
from ..services.dto import ProductAdminInfo
from ..services.errors import BusinessError
from .dialogs import _button, _buttons_row

TYPE_LABEL = {"WEIGHT": "Por quilo", "UNIT": "Unidade"}


class ProductFormDialog(QDialog):
    """Pede nome e/ou preço. `name`/`price` = None esconde o campo."""

    def __init__(self, title: str, name: Optional[str] = None, price: Optional[str] = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(420)
        self.name_edit = QLineEdit(name or "")
        self.price_edit = QLineEdit(price or "")
        self.name_edit.setPlaceholderText("Ex.: SUCO DE LARANJA")
        self.price_edit.setPlaceholderText("Ex.: 7,50")
        self.name_edit.setMaxLength(40)
        self.value_name: str = ""
        self.value_price = None
        self._want_name, self._want_price = name is not None, price is not None
        form = QFormLayout()
        form.setSpacing(10)
        if self._want_name:
            form.addRow("Nome", self.name_edit)
        if self._want_price:
            form.addRow("Preço (R$)", self.price_edit)
        cancel = _button("CANCELAR")
        ok = _button("SALVAR", "primary")
        cancel.clicked.connect(self.reject)
        ok.clicked.connect(self._save)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)
        heading = QLabel(title)
        heading.setObjectName("appTitle")
        layout.addWidget(heading)
        layout.addLayout(form)
        layout.addLayout(_buttons_row(cancel, ok))

    def _save(self) -> None:
        if self._want_name:
            self.value_name = self.name_edit.text().strip()
            if len(self.value_name) < 2:
                QMessageBox.warning(self, "Nome", "Informe o nome do produto.")
                return
        if self._want_price:
            try:
                value = to_decimal(self.price_edit.text())
                if value <= 0:
                    raise InvalidOperation
            except (InvalidOperation, ValueError):
                QMessageBox.warning(self, "Preço", "Informe um preço maior que zero, ex.: 7,50")
                return
            self.value_price = value
        self.accept()


class CatalogDialog(QDialog):
    changed = Signal()          # avisa a tela de trás para recarregar preços e produtos

    def __init__(self, services, admin_pin: str, parent=None):
        super().__init__(parent)
        self.services = services
        self._pin = admin_pin
        self.products: list[ProductAdminInfo] = []
        self.setWindowTitle("Produtos e preços")
        self.setModal(True)
        self.resize(820, 520)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)
        heading = QLabel("Produtos e preços")
        heading.setObjectName("appTitle")
        hint = QLabel("Preço novo vale a partir de agora; comandas já lançadas não mudam. Produto desativado "
                      "some do autoatendimento, mas continua nas comandas antigas.")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        layout.addWidget(heading)
        layout.addWidget(hint)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["CÓDIGO", "PRODUTO", "TIPO", "PREÇO", "SITUAÇÃO"])
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        head = self.table.horizontalHeader()
        head.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for i in (0, 2, 3, 4):
            head.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
        self.table.itemSelectionChanged.connect(self._sync)
        layout.addWidget(self.table, 1)

        row = QHBoxLayout()
        self.new_btn = _button("Novo produto", "primary")
        self.price_btn = _button("Alterar preço")
        self.rename_btn = _button("Renomear")
        self.toggle_btn = _button("Desativar")
        close = _button("Fechar")
        self.new_btn.clicked.connect(self._create)
        self.price_btn.clicked.connect(self._price)
        self.rename_btn.clicked.connect(self._rename)
        self.toggle_btn.clicked.connect(self._toggle)
        close.clicked.connect(self.accept)
        for w in (self.new_btn, self.price_btn, self.rename_btn, self.toggle_btn):
            row.addWidget(w)
        row.addStretch(1)
        row.addWidget(close)
        layout.addLayout(row)
        self.reload()

    # ---------------------------------------------------------------- dados
    def reload(self) -> None:
        self.products = self.services.catalog.list_products(self._pin)
        self.table.setRowCount(len(self.products))
        for r, p in enumerate(self.products):
            cells = [p.code, p.description, TYPE_LABEL.get(p.type, p.type),
                     format_brl(p.price) + ("/kg" if p.type == "WEIGHT" else "") if p.price is not None else "sem preço",
                     "Ativo" if p.active else "Desativado"]
            for c, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if c == 3:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                if not p.active:
                    item.setForeground(Qt.GlobalColor.gray)
                self.table.setItem(r, c, item)
            self.table.setRowHeight(r, 40)
        self._sync()

    def selected(self) -> Optional[ProductAdminInfo]:
        rows = self.table.selectionModel().selectedRows()
        return self.products[rows[0].row()] if rows else None

    def _sync(self) -> None:
        p = self.selected()
        for b in (self.price_btn, self.rename_btn, self.toggle_btn):
            b.setEnabled(p is not None)
        if p is not None:
            self.toggle_btn.setText("Ativar" if not p.active else "Desativar")
            self.toggle_btn.setEnabled(not (p.type == "WEIGHT"))     # comida por kg não desativa

    def _run(self, action) -> None:
        try:
            action()
        except BusinessError as exc:
            QMessageBox.warning(self, "Não foi possível", str(exc))
            return
        self.reload()
        self.changed.emit()

    # ---------------------------------------------------------------- ações
    def _create(self) -> None:
        form = ProductFormDialog("Novo produto (por unidade)", name="", price="", parent=self)
        if form.exec() == form.DialogCode.Accepted:
            self._run(lambda: self.services.catalog.create_product(self._pin, form.value_name, form.value_price))

    def _price(self) -> None:
        p = self.selected()
        if p is None:
            return
        current = f"{p.price:.2f}".replace(".", ",") if p.price is not None else ""
        form = ProductFormDialog(f"Novo preço — {p.description}", price=current, parent=self)
        if form.exec() == form.DialogCode.Accepted:
            self._run(lambda: self.services.catalog.set_price(self._pin, p.code, form.value_price))

    def _rename(self) -> None:
        p = self.selected()
        if p is None:
            return
        form = ProductFormDialog("Renomear produto", name=p.description, parent=self)
        if form.exec() == form.DialogCode.Accepted:
            self._run(lambda: self.services.catalog.rename_product(self._pin, p.id, form.value_name))

    def _toggle(self) -> None:
        p = self.selected()
        if p is None:
            return
        if p.active:
            answer = QMessageBox.question(self, "Desativar produto",
                                          f"Desativar {p.description}? Ele some do autoatendimento.")
            if answer != QMessageBox.StandardButton.Yes:
                return
        self._run(lambda: self.services.catalog.set_active(self._pin, p.id, not p.active))

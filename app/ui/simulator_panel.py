from typing import Callable

from PySide6.QtWidgets import (QCheckBox, QGroupBox, QHBoxLayout, QLabel, QPushButton, QSpinBox,
                               QVBoxLayout)

from ..hardware.simulator import SimulatedSerial
from .dialogs import _button


def build_simulator_panel(sim: SimulatedSerial, notify: Callable[[str], None]) -> QGroupBox:
    """Controles para simular o que está sobre o prato da balança (modo sem hardware)."""
    box = QGroupBox("Simulador da balança (modo de teste)")
    lay = QVBoxLayout(box)
    lay.setSpacing(10)
    hint = QLabel("Sem hardware: simule o que estaria sobre o prato da balança.")
    hint.setObjectName("muted")
    hint.setWordWrap(True)
    lay.addWidget(hint)

    row = QHBoxLayout()
    name = QLabel("Peso sobre o prato")
    name.setObjectName("fieldLabel")
    spin = QSpinBox()
    spin.setRange(0, 40000)
    spin.setSingleStep(10)
    spin.setSuffix(" g")
    spin.setValue(sim.gross_g)
    spin.valueChanged.connect(sim.place_weight)
    row.addWidget(name)
    row.addStretch(1)
    row.addWidget(spin)
    lay.addLayout(row)

    presets = QHBoxLayout()
    for text, grams in (("Prato vazio (360 g)", 360), ("Prato + comida (860 g)", 860),
                        ("Tirar prato", 0)):
        btn = _button(text)
        btn.clicked.connect(lambda _=False, g=grams: spin.setValue(g))
        presets.addWidget(btn)
    lay.addLayout(presets)

    second = QHBoxLayout()
    tare_key = _button("Tecla TARA da balança")
    tare_key.clicked.connect(lambda: (sim.press_tare_key(), notify("Tara memorizada pela tecla da balança.")))
    unstable = QCheckBox("Balança instável")
    unstable.toggled.connect(lambda v: setattr(sim, "unstable", v))
    second.addWidget(tare_key)
    second.addStretch(1)
    second.addWidget(unstable)
    lay.addLayout(second)
    return box

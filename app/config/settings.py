"""Configuração persistida em JSON (a config da balança não é hardcoded — seção 18)."""
import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional


def config_dir() -> Path:
    override = os.environ.get("BALANCA_HOME")
    path = Path(override) if override else Path.home() / ".balanca_restaurante"
    path.mkdir(parents=True, exist_ok=True)
    return path


@dataclass
class ScaleSettings:
    mode: str = "simulated"        # "simulated" | "serial"
    manufacturer: str = "Toledo"
    model: str = "Prix 3 Fit"
    protocol: str = "Prt5"
    port: str = "COM3"
    baudrate: int = 9600           # precisa ser o mesmo configurado em C15 na balança
    data_bits: int = 8
    parity: str = "N"              # "N" nenhuma | "E" par
    stop_bits: int = 1
    timeout_s: float = 1.0
    poll_ms: int = 300
    stable_reads: int = 3          # leituras iguais consecutivas para considerar estável
    capacity_kg: str = "32.000"
    default_tare_g: int = 360
    send_price_to_scale: bool = False   # a fonte da verdade do preço é o sistema


@dataclass
class KioskSettings:
    fullscreen: bool = True
    auto_tare: bool = True               # aplica a tara padrão do prato ao iniciar o atendimento
    auto_register_after_s: int = 0       # 0 = o cliente confirma o prato com um toque
    require_cpf: bool = True             # CPF obrigatório para abrir comanda
    done_screen_s: int = 10              # tempo da tela final antes de voltar ao início
    idle_timeout_s: int = 90             # sem toque por este tempo, volta ao início (0 = nunca)


@dataclass
class CheckoutSettings:
    mode: str = "manual"                 # "manual" (operador no caixa) | "auto" (cliente paga no TEF)
    gateway: str = "simulated"           # "simulated" | "tef"
    auto_return_s: int = 12


@dataclass
class PrintSettings:
    printer_name: str = ""               # "" = só gera PDF (seguro p/ testes); "@default" = impressora
                                         # padrão do sistema; ou o nome exato da impressora
    paper_width_mm: int = 80
    pdf_dir: str = ""                    # vazio = <config>/tickets
    print_on_start: bool = True          # imprime a comanda ao abri-la
    print_receipt: bool = True           # imprime o comprovante após o pagamento
    title: str = "RESTAURANTE"


@dataclass
class ConnectionSettings:
    """Onde estão os dados deste PC: "" (ainda não escolhido), "local" ou "remote" (outro PC)."""
    mode: str = ""
    host: str = ""                       # IP do PC servidor
    port: int = 8765
    access_key: str = ""                 # código de pareamento mostrado no servidor


@dataclass
class ServerSettings:
    port: int = 8765
    access_key: str = ""                 # gerado no primeiro uso do servidor
    name: str = "Servidor"


@dataclass
class AppSettings:
    database_url: Optional[str] = None
    role: str = ""                       # "autoatendimento" | "operador" | "caixa" ("" = perguntar)
    scale: ScaleSettings = field(default_factory=ScaleSettings)
    kiosk: KioskSettings = field(default_factory=KioskSettings)
    checkout: CheckoutSettings = field(default_factory=CheckoutSettings)
    printing: PrintSettings = field(default_factory=PrintSettings)
    connection: ConnectionSettings = field(default_factory=ConnectionSettings)
    server: ServerSettings = field(default_factory=ServerSettings)

    @property
    def effective_database_url(self) -> str:
        return (os.environ.get("DATABASE_URL")
                or self.database_url
                or f"sqlite:///{config_dir() / 'balanca.db'}")


def _path() -> Path:
    return config_dir() / "config.json"


def load_settings() -> AppSettings:
    path = _path()
    if not path.exists():
        settings = AppSettings()
        save_settings(settings)
        return settings
    raw = json.loads(path.read_text(encoding="utf-8"))

    def section(cls, key):
        known = {k: v for k, v in raw.get(key, {}).items() if k in cls.__dataclass_fields__}
        return cls(**known)

    return AppSettings(database_url=raw.get("database_url"), role=raw.get("role", ""),
                       scale=section(ScaleSettings, "scale"), kiosk=section(KioskSettings, "kiosk"),
                       checkout=section(CheckoutSettings, "checkout"),
                       printing=section(PrintSettings, "printing"),
                       connection=section(ConnectionSettings, "connection"),
                       server=section(ServerSettings, "server"))


def save_settings(settings: AppSettings) -> None:
    _path().write_text(json.dumps(asdict(settings), indent=2, ensure_ascii=False), encoding="utf-8")

from dataclasses import dataclass
from typing import Optional

from .config.settings import AppSettings
from .database.connection import Database
from .database.seed import seed_if_empty
from .services.auth_service import AuthService
from .services.catalog_service import CatalogService
from .services.command_service import CommandService
from .services.pricing_service import PricingService


@dataclass
class Services:
    db: Optional[Database]      # None quando os dados estão em outro PC (cliente remoto)
    auth: AuthService
    pricing: PricingService
    commands: CommandService
    catalog: Optional[CatalogService] = None


def build_services(settings: AppSettings) -> Services:
    db = Database(settings.effective_database_url)
    db.create_all()
    seed_if_empty(db)
    pricing = PricingService(db)
    auth = AuthService(db)
    auth.self_service_operator()          # garante o operador técnico antes de vários terminais o pedirem
    return Services(db, auth, pricing, CommandService(db, pricing), CatalogService(db, pricing, auth))

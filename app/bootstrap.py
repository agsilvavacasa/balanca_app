from dataclasses import dataclass

from .config.settings import AppSettings
from .database.connection import Database
from .database.seed import seed_if_empty
from .services.auth_service import AuthService
from .services.command_service import CommandService
from .services.pricing_service import PricingService


@dataclass
class Services:
    db: Database
    auth: AuthService
    pricing: PricingService
    commands: CommandService


def build_services(settings: AppSettings) -> Services:
    db = Database(settings.effective_database_url)
    db.create_all()
    seed_if_empty(db)
    pricing = PricingService(db)
    return Services(db, AuthService(db), pricing, CommandService(db, pricing))

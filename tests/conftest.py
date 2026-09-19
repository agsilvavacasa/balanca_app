import pytest

from app.database.connection import Database
from app.database.seed import seed_if_empty
from app.services.auth_service import AuthService
from app.services.catalog_service import CatalogService
from app.services.command_service import CommandService
from app.services.pricing_service import PricingService


@pytest.fixture
def db(tmp_path):
    database = Database(f"sqlite:///{tmp_path / 'test.db'}")
    database.create_all()
    seed_if_empty(database)
    yield database
    database.dispose()


@pytest.fixture
def services(db):
    pricing = PricingService(db)
    auth = AuthService(db)
    return {"db": db, "pricing": pricing, "commands": CommandService(db, pricing), "auth": auth,
            "catalog": CatalogService(db, pricing, auth)}


@pytest.fixture
def operator(services):
    return services["auth"].authenticate(
        next(o.id for o in services["auth"].list_operators() if o.name == "Operador 1"), "1111")


@pytest.fixture
def selfservice(services):
    return services["auth"].self_service_operator()

import warnings
from contextlib import contextmanager

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from .migrations import apply_migrations
from .models import Base

# SQLite não tem Decimal nativo; o SQLAlchemy avisa, mas converte corretamente.
warnings.filterwarnings("ignore", message="Dialect sqlite.*does \\*not\\* support Decimal")


def make_engine(url: str) -> Engine:
    engine = create_engine(url, future=True, pool_pre_ping=True)
    if engine.dialect.name == "sqlite":
        @event.listens_for(engine, "connect")
        def _fk_on(dbapi_conn, _):
            dbapi_conn.execute("PRAGMA foreign_keys=ON")
    return engine


class Database:
    def __init__(self, url: str):
        self.engine = make_engine(url)
        self._factory = sessionmaker(self.engine, expire_on_commit=False, future=True)

    def dispose(self) -> None:
        """Fecha as conexões. Necessário no Windows para poder apagar/mover o arquivo SQLite."""
        self.engine.dispose()

    def create_all(self) -> None:
        Base.metadata.create_all(self.engine)
        apply_migrations(self.engine)

    @contextmanager
    def session(self):
        """Uma transação por bloco: commit no sucesso, rollback na exceção."""
        session: Session = self._factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

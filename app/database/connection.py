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
    # pool_recycle: o MySQL derruba conexões ociosas (wait_timeout); reciclar evita erro na manhã seguinte
    engine = create_engine(url, future=True, pool_pre_ping=True, pool_recycle=1800)
    if engine.dialect.name == "sqlite":
        @event.listens_for(engine, "connect")
        def _fk_on(dbapi_conn, _):
            dbapi_conn.execute("PRAGMA foreign_keys=ON")
            dbapi_conn.execute("PRAGMA journal_mode=WAL")      # leituras não bloqueiam a escrita
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


def check_connection(url: str, timeout_s: int = 5) -> tuple[bool, str]:
    """Abre uma conexão de verdade e roda SELECT 1. Devolve (ok, mensagem para o usuário)."""
    from sqlalchemy import text
    engine = None
    try:
        args = {"connect_timeout": timeout_s} if url.startswith("mysql") else {}
        engine = create_engine(url, connect_args=args, pool_pre_ping=True)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True, "Conexão estabelecida."
    except Exception as exc:
        first_line = str(exc).strip().splitlines()[0] if str(exc).strip() else exc.__class__.__name__
        return False, first_line[:300]
    finally:
        if engine is not None:
            engine.dispose()

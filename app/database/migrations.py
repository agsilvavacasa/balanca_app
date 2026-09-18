"""Migrações mínimas e idempotentes para bancos criados por versões anteriores.

`create_all` cria tabelas novas mas não altera as existentes; aqui entram as colunas
adicionadas depois da v1. Funciona em SQLite e MySQL."""
from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

# (tabela, coluna, DDL do tipo)
COLUMNS = [
    ("command", "customer_cpf", "VARCHAR(11)"),
]
INDEXES = [
    ("ix_command_customer_cpf", "command", "customer_cpf"),
]


def apply_migrations(engine: Engine) -> None:
    inspector = inspect(engine)
    with engine.begin() as conn:
        for table, column, ddl in COLUMNS:
            if table in inspector.get_table_names():
                existing = {c["name"] for c in inspector.get_columns(table)}
                if column not in existing:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))
    inspector = inspect(engine)
    with engine.begin() as conn:
        for name, table, column in INDEXES:
            if table in inspector.get_table_names():
                if name not in {i["name"] for i in inspector.get_indexes(table)}:
                    conn.execute(text(f"CREATE INDEX {name} ON {table} ({column})"))

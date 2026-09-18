"""Migração aditiva, idempotente e de endurecimento para a versão 0.4.0.

Execute a partir de backend com: .venv/Scripts/python scripts/migrate_security.py
O DATABASE_URL é lido do .env e nunca é impresso.
"""

from pathlib import Path
import sys

from sqlalchemy import inspect, text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import Base, engine  # noqa: E402
import app.models  # noqa: E402,F401


def migrate() -> None:
    if engine.dialect.name != "postgresql":
        raise SystemExit("Esta migração é destinada ao PostgreSQL. Em desenvolvimento, recrie o SQLite.")

    Base.metadata.create_all(engine)
    statements = [
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS failed_login_attempts INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS locked_until TIMESTAMP WITHOUT TIME ZONE NULL",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS password_changed_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS mfa_secret_encrypted VARCHAR(500) NULL",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS mfa_enabled BOOLEAN NOT NULL DEFAULT FALSE",
        "ALTER TABLE attachments ADD COLUMN IF NOT EXISTS storage_key VARCHAR(255) NULL",
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_attachments_storage_key ON attachments (storage_key)",
        "ALTER TABLE auth_sessions ADD COLUMN IF NOT EXISTS ip_address VARCHAR(64) NULL",
        "ALTER TABLE auth_sessions ADD COLUMN IF NOT EXISTS user_agent VARCHAR(300) NULL",
        "ALTER TABLE auth_sessions ADD COLUMN IF NOT EXISTS last_seen_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP",
    ]
    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))

    inspector = inspect(engine)
    table_names = inspector.get_table_names(schema="public")
    with engine.begin() as connection:
        for table_name in table_names:
            quoted = connection.dialect.identifier_preparer.quote(table_name)
            connection.execute(text(f"ALTER TABLE public.{quoted} ENABLE ROW LEVEL SECURITY"))
            connection.execute(text(f"REVOKE ALL PRIVILEGES ON TABLE public.{quoted} FROM anon, authenticated"))
        connection.execute(text("REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public FROM anon, authenticated"))
        connection.execute(text("ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON TABLES FROM anon, authenticated"))
        connection.execute(text("ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON SEQUENCES FROM anon, authenticated"))

    inspector = inspect(engine)
    required = {"auth_sessions", "auth_events", "auth_throttles", "checklist_templates", "checklist_items"}
    missing = required - set(inspector.get_table_names())
    user_columns = {column["name"] for column in inspector.get_columns("users")}
    session_columns = {column["name"] for column in inspector.get_columns("auth_sessions")}
    expected_users = {"failed_login_attempts", "locked_until", "password_changed_at", "mfa_secret_encrypted", "mfa_enabled"}
    expected_sessions = {"ip_address", "user_agent", "last_seen_at"}
    if missing or not expected_users.issubset(user_columns) or not expected_sessions.issubset(session_columns):
        raise RuntimeError(f"Migração incompleta. Tabelas ausentes: {sorted(missing)}")

    with engine.connect() as connection:
        exposed = connection.execute(text("""
            SELECT table_name FROM information_schema.role_table_grants
             WHERE table_schema = 'public' AND grantee IN ('anon', 'authenticated')
        """)).scalars().all()
        rls_disabled = connection.execute(text("""
            SELECT relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
             WHERE n.nspname = 'public' AND c.relkind = 'r' AND NOT c.relrowsecurity
        """)).scalars().all()
    if exposed or rls_disabled:
        raise RuntimeError(f"Endurecimento incompleto. Grants: {sorted(set(exposed))}; RLS desligado: {rls_disabled}")
    print("Migração 0.4.0 concluída: schema atualizado, RLS ligado e grants públicos revogados.")


if __name__ == "__main__":
    migrate()

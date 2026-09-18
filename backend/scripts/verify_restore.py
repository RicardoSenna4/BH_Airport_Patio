"""Restaura e verifica um dump somente em banco isolado explicitamente autorizado."""

import os
from pathlib import Path
import shutil
import subprocess

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url


def main() -> None:
    raw_url = os.environ.get("RESTORE_DATABASE_URL")
    backup = Path(os.environ.get("BACKUP_FILE", "")).resolve()
    confirmation = os.environ.get("ALLOW_ISOLATED_RESTORE")
    if not raw_url or not backup.is_file() or confirmation != "yes-isolated-only":
        raise SystemExit("Defina RESTORE_DATABASE_URL, BACKUP_FILE e ALLOW_ISOLATED_RESTORE=yes-isolated-only.")
    url = make_url(raw_url)
    database = (url.database or "").lower()
    if not any(marker in database for marker in ("restore", "test", "staging")):
        raise SystemExit("Proteção: o nome do banco isolado deve conter restore, test ou staging.")
    environment = os.environ.copy()
    if url.password:
        environment["PGPASSWORD"] = url.password
    pg_restore = shutil.which("pg_restore")
    if not pg_restore and os.name == "nt":
        candidates = sorted(Path("C:/Program Files/PostgreSQL").glob("*/bin/pg_restore.exe"), reverse=True)
        pg_restore = str(candidates[0]) if candidates else None
    if not pg_restore:
        raise SystemExit("pg_restore não encontrado; instale as ferramentas cliente do PostgreSQL.")
    command = [
        pg_restore, "--clean", "--if-exists", "--no-owner", "--no-acl",
        "--host", url.host or "localhost", "--port", str(url.port or 5432),
        "--username", url.username or "postgres", "--dbname", url.database,
        str(backup),
    ]
    subprocess.run(command, env=environment, check=True)
    engine = create_engine(raw_url, pool_pre_ping=True)
    required = {"users", "inspections", "inspection_answers", "occurrences", "audit_logs"}
    present = set(inspect(engine).get_table_names())
    missing = required - present
    if missing:
        raise SystemExit(f"Restauração incompleta; tabelas ausentes: {sorted(missing)}")
    with engine.connect() as connection:
        counts = {table: connection.execute(text(f'SELECT count(*) FROM "{table}"')).scalar_one() for table in sorted(required)}
    print(f"Restauração verificada em ambiente isolado. Contagens: {counts}")


if __name__ == "__main__":
    main()

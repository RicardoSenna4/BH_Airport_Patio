"""Gera um backup PostgreSQL customizado sem expor a senha na linha de comando."""

from datetime import UTC, datetime
import os
from pathlib import Path
import shutil
import subprocess
import sys

from sqlalchemy.engine import make_url

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings  # noqa: E402


def main() -> None:
    raw_url = os.environ.get("DATABASE_URL") or settings.database_url
    if not raw_url:
        raise SystemExit("Defina DATABASE_URL.")
    url = make_url(raw_url)
    if not url.drivername.startswith("postgresql"):
        raise SystemExit("DATABASE_URL deve apontar para PostgreSQL.")
    destination = Path(os.environ.get("BACKUP_DIR", "backups")).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    output = destination / f"aeroops-{datetime.now(UTC):%Y%m%dT%H%M%SZ}.dump"
    environment = os.environ.copy()
    if url.password:
        environment["PGPASSWORD"] = url.password
    pg_dump = shutil.which("pg_dump")
    if not pg_dump and os.name == "nt":
        candidates = sorted(Path("C:/Program Files/PostgreSQL").glob("*/bin/pg_dump.exe"), reverse=True)
        pg_dump = str(candidates[0]) if candidates else None
    if not pg_dump:
        raise SystemExit("pg_dump não encontrado; instale as ferramentas cliente do PostgreSQL.")
    command = [
        pg_dump, "--format=custom", "--no-owner", "--no-acl",
        "--host", url.host or "localhost", "--port", str(url.port or 5432),
        "--username", url.username or "postgres", "--file", str(output),
        url.database or "postgres",
    ]
    subprocess.run(command, env=environment, check=True)
    if output.stat().st_size == 0:
        output.unlink(missing_ok=True)
        raise SystemExit("Backup vazio; operação rejeitada.")
    print(f"Backup criado em {output} ({output.stat().st_size} bytes).")


if __name__ == "__main__":
    main()

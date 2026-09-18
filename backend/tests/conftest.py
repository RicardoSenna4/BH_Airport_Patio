import os
import shutil
import tempfile
from pathlib import Path

import pytest


_test_dir = Path(tempfile.mkdtemp(prefix="aeroops-tests-"))
_database_path = (_test_dir / "test.db").as_posix()
os.environ["ENVIRONMENT"] = "test"
os.environ["DATABASE_URL"] = f"sqlite:///{_database_path}"
os.environ["SECRET_KEY"] = "test-only-secret-key-with-more-than-32-characters"
os.environ["CORS_ORIGINS"] = "http://testserver"
os.environ["ALLOWED_HOSTS"] = "testserver,localhost,127.0.0.1"
os.environ["SEED_DEMO_USERS"] = "true"
os.environ["AUTO_CREATE_SCHEMA"] = "true"
os.environ["LOGIN_MAX_ATTEMPTS"] = "5"


@pytest.fixture(autouse=True)
def isolated_database():
    from app.database import Base, engine
    import app.main as main

    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    main.UPLOAD_DIR = _test_dir / "uploads"
    shutil.rmtree(main.UPLOAD_DIR, ignore_errors=True)
    main.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    main.seed_users()
    main.login_limiter.clear()
    yield


def pytest_sessionfinish(session, exitstatus):
    from app.database import engine

    engine.dispose()
    shutil.rmtree(_test_dir, ignore_errors=True)

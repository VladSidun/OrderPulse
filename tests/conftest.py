import os
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from alembic import command
from app.core.config import Settings
from app.db.session import create_database_engine
from app.main import create_app


@pytest.fixture
def client():
    settings = Settings(
        _env_file=None, app_env="testing", debug=False, secret_key=None, database_url=None
    )
    with TestClient(create_app(settings)) as test_client:
        yield test_client


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def db_engine():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL to run PostgreSQL integration tests")
    settings = Settings(_env_file=None, database_url=url)
    admin_engine = create_database_engine(settings)
    schema = "test_" + uuid4().hex
    with admin_engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(
        url,
        hide_parameters=True,
        connect_args={"options": f"-c timezone=UTC -c search_path={schema}"},
    )
    try:
        yield engine
    finally:
        engine.dispose()
        with admin_engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin_engine.dispose()


def migration_config(connection):
    config = Config(str(ROOT / "alembic.ini"))
    config.attributes["connection"] = connection
    return config


@pytest.fixture
def migrated_engine(db_engine):
    with db_engine.begin() as connection:
        command.upgrade(migration_config(connection), "head")
    return db_engine

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app


@pytest.fixture
def client():
    settings = Settings(_env_file=None, app_env="testing", debug=False)
    with TestClient(create_app(settings)) as test_client:
        yield test_client

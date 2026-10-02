from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app


def test_health_is_available_without_database(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["content-type"] == "application/json"


def test_home_renders_ukrainian_template_and_workspace_settings(client):
    response = client.get("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert '<html lang="uk">' in response.text
    assert "Облік замовлень" in response.text
    assert "EUR" in response.text
    assert "Europe/Kyiv" in response.text
    assert 'href="#main-content"' in response.text
    assert "/orders" not in response.text


def test_application_name_is_escaped_in_html():
    settings = Settings(_env_file=None, app_name='<script>alert("name")</script>')

    with TestClient(create_app(settings)) as client:
        response = client.get("/")

    assert "<script>alert" not in response.text
    assert "&lt;script&gt;" in response.text


def test_static_assets_resolve_independently_of_working_directory(client, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)

    assert client.get("/").status_code == 200
    response = client.get("/static/css/app.css")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/css")
    assert ".welcome-panel" in response.text


def test_development_documentation_contains_health_endpoint(client):
    assert client.get("/docs").status_code == 200
    schema = client.get("/openapi.json").json()

    assert "/health" in schema["paths"]
    assert "/" not in schema["paths"]


def test_production_disables_documentation_and_debug():
    settings = Settings(
        _env_file=None,
        app_env="production",
        debug=False,
        secret_key="production-test-key-with-at-least-32-characters",
    )

    with TestClient(create_app(settings)) as client:
        assert client.app.debug is False
        assert client.get("/health").status_code == 200
        assert client.get("/docs").status_code == 404
        assert client.get("/openapi.json").status_code == 404


def test_application_factories_keep_settings_separate():
    first = create_app(Settings(_env_file=None, app_name="Перший простір"))
    second = create_app(Settings(_env_file=None, app_name="Другий простір"))

    with TestClient(first) as first_client, TestClient(second) as second_client:
        assert "Перший простір" in first_client.get("/").text
        assert "Другий простір" in second_client.get("/").text
        assert "Другий простір" not in first_client.get("/").text


def test_business_routes_are_not_exposed_before_implementation(client):
    for path in ("/orders", "/clients", "/users/new", "/ready", "/api/v1/orders"):
        assert client.get(path).status_code == 404


def test_authentication_requires_explicit_secret_without_affecting_health(client):
    assert client.get("/login").status_code == 503
    assert client.get("/health").status_code == 200


def test_production_session_cookie_is_secure():
    settings = Settings(
        _env_file=None,
        app_env="production",
        debug=False,
        secret_key="production-test-secret-with-at-least-32-characters",
        database_url=None,
    )
    with TestClient(create_app(settings), base_url="https://testserver") as client:
        response = client.get("/login")
        assert response.status_code == 200
        assert "secure" in response.headers["set-cookie"]
        assert "httponly" in response.headers["set-cookie"]
        assert "samesite=lax" in response.headers["set-cookie"]


def test_login_without_database_returns_friendly_configuration_error():
    settings = Settings(
        _env_file=None,
        app_env="testing",
        database_url=None,
        secret_key="test-session-key-with-at-least-32-characters",
    )
    with TestClient(create_app(settings)) as client:
        response = client.get("/dashboard")
        assert response.status_code == 503
        assert "DATABASE_URL" in response.text
        assert client.get("/static/favicon.svg").status_code == 200

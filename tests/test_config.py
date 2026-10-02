import pytest
from pydantic import ValidationError

from app.core.config import Settings, get_settings


def test_settings_load_utf8_environment_file(tmp_path):
    environment_file = tmp_path / ".env"
    environment_file.write_text(
        'APP_NAME="Облік компанії"\n'
        "APP_ENV=testing\n"
        "DEBUG=false\n"
        "CURRENCY=EUR\n"
        "MANAGER_ORDER_VISIBILITY=assigned\n"
        "DATABASE_URL=\n"
        "SECRET_KEY=\n",
        encoding="utf-8",
    )

    settings = Settings(_env_file=environment_file)

    assert settings.app_name == "Облік компанії"
    assert settings.app_env == "testing"
    assert settings.debug is False
    assert settings.manager_order_visibility == "assigned"
    assert settings.database_url is None
    assert settings.secret_key is None


def test_environment_variables_override_dotenv(monkeypatch, tmp_path):
    environment_file = tmp_path / ".env"
    environment_file.write_text("APP_NAME=File value\n", encoding="utf-8")
    monkeypatch.setenv("APP_NAME", "Environment value")

    assert Settings(_env_file=environment_file).app_name == "Environment value"


@pytest.mark.parametrize(
    "values",
    [
        {"app_env": "invalid"},
        {"currency": "UAH"},
        {"manager_order_visibility": "everyone"},
        {"app_name": "   "},
        {"app_name": "x" * 101},
        {"app_timezone": "Invalid/Timezone"},
        {"app_timezone": "../Europe/Kyiv"},
        {"session_cookie_name": "cookie;name"},
    ],
)
def test_invalid_configuration_is_rejected(values):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **values)


@pytest.mark.parametrize("secret", [None, "", "change-me", "x" * 31])
def test_production_requires_a_sufficient_secret(secret):
    with pytest.raises(ValidationError, match="Production SECRET_KEY"):
        Settings(_env_file=None, app_env="production", debug=False, secret_key=secret)


def test_production_rejects_debug_mode():
    with pytest.raises(ValidationError, match="DEBUG must be false"):
        Settings(_env_file=None, app_env="production", debug=True, secret_key="x" * 32)


def test_secret_values_are_not_exposed_in_settings_repr():
    settings = Settings(
        _env_file=None,
        secret_key="local-test-secret",
        database_url="postgresql+psycopg://user:private-password@localhost/database",
    )

    assert "local-test-secret" not in repr(settings)
    assert "private-password" not in repr(settings)


def test_invalid_production_configuration_does_not_expose_secret_input():
    secret = "private-test-key-with-at-least-32-characters"
    with pytest.raises(ValidationError) as error:
        Settings(_env_file=None, app_env="production", debug=True, secret_key=secret)

    assert secret not in str(error.value)


def test_cached_settings_can_be_reloaded(monkeypatch):
    get_settings.cache_clear()
    try:
        monkeypatch.setenv("APP_NAME", "Перший простір")
        first = get_settings()
        monkeypatch.setenv("APP_NAME", "Другий простір")
        assert get_settings() is first

        get_settings.cache_clear()
        assert get_settings().app_name == "Другий простір"
    finally:
        get_settings.cache_clear()

from functools import lru_cache
from typing import Literal, Self
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        extra="ignore",
        hide_input_in_errors=True,
        str_strip_whitespace=True,
    )

    app_name: str = Field(default="Система обліку замовлень", min_length=1, max_length=100)
    app_env: Literal["development", "testing", "production"] = "development"
    debug: bool = False
    secret_key: SecretStr | None = None
    database_url: SecretStr | None = None
    session_cookie_name: str = Field(default="order_session", pattern=r"^[A-Za-z0-9_-]+$")
    app_timezone: str = "Europe/Kyiv"
    currency: Literal["EUR"] = "EUR"
    manager_order_visibility: Literal["all", "assigned"] = "all"

    @field_validator("app_timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("APP_TIMEZONE must be a valid IANA time zone") from exc
        return value

    @model_validator(mode="after")
    def validate_production(self) -> Self:
        if self.app_env == "production":
            if self.debug:
                raise ValueError("DEBUG must be false in production")
            if self.secret_key is None or len(self.secret_key.get_secret_value()) < 32:
                raise ValueError("Production SECRET_KEY must contain at least 32 characters")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()

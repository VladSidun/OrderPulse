from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models import OrderStatus


class VersionInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    version: int = Field(gt=0)

    @field_validator("version", mode="before")
    @classmethod
    def integer_version(cls, value):
        if isinstance(value, (bool, float)):
            raise ValueError("Версія має бути цілим числом.")
        return value


class StatusChange(VersionInput):
    status: OrderStatus
    comment: str | None = Field(default=None, max_length=2000)

    @field_validator("comment", mode="before")
    @classmethod
    def empty_comment(cls, value):
        return None if isinstance(value, str) and not value.strip() else value

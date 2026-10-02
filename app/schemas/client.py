from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class ClientInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=2, max_length=160)
    phone: str | None = Field(default=None, max_length=50)
    email: EmailStr | None = Field(default=None, max_length=255)
    address: str | None = Field(default=None, max_length=255)
    note: str | None = Field(default=None, max_length=2000)

    @field_validator("phone", "email", "address", "note", mode="before")
    @classmethod
    def empty_to_none(cls, value):
        return None if isinstance(value, str) and not value.strip() else value

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value):
        return value.lower() if value else None

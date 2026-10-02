from pydantic import BaseModel, EmailStr, Field, SecretStr, field_validator


class LoginInput(BaseModel):
    email: EmailStr = Field(max_length=255)
    password: SecretStr = Field(min_length=8, max_length=128)

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.strip().lower()


class AdminSeedInput(LoginInput):
    first_name: str = Field(min_length=2, max_length=80)
    last_name: str = Field(min_length=2, max_length=80)

    @field_validator("first_name", "last_name", mode="before")
    @classmethod
    def strip_name(cls, value: str) -> str:
        return value.strip()

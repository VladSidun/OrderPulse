from pydantic import BaseModel, ConfigDict, EmailStr, Field, SecretStr, field_validator

from app.models import UserRole


class UserUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    first_name: str = Field(min_length=2, max_length=80)
    last_name: str = Field(min_length=2, max_length=80)
    role: UserRole
    is_active: bool = True


class UserCreate(UserUpdate):
    email: EmailStr = Field(max_length=255)
    password: SecretStr = Field(min_length=8, max_length=128)

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, value):
        return value.strip().lower() if isinstance(value, str) else value


class PasswordReset(BaseModel):
    model_config = ConfigDict(extra="forbid")
    password: SecretStr = Field(min_length=8, max_length=128)

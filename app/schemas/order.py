from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models import OrderPriority

CENT = Decimal("0.01")
MAX_MONEY = Decimal("9999999999.99")


class ItemInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=200)
    quantity: Decimal = Field(gt=0, le=Decimal("99999999.99"))
    unit_price: Decimal = Field(ge=0, le=MAX_MONEY)

    @field_validator("quantity", "unit_price", mode="before")
    @classmethod
    def exact_decimal(cls, value):
        if isinstance(value, (float, bool)):
            raise ValueError("Використовуйте десятковий рядок, а не float.")
        try:
            number = Decimal(value)
        except (ValueError, TypeError, ArithmeticError) as exc:
            raise ValueError("Введіть десяткове число.") from exc
        if not number.is_finite() or number.as_tuple().exponent < -2:
            raise ValueError(
                "Число має бути скінченним і містити не більше двох десяткових знаків."
            )
        return number

    @model_validator(mode="after")
    def valid_line(self):
        if self.line_total > MAX_MONEY:
            raise ValueError("Сума позиції перевищує місткість numeric(12,2).")
        return self

    @property
    def line_total(self) -> Decimal:
        return (self.quantity * self.unit_price).quantize(CENT, rounding=ROUND_HALF_UP)


class OrderInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    client_id: int = Field(gt=0)
    manager_id: int | None = Field(default=None, gt=0)
    priority: OrderPriority = OrderPriority.NORMAL
    deadline_at: datetime | None = None
    comment: str | None = Field(default=None, max_length=2000)
    items: list[ItemInput] = Field(min_length=1, max_length=100)

    @field_validator("client_id", "manager_id", mode="before")
    @classmethod
    def valid_id(cls, value):
        if isinstance(value, (bool, float)):
            raise ValueError("Введіть цілий ідентифікатор.")
        return value

    @field_validator("deadline_at")
    @classmethod
    def aware_deadline(cls, value):
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("Дата має містити часовий пояс.")
        return value

    @field_validator("comment", mode="before")
    @classmethod
    def empty_comment(cls, value):
        return None if isinstance(value, str) and not value.strip() else value

    @model_validator(mode="after")
    def valid_total(self):
        if self.total_amount > MAX_MONEY:
            raise ValueError("Загальна сума перевищує місткість numeric(12,2).")
        return self

    @property
    def total_amount(self) -> Decimal:
        return sum((item.line_total for item in self.items), Decimal("0.00"))


class OrderUpdate(OrderInput):
    version: int = Field(gt=0)

    @field_validator("version", mode="before")
    @classmethod
    def valid_version(cls, value):
        if isinstance(value, (bool, float)):
            raise ValueError("Версія має бути цілим числом.")
        return value

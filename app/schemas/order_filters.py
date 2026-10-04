from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models import OrderPriority, OrderStatus


class OrderFilters(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    q: str = Field(default="", max_length=200)
    status: OrderStatus | None = None
    manager_id: int | None = Field(default=None, gt=0)
    priority: OrderPriority | None = None
    overdue: bool = False
    start_date: date | None = None
    end_date: date | None = None
    sort: Literal["created_at", "deadline_at", "total_amount"] = "created_at"
    direction: Literal["asc", "desc"] = "desc"
    page: int = Field(default=1, ge=1, le=2147483647)
    page_size: Literal[10, 20, 50] = 20
    archived: bool = False

    @field_validator("status", "manager_id", "priority", "start_date", "end_date", mode="before")
    @classmethod
    def optional_filter(cls, value):
        return None if value == "" else value

    @field_validator("page_size", mode="before")
    @classmethod
    def integer_size(cls, value):
        if isinstance(value, str) and value in {"10", "20", "50"}:
            return int(value)
        return value

    @model_validator(mode="after")
    def date_range(self):
        if self.start_date and self.end_date and self.start_date > self.end_date:
            raise ValueError("Початкова дата не може бути пізнішою за кінцеву.")
        if self.end_date == date.max:
            raise ValueError("Оберіть кінцеву дату раніше 31.12.9999.")
        return self

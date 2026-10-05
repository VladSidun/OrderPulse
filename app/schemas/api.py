from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models import OrderPriority, OrderStatus
from app.schemas.client import ClientInput
from app.schemas.order import MAX_MONEY, ItemInput, OrderInput
from app.schemas.workflow import VersionInput


class OrderCreate(OrderInput):
    """The same complete input used by the HTML order form."""


class OrderPatch(VersionInput):
    client_id: int | None = Field(default=None, gt=0)
    manager_id: int | None = Field(default=None, gt=0)
    priority: OrderPriority | None = None
    deadline_at: datetime | None = None
    comment: str | None = Field(default=None, max_length=2000)
    items: list[ItemInput] | None = Field(default=None, min_length=1, max_length=100)

    @field_validator("client_id", "manager_id", mode="before")
    @classmethod
    def valid_id(cls, value):
        return OrderInput.valid_id(value)

    @field_validator("client_id", "priority", "items")
    @classmethod
    def nonnullable(cls, value):
        if value is None:
            raise ValueError("Це поле не може бути null.")
        return value

    @field_validator("deadline_at")
    @classmethod
    def aware_deadline(cls, value):
        return OrderInput.aware_deadline(value)

    @field_validator("comment", mode="before")
    @classmethod
    def empty_comment(cls, value):
        return OrderInput.empty_comment(value)

    @model_validator(mode="after")
    def valid_total(self):
        if (
            self.items is not None
            and sum((item.line_total for item in self.items), Decimal("0")) > MAX_MONEY
        ):
            raise ValueError("Загальна сума перевищує місткість numeric(12,2).")
        return self


class ClientPatch(ClientInput):
    name: str | None = Field(default=None, min_length=2, max_length=160)

    @field_validator("name")
    @classmethod
    def nonnullable_name(cls, value):
        if value is None:
            raise ValueError("Назва не може бути null.")
        return value


class ReadModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class ClientRead(ReadModel):
    id: int
    name: str
    phone: str | None
    email: str | None
    address: str | None
    note: str | None
    created_at: datetime
    updated_at: datetime


class ClientPage(BaseModel):
    items: list[ClientRead]
    total: int
    page: int
    page_size: int


class ClientFilters(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    q: str = Field(default="", max_length=160)
    page: int = Field(default=1, ge=1, le=2147483647)
    page_size: Literal[10, 20, 50] = 20

    @field_validator("page_size", mode="before")
    @classmethod
    def integer_size(cls, value):
        return int(value) if value in {"10", "20", "50"} else value


class ClientBrief(ReadModel):
    id: int
    name: str


class UserBrief(ReadModel):
    id: int
    first_name: str
    last_name: str


class ItemRead(ReadModel):
    id: int
    name: str
    quantity: Decimal
    unit_price: Decimal
    line_total: Decimal


class HistoryRead(ReadModel):
    id: int
    old_status: OrderStatus | None
    new_status: OrderStatus
    changed_by: UserBrief
    comment: str | None
    changed_at: datetime


class OrderSummary(ReadModel):
    id: int
    number: str
    client_id: int
    manager_id: int
    client: ClientBrief
    manager: UserBrief
    status: OrderStatus
    priority: OrderPriority
    deadline_at: datetime | None
    total_amount: Decimal
    currency: Literal["EUR"] = "EUR"
    is_archived: bool
    version: int
    created_at: datetime
    updated_at: datetime


class OrderRead(OrderSummary):
    comment: str | None
    items: list[ItemRead]
    status_history: list[HistoryRead]


class OrderPage(BaseModel):
    items: list[OrderSummary]
    total: int
    page: int
    page_size: int


class CsrfRead(BaseModel):
    csrf_token: str


class ErrorRead(BaseModel):
    detail: str

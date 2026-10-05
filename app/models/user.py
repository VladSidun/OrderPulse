from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Boolean, CheckConstraint, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

from app.db.base import Base, TimestampMixin
from app.models.enums import UserRole, enum_column

if TYPE_CHECKING:
    from app.models.order import Order
    from app.models.order_status_history import OrderStatusHistory


class User(TimestampMixin, Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(
            "email = lower(btrim(email)) AND length(email) > 0", name="email_normalized"
        ),
        CheckConstraint("auth_version > 0", name="auth_version_positive"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    first_name: Mapped[str] = mapped_column(String(80))
    last_name: Mapped[str] = mapped_column(String(80))
    email: Mapped[str] = mapped_column(String(255), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[UserRole] = mapped_column(enum_column(UserRole, "user_role"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    auth_version: Mapped[int] = mapped_column(Integer, default=1, server_default=text("1"))

    orders: Mapped[list[Order]] = relationship(back_populates="manager", passive_deletes="all")
    status_changes: Mapped[list[OrderStatusHistory]] = relationship(
        back_populates="changed_by", passive_deletes="all"
    )

    @validates("email")
    def normalize_email(self, key: str, value: str) -> str:
        return value.strip().lower()

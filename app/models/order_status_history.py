from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import OrderStatus, enum_column

if TYPE_CHECKING:
    from app.models.order import Order
    from app.models.user import User


class OrderStatusHistory(Base):
    __tablename__ = "order_status_history"
    __table_args__ = (
        CheckConstraint("old_status IS NOT NULL OR new_status = 'NEW'", name="initial_status"),
        Index("ix_order_status_history_order_time", "order_id", "changed_at", "id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id", ondelete="RESTRICT"))
    old_status: Mapped[OrderStatus | None] = mapped_column(
        enum_column(OrderStatus, "history_old_status")
    )
    new_status: Mapped[OrderStatus] = mapped_column(enum_column(OrderStatus, "history_new_status"))
    changed_by_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    comment: Mapped[str | None] = mapped_column(Text)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    order: Mapped[Order] = relationship(back_populates="status_history")
    changed_by: Mapped[User] = relationship(back_populates="status_changes")

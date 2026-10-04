from datetime import datetime

from sqlalchemy import and_

from app.models import Order, OrderStatus

TERMINAL_STATUSES = (OrderStatus.COMPLETED, OrderStatus.CANCELLED)


def overdue_condition(now: datetime):
    return and_(
        Order.deadline_at < now,
        Order.status.not_in(TERMINAL_STATUSES),
        Order.is_archived.is_(False),
    )


def is_overdue(order: Order, now: datetime) -> bool:
    return bool(
        not order.is_archived
        and order.status not in TERMINAL_STATUSES
        and order.deadline_at is not None
        and order.deadline_at < now
    )

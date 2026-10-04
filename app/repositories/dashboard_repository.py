from sqlalchemy import func, select
from sqlalchemy.orm import joinedload

from app.core.business_time import month_bounds
from app.core.order_rules import TERMINAL_STATUSES, overdue_condition
from app.models import Order, OrderStatus, OrderStatusHistory
from app.repositories.order_repository import visible_statement


def snapshot(session, user, visibility, now):
    visible = visible_statement(user, visibility)
    grouped = session.execute(
        visible.with_only_columns(
            Order.status, func.count(), func.count().filter(overdue_condition(now))
        ).group_by(Order.status)
    ).all()
    by_status = {status: 0 for status in OrderStatus}
    overdue = 0
    for status, count, overdue_count in grouped:
        by_status[status] = count
        overdue += overdue_count
    lower, upper = month_bounds(now)
    completed_in_month = (
        select(OrderStatusHistory.id)
        .where(
            OrderStatusHistory.order_id == Order.id,
            OrderStatusHistory.new_status == OrderStatus.COMPLETED,
            OrderStatusHistory.changed_at >= lower,
            OrderStatusHistory.changed_at < upper,
        )
        .exists()
    )
    completed = session.scalar(
        select(func.count()).select_from(
            visible.where(Order.status == OrderStatus.COMPLETED, completed_in_month).subquery()
        )
    )
    related = visible.options(joinedload(Order.client), joinedload(Order.manager))
    recent = session.scalars(
        related.order_by(Order.created_at.desc(), Order.id.desc()).limit(10)
    ).all()
    upcoming = session.scalars(
        related.where(Order.status.not_in(TERMINAL_STATUSES), Order.deadline_at > now)
        .order_by(Order.deadline_at.asc(), Order.id.asc())
        .limit(5)
    ).all()
    return {
        "total": sum(by_status.values()),
        "new": by_status[OrderStatus.NEW],
        "in_progress": by_status[OrderStatus.IN_PROGRESS],
        "ready": by_status[OrderStatus.READY],
        "completed_month": completed,
        "overdue": overdue,
        "by_status": by_status,
        "recent": recent,
        "upcoming": upcoming,
    }

from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import joinedload

from app.core.business_time import calendar_bounds
from app.models import Order, OrderStatus, OrderStatusHistory, UserRole


def completion_time():
    return (
        select(func.min(OrderStatusHistory.changed_at))
        .where(
            OrderStatusHistory.order_id == Order.id,
            OrderStatusHistory.new_status == OrderStatus.COMPLETED,
        )
        .correlate(Order)
        .scalar_subquery()
    )


def statement(user, visibility, filters):
    query = select(Order, completion_time().label("completed_at"))
    if not filters.include_archived:
        query = query.where(Order.is_archived.is_(False))
    if user.role == UserRole.MANAGER and visibility == "assigned":
        query = query.where(Order.manager_id == user.id)
    if filters.status:
        query = query.where(Order.status == filters.status)
    if filters.manager_id is not None:
        query = query.where(Order.manager_id == filters.manager_id)
    basis = Order.created_at if filters.date_basis == "created" else completion_time()
    if filters.date_basis == "completed":
        query = query.where(basis.is_not(None))
    lower, upper = calendar_bounds(filters.start_date, filters.end_date)
    if lower:
        query = query.where(basis >= lower)
    if upper:
        query = query.where(basis < upper)
    return query


def summary(session, query):
    selected = query.subquery()
    total, amount = session.execute(
        select(
            func.count(), func.coalesce(func.sum(selected.c.total_amount), Decimal("0.00"))
        ).select_from(selected)
    ).one()
    return total, amount


def rows(session, query, *, page=None, page_size=20):
    query = query.options(joinedload(Order.client), joinedload(Order.manager)).order_by(
        Order.created_at.desc(), Order.id.desc()
    )
    if page is not None:
        query = query.offset((page - 1) * page_size).limit(page_size)
    return session.execute(query).all()

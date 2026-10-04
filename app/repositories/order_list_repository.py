from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload

from app.core.business_time import calendar_bounds
from app.core.order_rules import overdue_condition
from app.models import Client, Order, User, UserRole
from app.repositories.order_repository import visible_statement
from app.schemas.order_filters import OrderFilters


def filtered_statement(user: User, visibility: str, filters: OrderFilters, now):
    statement = visible_statement(user, visibility, archived=filters.archived)
    if filters.q:
        pattern = (
            "%" + filters.q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        )
        statement = statement.join(Order.client).where(
            or_(Order.number.ilike(pattern, escape="\\"), Client.name.ilike(pattern, escape="\\"))
        )
    for field in ("status", "manager_id", "priority"):
        value = getattr(filters, field)
        if value is not None:
            statement = statement.where(getattr(Order, field) == value)
    if filters.overdue:
        statement = statement.where(overdue_condition(now))
    lower, upper = calendar_bounds(filters.start_date, filters.end_date)
    if lower:
        statement = statement.where(Order.created_at >= lower)
    if upper:
        statement = statement.where(Order.created_at < upper)
    return statement


def search(session: Session, user: User, visibility: str, filters: OrderFilters, now):
    statement = filtered_statement(user, visibility, filters, now)
    total = session.scalar(select(func.count()).select_from(statement.subquery()))
    pages = max(1, (total + filters.page_size - 1) // filters.page_size)
    page = min(filters.page, pages)
    column = getattr(Order, filters.sort)
    sort = column.asc() if filters.direction == "asc" else column.desc()
    tie_break = Order.id.asc() if filters.direction == "asc" else Order.id.desc()
    rows = session.scalars(
        statement.options(joinedload(Order.client), joinedload(Order.manager))
        .order_by(sort.nulls_last(), tie_break)
        .offset((page - 1) * filters.page_size)
        .limit(filters.page_size)
    ).all()
    return rows, total, page, pages


def managers(session: Session):
    # Historical assignments remain filterable after a manager is deactivated or changes role.
    return session.scalars(
        select(User)
        .where(or_(User.role == UserRole.MANAGER, User.orders.any()))
        .order_by(User.last_name, User.id)
    ).all()

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload

from app.models import Client, Order, User, UserRole


def get(session: Session, client_id: int, *, lock: bool = False) -> Client | None:
    if lock:
        return session.scalar(
            select(Client)
            .where(Client.id == client_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    return session.get(Client, client_id)


def search(session: Session, query: str, page: int, page_size: int):
    statement = select(Client)
    if query:
        pattern = "%" + query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        statement = statement.where(
            or_(
                *(
                    field.ilike(pattern, escape="\\")
                    for field in (Client.name, Client.email, Client.phone)
                )
            )
        )
    total = session.scalar(select(func.count()).select_from(statement.subquery()))
    rows = session.scalars(
        statement.order_by(Client.name, Client.id).offset((page - 1) * page_size).limit(page_size)
    ).all()
    return rows, total


def visible_orders(session: Session, client_id: int, user: User, visibility: str):
    statement = select(Order).where(Order.client_id == client_id, Order.is_archived.is_(False))
    if user.role == UserRole.MANAGER and visibility == "assigned":
        statement = statement.where(Order.manager_id == user.id)
    return session.scalars(
        statement.options(joinedload(Order.manager)).order_by(
            Order.created_at.desc(), Order.id.desc()
        )
    ).all()

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, joinedload, selectinload

from app.models import Client, Order, OrderNumberCounter, OrderStatusHistory, User, UserRole


def visible_statement(user: User, visibility: str, *, archived: bool = False):
    statement = select(Order).where(Order.is_archived.is_(archived))
    if user.role == UserRole.MANAGER and visibility == "assigned":
        statement = statement.where(Order.manager_id == user.id)
    return statement


def list_recent(session: Session, user: User, visibility: str, *, archived: bool = False):
    return session.scalars(
        visible_statement(user, visibility, archived=archived)
        .options(joinedload(Order.client), joinedload(Order.manager))
        .order_by(Order.created_at.desc(), Order.id.desc())
        .limit(20)
    ).all()


def get(session: Session, order_id: int, *, lock: bool = False):
    statement = (
        select(Order)
        .where(Order.id == order_id)
        .execution_options(populate_existing=True)
        .options(
            joinedload(Order.client),
            joinedload(Order.manager),
            selectinload(Order.items),
            selectinload(Order.status_history).joinedload(OrderStatusHistory.changed_by),
        )
    )
    if lock:
        statement = statement.with_for_update(of=Order).execution_options(populate_existing=True)
    return session.scalar(statement)


def next_number(session: Session, year: int) -> str:
    counter = OrderNumberCounter
    statement = (
        insert(counter)
        .values(year=year, last_value=1)
        .on_conflict_do_update(
            index_elements=[counter.year], set_={"last_value": counter.last_value + 1}
        )
        .returning(counter.last_value)
    )
    value = session.scalar(statement)
    return f"ORD-{year:04}-{value:04}"


def active_manager(session: Session, manager_id: int):
    return session.scalar(
        select(User)
        .where(User.id == manager_id)
        .with_for_update(read=True)
        .execution_options(populate_existing=True)
    )


def choices(session: Session):
    clients = session.scalars(select(Client).order_by(Client.name, Client.id)).all()
    managers = session.scalars(
        select(User)
        .where(User.role == UserRole.MANAGER, User.is_active.is_(True))
        .order_by(User.last_name, User.id)
    ).all()
    return clients, managers

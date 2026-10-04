from sqlalchemy import func, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import Order, OrderStatus, User, UserRole


def list_all(session: Session):
    return session.scalars(select(User).order_by(User.last_name, User.first_name, User.id)).all()


def lock_management(session: Session, ids: set[int]):
    session.execute(text("SELECT pg_advisory_xact_lock(730812)"))
    return session.scalars(
        select(User)
        .where(User.id.in_(ids))
        .order_by(User.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).all()


def active_admin_count(session: Session) -> int:
    return session.scalar(
        select(func.count())
        .select_from(User)
        .where(User.role == UserRole.ADMIN, User.is_active.is_(True))
    )


def has_unfinished_orders(session: Session, user_id: int) -> bool:
    return (
        session.scalar(
            select(Order.id)
            .where(
                Order.manager_id == user_id,
                Order.status.not_in([OrderStatus.COMPLETED, OrderStatus.CANCELLED]),
            )
            .limit(1)
        )
        is not None
    )


def find_by_email(session: Session, email: str, *, lock: bool = False) -> User | None:
    query = select(User).where(User.email == email.strip().lower())
    if lock:
        query = query.with_for_update()
    return session.scalar(query)


def find_by_id(session: Session, user_id: int) -> User | None:
    return session.get(User, user_id)


def revoke_sessions(session: Session, user_id: int, auth_version: int) -> None:
    session.execute(
        update(User)
        .where(User.id == user_id, User.auth_version == auth_version)
        .values(auth_version=User.auth_version + 1)
    )


def insert_admin(session: Session, values: dict) -> int | None:
    return session.scalar(
        insert(User)
        .values(**values, role=UserRole.ADMIN, is_active=True)
        .on_conflict_do_nothing(constraint="uq_users_email")
        .returning(User.id)
    )

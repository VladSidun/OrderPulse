from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import User, UserRole


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

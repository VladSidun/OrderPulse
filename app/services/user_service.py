from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.business_time import utc_now
from app.core.errors import DomainError, NotFound
from app.core.policies import require_administrator
from app.core.security import hash_password
from app.models import User, UserRole
from app.repositories import user_repository
from app.schemas.user import PasswordReset, UserCreate, UserUpdate


def list_users(session: Session, actor: User):
    require_administrator(actor)
    return user_repository.list_all(session)


def get(session: Session, actor: User, user_id: int):
    require_administrator(actor)
    target = user_repository.find_by_id(session, user_id)
    if target is None:
        raise NotFound("Користувача не знайдено.")
    return target


def lock_management(session: Session, actor: User, user_id: int | None = None):
    # Serialize the cross-row last-admin invariant, including simultaneous changes.
    # Row locks also synchronize with FOR SHARE used by order assignment.
    ids = {actor.id} if user_id is None else {actor.id, user_id}
    locked = user_repository.lock_management(session, ids)
    require_administrator(next((row for row in locked if row.id == actor.id), None))
    if user_id is not None:
        target = next((row for row in locked if row.id == user_id), None)
        if target is None:
            raise NotFound("Користувача не знайдено.")
        return target


def create(session: Session, actor: User, data: UserCreate) -> int:
    try:
        lock_management(session, actor)
        values = data.model_dump(exclude={"password"})
        target = User(**values, password_hash=hash_password(data.password.get_secret_value()))
        session.add(target)
        session.flush()
        result = target.id
        session.commit()
        return result
    except IntegrityError as exc:
        session.rollback()
        if getattr(exc.orig, "sqlstate", None) == "23505":
            raise DomainError("Користувач із таким email уже існує.") from exc
        raise
    except Exception:
        session.rollback()
        raise


def update(session: Session, actor: User, user_id: int, data: UserUpdate) -> int:
    try:
        target = lock_management(session, actor, user_id)
        loses_access = target.role != data.role or (target.is_active and not data.is_active)
        if (
            target.role == UserRole.ADMIN
            and target.is_active
            and (data.role != UserRole.ADMIN or not data.is_active)
        ):
            admins = user_repository.active_admin_count(session)
            if admins <= 1:
                raise DomainError(
                    "Не можна змінити роль або деактивувати останнього активного адміністратора."
                )
        if target.role == UserRole.MANAGER and (
            data.role != UserRole.MANAGER or not data.is_active
        ):
            if user_repository.has_unfinished_orders(session, target.id):
                raise DomainError(
                    "Спочатку перепризначте всі незавершені замовлення цього менеджера."
                )
        for field, value in data.model_dump().items():
            setattr(target, field, value)
        if loses_access:
            target.auth_version += 1
        target.updated_at = utc_now()
        session.commit()
        return user_id
    except Exception:
        session.rollback()
        raise


def reset_password(session: Session, actor: User, user_id: int, data: PasswordReset) -> int:
    try:
        target = lock_management(session, actor, user_id)
        target.password_hash = hash_password(data.password.get_secret_value())
        target.auth_version += 1
        target.updated_at = utc_now()
        session.commit()
        return user_id
    except Exception:
        session.rollback()
        raise

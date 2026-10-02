from app.core.errors import AuthenticationRequired, PermissionDenied
from app.models import User, UserRole


def require_active(user: User | None) -> User:
    if user is None or not user.is_active:
        raise AuthenticationRequired("Увійдіть у систему, щоб продовжити.")
    return user


def require_administrator(user: User | None) -> User:
    active = require_active(user)
    if active.role != UserRole.ADMIN:
        raise PermissionDenied("Ця сторінка доступна лише адміністратору.")
    return active

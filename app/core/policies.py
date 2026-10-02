from app.core.errors import AuthenticationRequired, NotFound, PermissionDenied
from app.models import Order, OrderStatus, User, UserRole


def require_active(user: User | None) -> User:
    if user is None or not user.is_active:
        raise AuthenticationRequired("Увійдіть у систему, щоб продовжити.")
    return user


def require_administrator(user: User | None) -> User:
    active = require_active(user)
    if active.role != UserRole.ADMIN:
        raise PermissionDenied("Ця сторінка доступна лише адміністратору.")
    return active


def require_order_view(user: User, order: Order, visibility: str) -> None:
    require_active(user)
    if user.role == UserRole.MANAGER and (
        order.is_archived or (visibility == "assigned" and order.manager_id != user.id)
    ):
        raise NotFound("Замовлення не знайдено.")


def can_edit_order(user: User, order: Order) -> bool:
    return (
        user.is_active
        and not order.is_archived
        and order.status not in {OrderStatus.COMPLETED, OrderStatus.CANCELLED}
        and (user.role == UserRole.ADMIN or order.manager_id == user.id)
    )


def require_order_edit(user: User, order: Order, visibility: str) -> None:
    require_order_view(user, order, visibility)
    if not can_edit_order(user, order):
        raise PermissionDenied("Редагувати можна лише доступне вам незавершене замовлення.")

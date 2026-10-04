import logging

from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from app.core.business_time import KYIV, utc_now
from app.core.errors import (
    InputError,
    InvalidArchive,
    InvalidStatusTransition,
    NotFound,
    PermissionDenied,
    VersionConflict,
)
from app.core.policies import (
    require_active,
    require_administrator,
    require_order_edit,
    require_order_view,
)
from app.models import Client, Order, OrderItem, OrderStatus, OrderStatusHistory, User, UserRole
from app.repositories import order_repository
from app.schemas.api import OrderPatch
from app.schemas.order import OrderInput, OrderUpdate
from app.schemas.workflow import StatusChange, VersionInput

logger = logging.getLogger(__name__)

ALLOWED_TRANSITIONS = {
    OrderStatus.NEW: (OrderStatus.CONFIRMED, OrderStatus.CANCELLED),
    OrderStatus.CONFIRMED: (OrderStatus.IN_PROGRESS, OrderStatus.CANCELLED),
    OrderStatus.IN_PROGRESS: (OrderStatus.READY, OrderStatus.CANCELLED),
    OrderStatus.READY: (OrderStatus.COMPLETED, OrderStatus.CANCELLED),
    OrderStatus.COMPLETED: (),
    OrderStatus.CANCELLED: (),
}


def patch(session: Session, user: User, order_id: int, data: OrderPatch, visibility="all"):
    try:
        order = order_repository.get(session, order_id, lock=True)
        if order is None:
            raise NotFound("Замовлення не знайдено.")
        require_order_edit(user, order, visibility)
        if order.version != data.version:
            raise VersionConflict("Замовлення вже змінене. Оновіть дані та повторіть дію.")
        values = {
            field: getattr(order, field) for field in OrderInput.model_fields if field != "items"
        }
        values["items"] = [
            dict(name=item.name, quantity=item.quantity, unit_price=item.unit_price)
            for item in order.items
        ]
        values.update(data.model_dump(exclude_unset=True))
        return update(
            session,
            user,
            order_id,
            OrderUpdate.model_validate(values),
            visibility,
            replace_positions="items" in data.model_fields_set,
        )
    except Exception:
        session.rollback()
        raise


def validate_transition(old: OrderStatus, new: OrderStatus) -> None:
    if new not in ALLOWED_TRANSITIONS[old]:
        raise InvalidStatusTransition("Цей перехід статусу заборонений. Оновіть сторінку.")


def change_status(
    session: Session, user: User, order_id: int, data: StatusChange, visibility: str = "all"
) -> int:
    try:
        order = order_repository.get(session, order_id, lock=True)
        if order is None:
            raise NotFound("Замовлення не знайдено.")
        require_order_edit(user, order, visibility)
        if order.version != data.version:
            raise VersionConflict("Замовлення вже змінене. Оновіть сторінку перед повторною дією.")
        validate_transition(order.status, data.status)
        old_status, actor_id = order.status, user.id
        now = utc_now()
        session.add(
            OrderStatusHistory(
                order_id=order_id,
                old_status=old_status,
                new_status=data.status,
                changed_by_id=actor_id,
                changed_at=now,
                comment=data.comment,
            )
        )
        order.status, order.updated_at = data.status, now
        order.version += 1
        session.commit()
    except StaleDataError as exc:
        session.rollback()
        raise VersionConflict("Замовлення вже змінене. Оновіть сторінку.") from exc
    except Exception:
        session.rollback()
        raise
    logger.info(
        "Order status changed: order_id=%s actor_id=%s status=%s", order_id, actor_id, data.status
    )
    return order_id


def archive(session: Session, user: User, order_id: int, data: VersionInput) -> int:
    try:
        require_administrator(user)
        order = order_repository.get(session, order_id, lock=True)
        if order is None:
            raise NotFound("Замовлення не знайдено.")
        if order.version != data.version:
            raise VersionConflict("Замовлення вже змінене. Оновіть сторінку перед архівацією.")
        if order.is_archived or order.status not in {OrderStatus.COMPLETED, OrderStatus.CANCELLED}:
            raise InvalidArchive("Архівувати можна лише завершене або скасоване замовлення.")
        order.is_archived, order.updated_at = True, utc_now()
        order.version += 1
        session.commit()
        return order_id
    except StaleDataError as exc:
        session.rollback()
        raise VersionConflict("Замовлення вже змінене. Оновіть сторінку.") from exc
    except Exception:
        session.rollback()
        raise


def get(session: Session, user: User, order_id: int, visibility: str = "all") -> Order:
    order = order_repository.get(session, order_id)
    if order is None:
        raise NotFound("Замовлення не знайдено.")
    require_order_view(user, order, visibility)
    return order


def references(session: Session, user: User, data: OrderInput):
    if session.get(Client, data.client_id) is None:
        raise InputError("client_id", "Оберіть наявного клієнта.")
    if user.role == UserRole.MANAGER:
        if data.manager_id not in {None, user.id}:
            raise PermissionDenied("Менеджер не може перепризначати замовлення.")
        manager_id = user.id
    else:
        manager_id = data.manager_id
        if manager_id is None:
            raise InputError("manager_id", "Оберіть активного менеджера.")
    manager = order_repository.active_manager(session, manager_id)
    if manager is None or not manager.is_active or manager.role != UserRole.MANAGER:
        raise InputError("manager_id", "Оберіть активного користувача з роллю менеджера.")
    return manager_id


def replace_items(order: Order, data: OrderInput) -> None:
    order.items = [
        OrderItem(
            name=item.name,
            quantity=item.quantity,
            unit_price=item.unit_price,
            line_total=item.line_total,
        )
        for item in data.items
    ]
    order.total_amount = data.total_amount


def create(session: Session, user: User, data: OrderInput) -> int:
    try:
        require_active(user)
        actor_id = user.id
        manager_id = references(session, user, data)
        now = utc_now()
        if data.deadline_at is not None and data.deadline_at <= now:
            raise InputError(
                "deadline_at", "На створенні дедлайн має бути пізнішим за поточний час."
            )
        order = Order(
            number=order_repository.next_number(session, now.astimezone(KYIV).year),
            client_id=data.client_id,
            manager_id=manager_id,
            status=OrderStatus.NEW,
            priority=data.priority,
            deadline_at=data.deadline_at,
            comment=data.comment,
        )
        replace_items(order, data)
        session.add(order)
        session.flush()
        session.add(
            OrderStatusHistory(
                order_id=order.id,
                old_status=None,
                new_status=OrderStatus.NEW,
                changed_by_id=actor_id,
            )
        )
        result = order.id
        session.commit()
    except Exception:
        session.rollback()
        raise
    logger.info("Order created: order_id=%s actor_id=%s", result, actor_id)
    return result


def update(
    session: Session,
    user: User,
    order_id: int,
    data: OrderUpdate,
    visibility: str = "all",
    *,
    replace_positions: bool = True,
) -> int:
    try:
        order = order_repository.get(session, order_id, lock=True)
        if order is None:
            raise NotFound("Замовлення не знайдено.")
        require_order_edit(user, order, visibility)
        if data.version != order.version:
            raise VersionConflict(
                "Замовлення вже змінене. Ваші поля збережено нижче. "
                "Відкрийте актуальну версію в новій вкладці й повторіть введення."
            )
        manager_id = references(session, user, data)
        order.client_id, order.manager_id = data.client_id, manager_id
        order.priority, order.deadline_at, order.comment = (
            data.priority,
            data.deadline_at,
            data.comment,
        )
        if replace_positions:
            replace_items(order, data)
        order.updated_at = utc_now()
        # Always touch the parent, even when only items change or totals stay equal.
        order.version += 1
        session.commit()
        return order_id
    except StaleDataError as exc:
        session.rollback()
        raise VersionConflict(
            "Замовлення вже змінене. Оновіть сторінку та повторіть введення."
        ) from exc
    except Exception:
        session.rollback()
        raise

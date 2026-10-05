"""Atomic development dataset, recognized through immutable initial history."""

from datetime import timedelta

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.business_time import KYIV, utc_now
from app.core.config import Settings
from app.core.errors import SeedConflict
from app.core.security import hash_password
from app.models import Client, Order, OrderStatus, OrderStatusHistory, User, UserRole
from app.repositories.order_repository import next_number
from app.schemas.order import OrderInput
from app.services.order_service import replace_items, validate_transition

DEMO_PASSWORD = "Demo-OrderPulse-2026!"
DEMO_MARKER = "OrderPulse development dataset v1"
DEMO_EMAILS = (
    "demo-admin@example.com",
    "demo-manager@example.com",
    "demo-manager2@example.com",
)


def seed_demo(session: Session, settings: Settings) -> bool:
    try:
        if settings.app_env == "production":
            raise SeedConflict("Демонстраційні дані заборонено у production.")
        # Serialize concurrent invocations, including the first run on an empty DB.
        session.execute(text("SELECT pg_advisory_xact_lock(73112026)"))
        if (
            session.scalar(
                select(OrderStatusHistory.id)
                .where(OrderStatusHistory.comment == DEMO_MARKER)
                .limit(1)
            )
            is not None
        ):
            session.commit()
            return False
        if any(
            session.scalar(select(model.id).limit(1)) is not None for model in (User, Client, Order)
        ):
            raise SeedConflict("Demo seed потребує порожньої БД; наявні дані не змінено.")

        now = utc_now()
        users = []
        for index, email in enumerate(DEMO_EMAILS):
            user = User(
                email=email,
                first_name=("Демо", "Олена", "Андрій")[index],
                last_name=("Адміністратор", "Демонстраційна", "Демонстраційний")[index],
                role=UserRole.ADMIN if index == 0 else UserRole.MANAGER,
                password_hash=hash_password(DEMO_PASSWORD),
                is_active=True,
            )
            session.add(user)
            users.append(user)
        clients = [
            Client(
                name=name,
                email=f"demo-client{index + 1}@example.com",
                address="Демонстраційна адреса",
                note="Вигадані дані для демонстрації.",
            )
            for index, name in enumerate(
                [
                    "Демо: студія «Палітра»",
                    "Демо: кав’ярня «Ранок»",
                    "Демо: магазин «Вектор»",
                    "Демо: майстерня «Форма»",
                    "Демо: освітній центр",
                ]
            )
        ]
        session.add_all(clients)
        session.flush()
        paths = [
            [],
            [OrderStatus.CONFIRMED],
            [OrderStatus.CONFIRMED, OrderStatus.IN_PROGRESS],
            [OrderStatus.CONFIRMED, OrderStatus.IN_PROGRESS, OrderStatus.READY],
            [
                OrderStatus.CONFIRMED,
                OrderStatus.IN_PROGRESS,
                OrderStatus.READY,
                OrderStatus.COMPLETED,
            ],
            [OrderStatus.CANCELLED],
        ]
        samples = [
            [("Пробна послуга", "0.50", "0.01"), ("Друга послуга", "2.25", "10.00")],
            [("Дизайн меню", "1.00", "85.00"), ("Друк меню", "25.00", "2.40")],
            [("Візитівки", "200.00", "0.35"), ("Макет", "1.00", "30.00")],
            [("Дизайн пакування", "2.00", "65.00")],
            [("Навчальні матеріали", "12.00", "8.50")],
            [("Банер", "1.00", "120.00"), ("Доставка", "1.00", "0.00")],
        ]
        for index in range(16):
            created = now - timedelta(hours=6 * (16 - index))
            manager = users[1 + index % 2]
            data = OrderInput(
                client_id=clients[index % len(clients)].id,
                manager_id=manager.id,
                priority=("NORMAL", "HIGH", "LOW")[index % 3],
                deadline_at=(None if index == 1 else now + timedelta(days=index + 1)),
                comment="Демонстраційне замовлення; дані можна змінювати.",
                items=[
                    dict(name=name, quantity=qty, unit_price=price)
                    for name, qty, price in samples[index % len(samples)]
                ],
            )
            order = Order(
                number=next_number(session, created.astimezone(KYIV).year),
                client_id=data.client_id,
                manager_id=manager.id,
                status=OrderStatus.NEW,
                priority=data.priority,
                deadline_at=data.deadline_at,
                comment=data.comment,
                created_at=created,
                updated_at=created,
            )
            replace_items(order, data)
            if index in (0, 2, 6, 8, 12, 14):
                order.deadline_at = now - timedelta(days=1)
            session.add(order)
            session.flush()
            session.add(
                OrderStatusHistory(
                    order_id=order.id,
                    old_status=None,
                    new_status=OrderStatus.NEW,
                    changed_by_id=users[0].id,
                    changed_at=created,
                    comment=DEMO_MARKER,
                )
            )
            for step, status in enumerate(paths[index % len(paths)], start=1):
                validate_transition(order.status, status)
                changed = created + timedelta(hours=step)
                session.add(
                    OrderStatusHistory(
                        order_id=order.id,
                        old_status=order.status,
                        new_status=status,
                        changed_by_id=manager.id,
                        changed_at=changed,
                        comment="Демонстраційний перехід статусу.",
                    )
                )
                order.status, order.updated_at = status, changed
                order.version += 1
            if index == 11:
                order.is_archived = True
                order.updated_at = created + timedelta(hours=5)
                order.version += 1
        session.commit()
        return True
    except Exception:
        session.rollback()
        raise

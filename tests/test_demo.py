from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Barrier

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from app.core.config import Settings
from app.core.errors import SeedConflict
from app.core.security import hash_password, verify_password
from app.db import demo
from app.db.session import create_session_factory
from app.models import Client, Order, OrderNumberCounter, OrderStatus, OrderStatusHistory, User
from app.services.demo_service import DEMO_EMAILS, DEMO_PASSWORD, seed_demo
from app.services.order_service import validate_transition


def settings(**overrides):
    return Settings(_env_file=None, database_url=None, **overrides)


@pytest.mark.postgres
def test_dataset_history_money_and_repeat_preserve_manual_changes(migrated_engine):
    factory = create_session_factory(migrated_engine)
    with factory() as session:
        assert seed_demo(session, settings()) is True
        users = session.scalars(select(User).order_by(User.id)).all()
        assert [user.email for user in users] == list(DEMO_EMAILS)
        assert all(verify_password(DEMO_PASSWORD, user.password_hash) for user in users)
        assert session.scalar(select(func.count()).select_from(Client)) == 5
        orders = session.scalars(select(Order).order_by(Order.id)).all()
        assert len(orders) == 16 and len({order.number for order in orders}) == 16
        assert {order.status for order in orders} == set(OrderStatus)
        assert sum(order.total_amount for order in orders) == Decimal("1636.53")
        assert sum(order.is_archived for order in orders) == 1
        for order in orders:
            assert order.total_amount == sum(item.line_total for item in order.items)
            history = order.status_history
            assert history[0].old_status is None and history[0].new_status == OrderStatus.NEW
            for previous, current in zip(history, history[1:], strict=False):
                assert current.old_status == previous.new_status
                validate_transition(current.old_status, current.new_status)
                assert current.changed_at > previous.changed_at
            assert history[-1].new_status == order.status
            assert history[-1].changed_at <= order.updated_at
            assert not order.is_archived or order.status in {
                OrderStatus.COMPLETED,
                OrderStatus.CANCELLED,
            }
        users[0].password_hash = hash_password("Manually-changed-123!")
        users[1].is_active = False
        users[1].email = "renamed-manager@example.com"
        session.get(Client, orders[0].client_id).name = "Ручна назва"
        orders[0].comment = "Ручний коментар"
        session.commit()
        original_hash = users[0].password_hash
        assert seed_demo(session, settings()) is False
        session.expire_all()
        assert users[0].password_hash == original_hash and not users[1].is_active
        assert users[1].email == "renamed-manager@example.com"
        assert orders[0].comment == "Ручний коментар"
        assert session.get(Client, orders[0].client_id).name == "Ручна назва"
        assert session.scalar(select(func.count()).select_from(Order)) == 16


@pytest.mark.postgres
def test_nonempty_database_and_production_are_not_modified(migrated_engine):
    with create_session_factory(migrated_engine)() as session:
        with pytest.raises(SeedConflict, match="production"):
            seed_demo(session, settings(app_env="production", secret_key="x" * 32))
        session.add(Client(name="Наявний клієнт"))
        session.commit()
        with pytest.raises(SeedConflict, match="порожньої"):
            seed_demo(session, settings())
        assert session.scalar(select(func.count()).select_from(User)) == 0
        assert session.scalar(select(Client.name)) == "Наявний клієнт"


@pytest.mark.postgres
def test_database_failure_rolls_back_entire_seed(migrated_engine):
    with migrated_engine.begin() as connection:
        connection.execute(
            text("""
            CREATE FUNCTION reject_demo_history() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN RAISE EXCEPTION 'history write rejected'; END $$
        """)
        )
        connection.execute(
            text("""
            CREATE TRIGGER reject_demo BEFORE INSERT ON order_status_history
            FOR EACH ROW EXECUTE FUNCTION reject_demo_history()
        """)
        )
    with create_session_factory(migrated_engine)() as session:
        with pytest.raises(DBAPIError):
            seed_demo(session, settings())
        for model in [User, Client, Order, OrderNumberCounter, OrderStatusHistory]:
            assert session.scalar(select(func.count()).select_from(model)) == 0


@pytest.mark.postgres
def test_concurrent_demo_seed_creates_one_dataset(migrated_engine):
    factory = create_session_factory(migrated_engine)
    barrier = Barrier(2)

    def run():
        with factory() as session:
            barrier.wait(timeout=10)
            return seed_demo(session, settings())

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: run(), range(2)))
    assert sorted(results) == [False, True]
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(User)) == 3
        assert session.scalar(select(func.count()).select_from(Order)) == 16


def test_cli_rejects_production_before_opening_database(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["demo"])
    monkeypatch.setattr(
        demo, "get_settings", lambda: settings(app_env="production", secret_key="x" * 32)
    )
    monkeypatch.setattr(demo, "create_database_engine", lambda _: pytest.fail("DB opened"))
    assert demo.main() == 1
    assert "production" in capsys.readouterr().out


def test_cli_unconfigured_database_has_friendly_error(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["demo"])
    monkeypatch.setattr(demo, "get_settings", settings)
    assert demo.main() == 1
    assert "alembic upgrade head" in capsys.readouterr().out

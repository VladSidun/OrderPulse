import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.exc import DataError, IntegrityError
from sqlalchemy.orm import selectinload
from sqlalchemy.orm.exc import StaleDataError

from alembic import command
from app.core.config import Settings
from app.db.base import Base
from app.db.session import create_database_engine, create_session_factory, get_db
from app.models import Client, Order, OrderItem, OrderStatusHistory, User, UserRole

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def db_engine():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL to run PostgreSQL integration tests")
    settings = Settings(_env_file=None, database_url=url)
    admin_engine = create_database_engine(settings)
    schema = "test_" + uuid4().hex
    with admin_engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(
        url,
        hide_parameters=True,
        connect_args={"options": f"-c timezone=UTC -c search_path={schema}"},
    )
    try:
        yield engine
    finally:
        engine.dispose()
        with admin_engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin_engine.dispose()


def migration_config(connection):
    config = Config(str(ROOT / "alembic.ini"))
    config.attributes["connection"] = connection
    return config


@pytest.fixture
def migrated_engine(db_engine):
    with db_engine.begin() as connection:
        command.upgrade(migration_config(connection), "head")
    return db_engine


@pytest.fixture
def graph(migrated_engine):
    factory = create_session_factory(migrated_engine)
    with factory() as session:
        manager = User(
            first_name="Іван",
            last_name="Петренко",
            email="  Manager@Example.com ",
            password_hash="test-hash-only",
            role=UserRole.MANAGER,
        )
        client = Client(name="ТОВ Альфа")
        order = Order(
            number="ORD-2026-0001",
            manager=manager,
            client=client,
            total_amount=Decimal("12.50"),
            deadline_at=datetime(2026, 10, 3, 12, tzinfo=UTC),
        )
        order.items = [
            OrderItem(
                name="Послуга",
                quantity=Decimal("1.25"),
                unit_price=Decimal("10.00"),
                line_total=Decimal("12.50"),
            )
        ]
        order.status_history = [OrderStatusHistory(new_status="NEW", changed_by=manager)]
        session.add(order)
        session.commit()
        return order.id, manager.id, client.id


@pytest.mark.postgres
def test_fresh_upgrade_downgrade_upgrade_and_metadata(db_engine):
    with db_engine.begin() as connection:
        config = migration_config(connection)
        assert inspect(connection).get_table_names() == []
        command.upgrade(config, "head")
        assert set(inspect(connection).get_table_names()) == set(Base.metadata.tables) | {
            "alembic_version"
        }
        command.check(config)
        command.downgrade(config, "-1")
        command.upgrade(config, "head")
        command.downgrade(config, "base")
        assert inspect(connection).get_table_names() == ["alembic_version"]
        assert connection.execute(text("SELECT count(*) FROM alembic_version")).scalar() == 0
        command.upgrade(config, "head")
        command.check(config)


@pytest.mark.postgres
def test_relationships_decimal_utc_defaults_and_indexes(migrated_engine, graph):
    with create_session_factory(migrated_engine)() as session:
        order = session.scalar(
            select(Order).options(selectinload(Order.items), selectinload(Order.status_history))
        )
        assert order.manager.email == "manager@example.com"
        assert order.client.name == "ТОВ Альфа"
        assert order.total_amount == Decimal("12.50")
        assert isinstance(order.items[0].quantity, Decimal)
        assert order.items[0].quantity == Decimal("1.25")
        assert order.created_at.utcoffset() == timedelta(0)
        assert order.updated_at.utcoffset() == timedelta(0)
        assert order.deadline_at.utcoffset() == timedelta(0)
        assert order.status_history[0].changed_at.utcoffset() == timedelta(0)
        assert order.status_history[0].old_status is None
        assert order.status_history[0].changed_by is order.manager
        assert order.status == "NEW" and order.priority == "NORMAL"
        assert order.version == 1 and order.manager.auth_version == 1
        assert order.manager.is_active and not order.is_archived
        assert session.execute(text("SHOW timezone")).scalar() == "UTC"
    inspector = inspect(migrated_engine)
    order_indexes = {index["name"] for index in inspector.get_indexes("orders")}
    assert {
        "uq_orders_number",
        "ix_orders_client_id",
        "ix_orders_manager_id",
        "ix_orders_status",
        "ix_orders_created_at",
        "ix_orders_deadline_at",
    } <= order_indexes
    assert any(index["unique"] for index in inspector.get_indexes("users"))
    assert {constraint["name"] for constraint in inspector.get_unique_constraints("users")} == {
        "uq_users_email"
    }
    assert {constraint["name"] for constraint in inspector.get_unique_constraints("orders")} == {
        "uq_orders_number"
    }
    assert "ix_order_status_history_order_time" in {
        index["name"] for index in inspector.get_indexes("order_status_history")
    }


INVALID_UPDATES = [
    ("users", "email = 'Mixed@Example.com'"),
    ("users", "email = 'manager@example.com '"),
    ("users", "role = 'OWNER'"),
    ("users", "auth_version = 0"),
    ("clients", "note = repeat('x', 2001)"),
    ("orders", "status = 'INVALID'"),
    ("orders", "priority = 'URGENT'"),
    ("orders", "version = 0"),
    ("orders", "total_amount = -0.01"),
    ("orders", "client_id = -1"),
    ("orders", "manager_id = -1"),
    ("order_items", "order_id = -1"),
    ("order_items", "quantity = 0"),
    ("order_items", "quantity = -1"),
    ("order_items", "unit_price = -0.01"),
    ("order_items", "line_total = -0.01"),
    ("order_status_history", "old_status = 'INVALID'"),
    ("order_status_history", "new_status = 'INVALID'"),
    ("order_status_history", "new_status = 'COMPLETED'"),
    ("order_status_history", "order_id = -1"),
    ("order_status_history", "changed_by_id = -1"),
]


@pytest.mark.postgres
@pytest.mark.parametrize(("table", "assignment"), INVALID_UPDATES)
def test_database_rejects_invalid_raw_values(migrated_engine, graph, table, assignment):
    # Literal test cases deliberately bypass ORM validation to exercise actual PG constraints.
    with pytest.raises(IntegrityError), migrated_engine.begin() as connection:
        connection.execute(text(f"UPDATE {table} SET {assignment}"))


@pytest.mark.postgres
@pytest.mark.parametrize(
    ("table", "assignment"),
    [
        ("orders", "total_amount = 10000000000.00"),
        ("order_items", "unit_price = 10000000000.00"),
        ("order_items", "line_total = 10000000000.00"),
        ("order_items", "quantity = 100000000.00"),
    ],
)
def test_numeric_overflow_is_rejected(migrated_engine, graph, table, assignment):
    with pytest.raises(DataError), migrated_engine.begin() as connection:
        connection.execute(text(f"UPDATE {table} SET {assignment}"))


@pytest.mark.postgres
@pytest.mark.parametrize("table", ["clients", "users", "orders"])
def test_referenced_records_cannot_be_deleted(migrated_engine, graph, table):
    with pytest.raises(IntegrityError), migrated_engine.begin() as connection:
        connection.execute(text(f"DELETE FROM {table}"))
    with migrated_engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM order_items")).scalar() == 1
        assert connection.execute(text("SELECT count(*) FROM order_status_history")).scalar() == 1


@pytest.mark.postgres
def test_unique_normalized_email_and_order_number(migrated_engine, graph):
    factory = create_session_factory(migrated_engine)
    with factory() as session:
        session.add(
            User(
                first_name="Інна",
                last_name="Петренко",
                email="MANAGER@example.com",
                password_hash="test-hash-only",
                role=UserRole.ADMIN,
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()
    with factory() as session:
        session.add(Order(number="ORD-2026-0001", manager_id=graph[1], client_id=graph[2]))
        with pytest.raises(IntegrityError):
            session.commit()


@pytest.mark.postgres
def test_order_item_removal_and_cascade(migrated_engine, graph):
    factory = create_session_factory(migrated_engine)
    with factory() as session:
        order = session.get(Order, graph[0])
        removed_id = order.items[0].id
        order.items.clear()
        session.commit()
        assert session.get(OrderItem, removed_id) is None
        # A history-free test record verifies the item FK's explicit cascade.
        temporary = Order(number="ORD-2026-0002", manager_id=graph[1], client_id=graph[2])
        temporary.items = [
            OrderItem(
                name="Позиція",
                quantity=Decimal("1"),
                unit_price=Decimal("0"),
                line_total=Decimal("0"),
            )
        ]
        session.add(temporary)
        session.commit()
        temporary_id = temporary.id
    with migrated_engine.begin() as connection:
        connection.execute(text("DELETE FROM orders WHERE id = :id"), {"id": temporary_id})
        assert connection.execute(text("SELECT count(*) FROM order_items")).scalar() == 0


@pytest.mark.postgres
def test_orm_version_detects_stale_order(migrated_engine, graph):
    factory = create_session_factory(migrated_engine)
    with factory() as first, factory() as second:
        one = first.get(Order, graph[0])
        two = second.get(Order, graph[0])
        original_updated_at = one.updated_at
        one.comment = "Перше збереження"
        first.commit()
        assert one.version == 2
        assert one.updated_at >= original_updated_at
        two.comment = "Застаріле збереження"
        with pytest.raises(StaleDataError):
            second.commit()
    with factory() as session:
        current = session.get(Order, graph[0])
        assert current.version == 2 and current.comment == "Перше збереження"


@pytest.mark.postgres
@pytest.mark.parametrize(("year", "last_value"), [(0, 0), (10000, 0), (2026, -1)])
def test_counter_constraints(migrated_engine, year, last_value):
    with pytest.raises(IntegrityError), migrated_engine.begin() as connection:
        connection.execute(
            text("INSERT INTO order_number_counters (year, last_value) VALUES (:year, :value)"),
            {"year": year, "value": last_value},
        )


@pytest.mark.postgres
@pytest.mark.parametrize("fail", [False, True])
def test_dependency_closes_and_rolls_back_without_implicit_commit(
    migrated_engine, monkeypatch, fail
):
    from app.db import session as database_session

    factory = create_session_factory(migrated_engine)
    monkeypatch.setattr(database_session, "get_session_factory", lambda: factory)
    dependency = get_db()
    session = next(dependency)
    session.add(Client(name="Незбережений клієнт"))
    session.flush()
    if fail:
        with pytest.raises(RuntimeError, match="test error"):
            dependency.throw(RuntimeError("test error"))
    else:
        dependency.close()
    with factory() as session:
        assert session.scalar(select(Client)) is None


@pytest.mark.parametrize("url", [None, "not-a-url", "sqlite:///test.db"])
def test_engine_requires_postgresql_without_exposing_url(url):
    settings = Settings(_env_file=None, database_url=url)
    with pytest.raises(ValueError) as error:
        create_database_engine(settings)
    if url:
        assert url not in str(error.value)


def test_engine_is_lazy_and_hides_parameters():
    settings = Settings(
        _env_file=None,
        database_url="postgresql+psycopg://test:private-test-password@127.0.0.1:1/test",
    )
    engine = create_database_engine(settings)
    try:
        assert engine.hide_parameters is True
        assert "private-test-password" not in repr(engine)
    finally:
        engine.dispose()

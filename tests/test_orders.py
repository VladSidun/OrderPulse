import re
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from threading import Barrier
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import event, func, select
from sqlalchemy.exc import IntegrityError

from app.core.business_time import local_input, parse_local_deadline
from app.core.errors import InputError, NotFound, PermissionDenied, VersionConflict
from app.models import (
    Client,
    Order,
    OrderItem,
    OrderNumberCounter,
    OrderStatus,
    OrderStatusHistory,
    User,
)
from app.schemas.order import ItemInput, OrderInput, OrderUpdate
from app.services import order_service
from tests.test_authentication import login, token
from tests.test_clients import business_setup as client_business_fixture  # noqa: F401


@pytest.fixture
def order_setup(business_setup):
    app, factory = business_setup
    with factory() as session:
        client = Client(name="Клієнт замовлення")
        session.add(client)
        session.commit()
        client_id = client.id
        users = {user.email.split("@")[0]: user.id for user in session.scalars(select(User))}
    return app, factory, client_id, users


def data(default_client_id, default_manager_id=None, **overrides):
    values = {
        "client_id": default_client_id,
        "manager_id": default_manager_id,
        "items": [
            {"name": "Послуга", "quantity": "0.50", "unit_price": "0.01"},
            {"name": "Друга", "quantity": "2.25", "unit_price": "10.00"},
        ],
    }
    values.update(overrides)
    return OrderInput(**values)


def create_one(setup, **overrides):
    _, factory, client_id, users = setup
    with factory() as session:
        return order_service.create(
            session,
            session.get(User, users["admin"]),
            data(client_id, users["manager"], **overrides),
        )


def form_data(csrf, client_id, manager_id=None, **overrides):
    values = {
        "csrf_token": csrf,
        "client_id": str(client_id),
        "priority": "NORMAL",
        "deadline_at": "",
        "comment": "Коментар <script>",
        "items.0.name": "Послуга <script>",
        "items.0.quantity": "0.50",
        "items.0.unit_price": "0.01",
        "items.1.name": "Друга",
        "items.1.quantity": "2.25",
        "items.1.unit_price": "10.00",
    }
    if manager_id is not None:
        values["manager_id"] = str(manager_id)
    values.update(overrides)
    return values


@pytest.mark.parametrize(
    "field,value",
    [
        ("quantity", "0"),
        ("quantity", "-1"),
        ("quantity", "1.001"),
        ("quantity", "100000000.00"),
        ("quantity", "NaN"),
        ("quantity", "Infinity"),
        ("quantity", 0.5),
        ("quantity", True),
        ("quantity", "abc"),
        ("unit_price", "-0.01"),
        ("unit_price", "10000000000.00"),
        ("unit_price", "0.001"),
        ("unit_price", float("nan")),
    ],
)
def test_invalid_decimal_inputs(field, value):
    values = {"name": "Позиція", "quantity": "1.00", "unit_price": "1.00", field: value}
    with pytest.raises(ValidationError):
        ItemInput(**values)


def test_rounding_each_line_before_total_and_zero_price():
    result = data(
        1,
        items=[
            {"name": "A", "quantity": "0.50", "unit_price": "0.01"},
            {"name": "B", "quantity": "0.50", "unit_price": "0.01"},
            {"name": "C", "quantity": "1.00", "unit_price": "0.00"},
        ],
    )
    assert result.total_amount == Decimal("0.02")
    assert [item.line_total for item in result.items] == [
        Decimal("0.01"),
        Decimal("0.01"),
        Decimal("0"),
    ]


@pytest.mark.parametrize(
    "overrides",
    [
        {"items": []},
        {"client_id": True},
        {"client_id": 1.5},
        {"client_id": 0},
        {"priority": "URGENT"},
        {"comment": "x" * 2001},
        {"deadline_at": datetime(2026, 1, 1)},
        {"status": "COMPLETED"},
        {"total_amount": "0"},
        {"number": "ORD-MANUAL"},
        {"is_archived": True},
        {"items": [{"name": "", "quantity": "1", "unit_price": "1"}]},
        {"items": [{"name": "A", "quantity": "2", "unit_price": "9999999999.99"}]},
        {
            "items": [
                {"name": "A", "quantity": "1", "unit_price": "9999999999.99"},
                {"name": "B", "quantity": "1", "unit_price": "0.01"},
            ]
        },
    ],
)
def test_order_validation_allowlist_and_overflow(overrides):
    with pytest.raises(ValidationError):
        data(1, **overrides)


@pytest.mark.parametrize(
    "value", ["2026-03-29T03:30", "2026-10-25T03:30", "2026-01-01T10:00+02:00", "invalid"]
)
def test_invalid_or_ambiguous_local_time(value):
    with pytest.raises(ValueError):
        parse_local_deadline(value)


def test_business_time_roundtrip_and_optional_date():
    assert parse_local_deadline("2026-01-01T10:00") == datetime(2026, 1, 1, 8, tzinfo=UTC)
    assert local_input(parse_local_deadline("2026-07-01T10:00")) == "2026-07-01T10:00"
    assert parse_local_deadline("") is None and local_input(None) == ""


@pytest.mark.postgres
def test_creation_items_history_decimal_and_new_year_number(order_setup, monkeypatch):
    _, factory, client_id, users = order_setup
    monkeypatch.setattr(
        order_service, "utc_now", lambda: datetime(2026, 12, 31, 22, 30, tzinfo=UTC)
    )
    order_id = create_one(order_setup)
    with factory() as session:
        order = order_service.get(session, session.get(User, users["admin"]), order_id)
        assert order.number == "ORD-2027-0001" and order.status == OrderStatus.NEW
        assert order.total_amount == Decimal("22.51") and len(order.items) == 2
        assert order.version == 1 and order.created_at.utcoffset() == timedelta(0)
        assert len(order.status_history) == 1
        history = order.status_history[0]
        assert history.old_status is None and history.new_status == OrderStatus.NEW
        assert history.changed_by_id == users["admin"]
        session.get(OrderNumberCounter, 2027).last_value = 9999
        session.commit()
    order_id = create_one(order_setup)
    with factory() as session:
        assert session.get(Order, order_id).number == "ORD-2027-10000"


@pytest.mark.postgres
def test_concurrent_creation_first_number_same_year(order_setup, monkeypatch):
    _, factory, client_id, users = order_setup
    monkeypatch.setattr(order_service, "utc_now", lambda: datetime(2028, 1, 1, 0, 0, tzinfo=UTC))
    barrier = Barrier(4)

    def run(_):
        with factory() as session:
            user = session.get(User, users["manager"])
            barrier.wait(timeout=10)
            return order_service.create(session, user, data(client_id))

    with ThreadPoolExecutor(max_workers=4) as executor:
        ids = list(executor.map(run, range(4)))
    with factory() as session:
        numbers = session.scalars(select(Order.number).where(Order.id.in_(ids))).all()
        assert sorted(numbers) == [f"ORD-2028-{i:04}" for i in range(1, 5)]
        assert session.get(OrderNumberCounter, 2028).last_value == 4
        assert session.scalar(select(func.count(OrderStatusHistory.id))) == 4


@pytest.mark.postgres
@pytest.mark.parametrize("stage", ["item", "history"])
def test_real_database_failure_rolls_back_order_items_history_and_counter(order_setup, stage):
    _, factory, client_id, users = order_setup

    def corrupt(session, context, instances):
        for entity in session.new:
            if stage == "item" and isinstance(entity, OrderItem):
                entity.quantity = Decimal("-1")
            if stage == "history" and isinstance(entity, OrderStatusHistory):
                entity.changed_by_id = 99999999

    with factory() as session:
        event.listen(session, "before_flush", corrupt)
        with pytest.raises(IntegrityError):
            order_service.create(
                session, session.get(User, users["admin"]), data(client_id, users["manager"])
            )
        for model in (Order, OrderItem, OrderStatusHistory, OrderNumberCounter):
            assert session.scalar(select(func.count()).select_from(model)) == 0


@pytest.mark.postgres
def test_atomic_item_replacement_parent_version_and_concurrent_conflict(order_setup):
    _, factory, client_id, users = order_setup
    order_id = create_one(order_setup)
    update = OrderUpdate(
        **data(
            client_id,
            users["manager"],
            items=[{"name": "Інша", "quantity": "1", "unit_price": "22.51"}],
        ).model_dump(),
        version=1,
    )
    barrier = Barrier(2)

    def run(_):
        with factory() as session:
            user = session.get(User, users["manager"])
            # Prime the identity map before competing writes: lock must refresh it.
            order_service.get(session, user, order_id)
            barrier.wait(timeout=10)
            try:
                order_service.update(session, user, order_id, update)
                return "saved"
            except VersionConflict:
                return "conflict"

    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(run, range(2))) == ["conflict", "saved"]
    with factory() as session:
        order = order_service.get(session, session.get(User, users["admin"]), order_id)
        assert order.version == 2 and order.total_amount == Decimal("22.51")
        assert len(order.items) == 1 and order.items[0].name == "Інша"
        assert len(order.status_history) == 1


@pytest.mark.postgres
def test_edit_failure_restores_original_items_and_version(order_setup):
    _, factory, client_id, users = order_setup
    order_id = create_one(order_setup)
    with factory() as session:
        user = session.get(User, users["admin"])
        original = order_service.get(session, user, order_id)
        ids = [item.id for item in original.items]
        update = OrderUpdate(
            **data(client_id, users["manager"], comment="Changed").model_dump(), version=1
        )
        with patch.object(session, "commit", side_effect=RuntimeError("commit failure")):
            with pytest.raises(RuntimeError):
                order_service.update(session, user, order_id, update)
        session.expire_all()
        current = order_service.get(session, user, order_id)
        assert current.version == 1 and current.comment is None
        assert [item.id for item in current.items] == ids


@pytest.mark.postgres
@pytest.mark.parametrize("field", ["client", "manager", "inactive", "admin", "deadline"])
def test_create_references_and_future_deadline(order_setup, field):
    _, factory, client_id, users = order_setup
    with factory() as session:
        user = session.get(User, users["admin"])
        values = data(client_id, users["manager"])
        if field == "client":
            values = data(999999, users["manager"])
        elif field == "manager":
            values = data(client_id, 999999)
        elif field == "inactive":
            session.get(User, users["manager"]).is_active = False
            session.commit()
        elif field == "admin":
            values = data(client_id, users["admin"])
        else:
            values = data(client_id, users["manager"], deadline_at=datetime(2000, 1, 1, tzinfo=UTC))
        with pytest.raises(InputError):
            order_service.create(session, user, values)
        assert session.scalar(select(func.count(Order.id))) == 0


@pytest.mark.postgres
@pytest.mark.parametrize("state", [OrderStatus.COMPLETED, OrderStatus.CANCELLED, "archived"])
def test_terminal_and_archived_orders_cannot_be_edited(order_setup, state):
    _, factory, client_id, users = order_setup
    order_id = create_one(order_setup)
    with factory() as session:
        order = session.get(Order, order_id)
        if state == "archived":
            order.is_archived = True
        else:
            order.status = state
        session.commit()
        update = OrderUpdate(
            **data(client_id, users["manager"]).model_dump(), version=order.version
        )
        with pytest.raises(PermissionDenied):
            order_service.update(session, session.get(User, users["admin"]), order_id, update)


@pytest.mark.postgres
def test_permissions_reassignment_past_edit_and_visibility(order_setup):
    app, factory, client_id, users = order_setup
    order_id = create_one(order_setup)
    update = OrderUpdate(
        **data(
            client_id, users["other"], deadline_at=datetime(2000, 1, 1, tzinfo=UTC)
        ).model_dump(),
        version=1,
    )
    with factory() as session:
        other = session.get(User, users["other"])
        assert order_service.get(session, other, order_id).id == order_id
        with pytest.raises(NotFound):
            order_service.get(session, other, order_id, "assigned")
        with pytest.raises(PermissionDenied):
            order_service.update(session, other, order_id, update)
        with pytest.raises(PermissionDenied):
            order_service.update(session, session.get(User, users["manager"]), order_id, update)
        order_service.update(session, session.get(User, users["admin"]), order_id, update)
        order = session.get(Order, order_id)
        assert order.manager_id == users["other"] and order.deadline_at.year == 2000


@pytest.mark.postgres
def test_html_lifecycle_validation_conflict_and_phase_boundary(order_setup):
    app, factory, client_id, users = order_setup
    with TestClient(app) as browser:
        login(browser)
        csrf = token(browser.get("/orders/new"))
        values = form_data(csrf, client_id, users["manager"])
        assert browser.post("/orders/new", data={"client_id": client_id}).status_code == 403
        invalid = {**values, "items.0.quantity": "0"}
        response = browser.post("/orders/new", data=invalid)
        assert response.status_code == 422 and "Послуга &lt;script&gt;" in response.text
        assert "aria-invalid" in response.text
        response = browser.post("/orders/new", data={**values, "deadline_at": "2026-10-25T03:30"})
        assert response.status_code == 422 and "неоднозначний" in response.text
        for protected in ("status", "number", "total_amount", "is_archived"):
            assert browser.post("/orders/new", data={**values, protected: "NEW"}).status_code == 422
        response = browser.post("/orders/new", data=values, follow_redirects=False)
        assert response.status_code == 303
        path = response.headers["location"]
        detail = browser.get(path)
        assert "22.51 EUR" in detail.text and "<script>" not in detail.text
        assert "Нове" in detail.text and "Історія статусів" in detail.text
        assert path in browser.get("/orders").text
        assert path in browser.get(f"/clients/{client_id}").text
        edit = browser.get(path + "/edit")
        version = re.search(r'name="version" value="(\d+)"', edit.text).group(1)
        change = {**values, "version": version, "comment": "Збережено"}
        assert browser.post(path + "/edit", data=change).status_code == 200
        response = browser.post(path + "/edit", data={**change, "comment": "Моя стара форма"})
        assert response.status_code == 409 and "Моя стара форма" in response.text
        assert f'name="version" value="{version}"' in response.text
        assert "Моя стара форма" not in browser.get(path).text
        for action in ("status", "archive"):
            assert browser.post(path + "/" + action, data={"csrf_token": csrf}).status_code == 404
        assert browser.get("/orders/999999").status_code == 404
        assert browser.delete(path, headers={"X-CSRF-Token": csrf}).status_code == 405


@pytest.mark.postgres
def test_manager_html_assignment_readonly_and_assigned_visibility(order_setup):
    app, factory, client_id, users = order_setup
    own_id = create_one(order_setup)
    other_id = create_one(order_setup, manager_id=users["other"])
    with TestClient(app) as browser:
        login(browser, email="manager@example.com")
        response = browser.get("/orders/new")
        assert 'name="manager_id"' not in response.text
        csrf = token(response)
        assert (
            browser.post("/orders/new", data=form_data(csrf, client_id, users["other"])).status_code
            == 403
        )
        response = browser.post(
            "/orders/new", data=form_data(csrf, client_id), follow_redirects=False
        )
        assert response.status_code == 303
        own_path, other_path = f"/orders/{own_id}", f"/orders/{other_id}"
        assert own_path + "/edit" in browser.get(own_path).text
        assert other_path + "/edit" not in browser.get(other_path).text
        assert browser.get(other_path + "/edit").status_code == 403
        assert (
            browser.post(
                other_path + "/edit", data=form_data(csrf, client_id, version="1")
            ).status_code
            == 403
        )
        app.state.settings.manager_order_visibility = "assigned"
        assert browser.get(other_path).status_code == 404
        assert browser.get(other_path + "/edit").status_code == 404
        assert other_path + '"' not in browser.get("/orders").text
        assert other_path + '"' not in browser.get(f"/clients/{client_id}").text

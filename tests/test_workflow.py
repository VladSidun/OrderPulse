from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

from app.core.errors import (
    InvalidArchive,
    InvalidStatusTransition,
    NotFound,
    PermissionDenied,
    VersionConflict,
)
from app.models import Order, OrderStatus, OrderStatusHistory, User
from app.schemas.workflow import StatusChange, VersionInput
from app.services import order_service
from tests.test_authentication import login, token
from tests.test_clients import business_setup as business_fixture  # noqa: F401
from tests.test_orders import create_one
from tests.test_orders import order_setup as base_order_setup


@pytest.fixture(name="order_setup")
def workflow_setup(business_setup):
    return base_order_setup.__wrapped__(business_setup)


EXPECTED = {
    (OrderStatus.NEW, OrderStatus.CONFIRMED),
    (OrderStatus.CONFIRMED, OrderStatus.IN_PROGRESS),
    (OrderStatus.IN_PROGRESS, OrderStatus.READY),
    (OrderStatus.READY, OrderStatus.COMPLETED),
    *((s, OrderStatus.CANCELLED) for s in list(OrderStatus)[:4]),
}


@pytest.mark.parametrize("old", list(OrderStatus))
@pytest.mark.parametrize("new", list(OrderStatus))
def test_all_transition_pairs(old, new):
    if (old, new) in EXPECTED:
        order_service.validate_transition(old, new)
    else:
        with pytest.raises(InvalidStatusTransition):
            order_service.validate_transition(old, new)


@pytest.mark.postgres
@pytest.mark.parametrize("old", list(OrderStatus))
@pytest.mark.parametrize("new", list(OrderStatus))
def test_database_transition_pairs(order_setup, old, new):
    _, factory, _, users = order_setup
    order_id = create_one(order_setup)
    with factory() as session:
        order = session.get(Order, order_id)
        order.status = old
        session.commit()
        version = order.version
        actor = session.get(User, users["manager"])
        change = StatusChange(version=version, status=new, comment="Причина")
        if (old, new) in EXPECTED:
            order_service.change_status(session, actor, order_id, change)
            session.expire_all()
            order = session.get(Order, order_id)
            assert order.status == new and order.version == version + 1
            history = session.scalars(
                select(OrderStatusHistory).order_by(OrderStatusHistory.id)
            ).all()
            assert len(history) == 2
            assert (history[-1].old_status, history[-1].new_status) == (old, new)
            assert history[-1].changed_by_id == users["manager"]
            assert history[-1].comment == "Причина" and history[-1].changed_at == order.updated_at
        else:
            with pytest.raises((InvalidStatusTransition, PermissionDenied)):
                order_service.change_status(session, actor, order_id, change)
            assert session.get(Order, order_id).status == old
            assert session.scalar(select(func.count()).select_from(OrderStatusHistory)) == 1


@pytest.mark.postgres
def test_status_history_failure_rolls_back_everything(order_setup):
    _, factory, _, users = order_setup
    order_id = create_one(order_setup)
    with factory() as session:
        before = session.get(Order, order_id)
        version, updated = before.version, before.updated_at
        session.execute(
            text(
                "ALTER TABLE order_status_history ADD CONSTRAINT reject_next "
                "CHECK (new_status = 'NEW')"
            )
        )
        session.commit()
        with pytest.raises(IntegrityError):
            order_service.change_status(
                session,
                session.get(User, users["admin"]),
                order_id,
                StatusChange(version=version, status="CONFIRMED"),
            )
        current = session.get(Order, order_id)
        assert (current.status, current.version, current.updated_at) == (
            OrderStatus.NEW,
            version,
            updated,
        )
        assert session.scalar(select(func.count()).select_from(OrderStatusHistory)) == 1


@pytest.mark.postgres
def test_concurrent_status_changes_have_one_history_event(order_setup):
    _, factory, _, users = order_setup
    order_id = create_one(order_setup)
    barrier = Barrier(2)

    def change():
        with factory() as session:
            actor = session.get(User, users["admin"])
            barrier.wait(timeout=10)
            try:
                order_service.change_status(
                    session, actor, order_id, StatusChange(version=1, status="CONFIRMED")
                )
                return "ok"
            except VersionConflict:
                return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(lambda _: change(), range(2))) == ["conflict", "ok"]
    with factory() as session:
        assert session.get(Order, order_id).version == 2
        assert session.scalar(select(func.count()).select_from(OrderStatusHistory)) == 2


@pytest.mark.postgres
def test_archive_and_permissions(order_setup):
    app, factory, _, users = order_setup
    order_id = create_one(order_setup)
    with factory() as session:
        admin = session.get(User, users["admin"])
        with pytest.raises(InvalidArchive):
            order_service.archive(session, admin, order_id, VersionInput(version=1))
        with pytest.raises(PermissionDenied):
            order_service.change_status(
                session,
                session.get(User, users["other"]),
                order_id,
                StatusChange(version=1, status="CONFIRMED"),
            )
        with pytest.raises(NotFound):
            order_service.change_status(
                session,
                session.get(User, users["other"]),
                order_id,
                StatusChange(version=1, status="CONFIRMED"),
                "assigned",
            )
        order_service.change_status(
            session, admin, order_id, StatusChange(version=1, status="CANCELLED")
        )
        with pytest.raises(PermissionDenied):
            order_service.archive(
                session, session.get(User, users["manager"]), order_id, VersionInput(version=2)
            )
        with pytest.raises(VersionConflict):
            order_service.archive(session, admin, order_id, VersionInput(version=1))
        order_service.archive(session, admin, order_id, VersionInput(version=2))
        assert session.get(Order, order_id).is_archived
        assert session.scalar(select(func.count()).select_from(OrderStatusHistory)) == 2
    with TestClient(app) as browser:
        login(browser, email="manager@example.com")
        assert browser.get(f"/orders/{order_id}").status_code == 404
        assert (
            browser.post(
                f"/orders/{order_id}/archive",
                data={"version": 3, "csrf_token": token(browser.get("/orders"))},
            ).status_code
            == 403
        )
        login(browser)
        assert "Замовлення в архіві" in browser.get(f"/orders/{order_id}").text


@pytest.mark.postgres
def test_html_status_validation_conflict_csrf_and_lifecycle(order_setup):
    app, factory, _, _ = order_setup
    order_id = create_one(order_setup)
    path = f"/orders/{order_id}"
    with TestClient(app) as browser:
        login(browser)
        csrf = token(browser.get(path))
        assert (
            browser.post(path + "/status", data={"version": 1, "status": "CONFIRMED"}).status_code
            == 403
        )
        for status in ("READY", "INVALID"):
            response = browser.post(
                path + "/status",
                data={
                    "csrf_token": csrf,
                    "version": 1,
                    "status": status,
                    "comment": "Зберегти <script>",
                },
            )
            assert response.status_code == (409 if status == "READY" else 422)
            assert "Зберегти &lt;script&gt;" in response.text
        for version, status in enumerate(("CONFIRMED", "IN_PROGRESS", "READY", "COMPLETED"), 1):
            assert (
                browser.post(
                    path + "/status",
                    data={"csrf_token": csrf, "version": version, "status": status},
                    follow_redirects=False,
                ).status_code
                == 303
            )
            if version == 1:
                response = browser.post(
                    path + "/status",
                    data={
                        "csrf_token": csrf,
                        "version": 1,
                        "status": "CANCELLED",
                        "comment": "Стара форма",
                    },
                )
                assert response.status_code == 409 and "Стара форма" in response.text
        assert "Змінити статус</button>" not in browser.get(path).text
        assert browser.get(path + "/edit").status_code == 403
        assert (
            browser.post(
                path + "/status", data={"csrf_token": csrf, "version": 5, "status": "NEW"}
            ).status_code
            == 403
        )
        assert (
            browser.post(
                path + "/archive", data={"csrf_token": csrf, "version": 5}, follow_redirects=False
            ).status_code
            == 303
        )
        assert (
            browser.post(path + "/archive", data={"csrf_token": csrf, "version": 6}).status_code
            == 409
        )
        assert browser.get(path + "/history/edit").status_code == 404
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(OrderStatusHistory)) == 5

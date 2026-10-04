from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import event, select

from app.core.business_time import calendar_bounds
from app.core.errors import PermissionDenied
from app.core.order_rules import is_overdue
from app.models import Client, Order, OrderStatus, User
from app.schemas.order_filters import OrderFilters
from app.services import order_list_service
from tests.test_authentication import login
from tests.test_clients import business_setup as business_fixture  # noqa: F401

NOW = datetime(2026, 10, 4, 10, tzinfo=UTC)


@pytest.fixture(name="list_setup")
def list_setup_fixture(business_setup):
    app, factory = business_setup
    with factory() as session:
        users = {u.email.split("@")[0]: u.id for u in session.scalars(select(User))}
        clients = [Client(name="Альфа %_"), Client(name="Бета")]
        session.add_all(clients)
        session.flush()
        ids = []
        for index in range(25):
            order = Order(
                number=f"ORD-2026-{index + 1:04}",
                client_id=clients[index % 2].id,
                manager_id=users["manager" if index % 2 == 0 else "other"],
                status=list(OrderStatus)[index % 6],
                priority="HIGH" if index % 2 == 0 else "NORMAL",
                deadline_at=None if index % 5 == 0 else NOW + timedelta(days=index - 12),
                created_at=NOW - timedelta(days=index % 3),
                total_amount=Decimal(index // 2),
                is_archived=index == 23,
            )
            session.add(order)
            session.flush()
            ids.append(order.id)
        session.commit()
    return app, factory, ids, users


@pytest.mark.parametrize(
    "values",
    [
        {"sort": "comment"},
        {"sort": "created_at; DROP TABLE orders"},
        {"direction": "bad"},
        {"page": 0},
        {"page": 2147483648},
        {"page_size": "15"},
        {"status": "BAD"},
        {"manager_id": -1},
        {"overdue": "bad"},
        {"q": "x" * 201},
        {"extra": "bad"},
        {"start_date": "2026-10-05", "end_date": "2026-10-04"},
        {"end_date": "9999-12-31"},
    ],
)
def test_filter_validation(values):
    with pytest.raises(ValidationError):
        OrderFilters(**values)


@pytest.mark.parametrize(
    "status,archived,offset,expected",
    [
        ("NEW", False, -1, True),
        ("NEW", False, 0, False),
        ("NEW", False, 1, False),
        ("COMPLETED", False, -1, False),
        ("CANCELLED", False, -1, False),
        ("IN_PROGRESS", True, -1, False),
        ("NEW", False, None, False),
    ],
)
def test_overdue_exact_rule(status, archived, offset, expected):
    order = Order(
        status=OrderStatus(status),
        is_archived=archived,
        deadline_at=NOW + timedelta(seconds=offset) if offset is not None else None,
    )
    assert is_overdue(order, NOW) is expected


def test_calendar_bounds_follow_kyiv_dst_and_both_days():
    start, end = calendar_bounds(date(2026, 10, 25), date(2026, 10, 25))
    assert start == datetime(2026, 10, 24, 21, tzinfo=UTC)
    assert end == datetime(2026, 10, 25, 22, tzinfo=UTC)
    assert end - start == timedelta(hours=25)


@pytest.mark.postgres
def test_combined_filters_permissions_and_overdue_match_rows(list_setup):
    _, factory, ids, users = list_setup
    with factory() as session:
        admin, manager = session.get(User, users["admin"]), session.get(User, users["manager"])
        filters = OrderFilters(
            q="%_",
            status="IN_PROGRESS",
            priority="HIGH",
            manager_id=manager.id,
            overdue=True,
            start_date="2026-10-02",
            end_date="2026-10-04",
        )
        rows, total, _, _ = order_list_service.search(session, admin, filters, now=NOW)
        assert {r.id for r in rows} == {ids[2], ids[8]} and total == 2
        rows, total, _, _ = order_list_service.search(session, manager, OrderFilters(), now=NOW)
        assert total == 24
        rows, total, _, _ = order_list_service.search(
            session, manager, OrderFilters(), "assigned", now=NOW
        )
        assert total == 13 and all(r.manager_id == manager.id for r in rows)
        assert (
            order_list_service.search(
                session, manager, OrderFilters(manager_id=users["other"]), "assigned", now=NOW
            )[1]
            == 0
        )
        with pytest.raises(PermissionDenied):
            order_list_service.search(session, manager, OrderFilters(archived=True), now=NOW)
        rows, total, _, _ = order_list_service.search(
            session, admin, OrderFilters(archived=True), now=NOW
        )
        assert total == 1 and rows[0].id == ids[23]
        all_rows = session.scalars(select(Order)).all()
        overdue_rows = order_list_service.search(
            session, admin, OrderFilters(overdue=True), now=NOW
        )[0]
        assert {r.id for r in overdue_rows} == {r.id for r in all_rows if is_overdue(r, NOW)}


@pytest.mark.postgres
@pytest.mark.parametrize("sort", ["created_at", "deadline_at", "total_amount"])
@pytest.mark.parametrize("direction", ["asc", "desc"])
def test_sorting_stability_pagination_nulls_last_and_bounded_queries(list_setup, sort, direction):
    _, factory, ids, users = list_setup
    with factory() as session:
        actor = session.get(User, users["admin"])
        statements = []

        def record(conn, cursor, statement, parameters, context, many):
            statements.append(statement)

        engine = session.get_bind()
        event.listen(engine, "before_cursor_execute", record)
        try:
            observed = []
            for page in (1, 2, 3):
                rows, total, actual, pages = order_list_service.search(
                    session,
                    actor,
                    OrderFilters(sort=sort, direction=direction, page_size=10, page=page),
                    now=NOW,
                )
                assert total == 24 and pages == 3 and page == actual
                observed.extend(rows)
                for row in rows:
                    assert row.client.name and row.manager.first_name
            assert len(statements) == 6
        finally:
            event.remove(engine, "before_cursor_execute", record)
        assert len({r.id for r in observed}) == 24
        existing = session.scalars(select(Order).where(Order.is_archived.is_(False))).all()
        valued = [r for r in existing if getattr(r, sort) is not None]
        missing = [r for r in existing if getattr(r, sort) is None]
        expected = sorted(
            valued, key=lambda r: (getattr(r, sort), r.id), reverse=direction == "desc"
        )
        expected += sorted(missing, key=lambda r: r.id, reverse=direction == "desc")
        assert [r.id for r in observed] == [r.id for r in expected]
        assert order_list_service.search(session, actor, OrderFilters(page=999), now=NOW)[2] == 2


@pytest.mark.postgres
def test_period_includes_local_day_with_half_open_boundary(list_setup):
    _, factory, ids, users = list_setup
    lower, upper = calendar_bounds(date(2026, 10, 4), date(2026, 10, 4))
    with factory() as session:
        for index, instant in enumerate(
            (lower - timedelta(microseconds=1), lower, upper - timedelta(microseconds=1), upper)
        ):
            session.get(Order, ids[index]).created_at = instant
        session.commit()
        rows = order_list_service.search(
            session,
            session.get(User, users["admin"]),
            OrderFilters(start_date="2026-10-04", end_date="2026-10-04", page_size=50),
            now=NOW,
        )[0]
        selected = {r.id for r in rows}
        assert ids[1] in selected and ids[2] in selected
        assert ids[0] not in selected and ids[3] not in selected


@pytest.mark.postgres
def test_html_filters_pages_errors_badges_and_manager_actions(list_setup):
    app, _, ids, _ = list_setup
    with TestClient(app) as browser, patch("app.web.routes.orders.utc_now", return_value=NOW):
        login(browser)
        response = browser.get(
            "/orders?q=ORD&status=&priority=HIGH&page_size=10&sort=total_amount&direction=asc"
        )
        assert response.status_code == 200 and "Знайдено: 13" in response.text
        assert "page=2" in response.text and "priority=HIGH" in response.text
        assert "Прострочено" in response.text
        assert "Прострочено" in browser.get(f"/orders/{ids[2]}").text
        assert "Замовлень не знайдено" in browser.get("/orders?q=no-result").text
        response = browser.get("/orders?q=Зберегти&start_date=2026-10-05&end_date=2026-10-04")
        assert response.status_code == 422 and 'value="Зберегти"' in response.text
        assert browser.get("/orders?sort=comment").status_code == 422
        login(browser, email="manager@example.com")
        response = browser.get("/orders?page_size=50")
        assert f'href="/orders/{ids[0]}/edit"' in response.text
        assert f'href="/orders/{ids[1]}/edit"' not in response.text
        assert browser.get("/orders?archived=true").status_code == 403
        app.state.settings.manager_order_visibility = "assigned"
        assert f'href="/orders/{ids[1]}"' not in browser.get("/orders?page_size=50").text

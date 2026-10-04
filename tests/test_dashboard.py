import json
import re
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, select

from app.core.business_time import month_bounds
from app.models import Order, OrderStatus, OrderStatusHistory, User
from app.services import dashboard_service
from tests.test_authentication import login
from tests.test_clients import business_setup as business_fixture  # noqa: F401
from tests.test_order_list import NOW
from tests.test_order_list import list_setup_fixture as list_fixture  # noqa: F401


@pytest.mark.parametrize(
    "now,lower,upper",
    [
        (
            datetime(2026, 12, 31, 22, tzinfo=UTC),
            datetime(2026, 12, 31, 22, tzinfo=UTC),
            datetime(2027, 1, 31, 22, tzinfo=UTC),
        ),
        (
            datetime(2026, 12, 10, 10, tzinfo=UTC),
            datetime(2026, 11, 30, 22, tzinfo=UTC),
            datetime(2026, 12, 31, 22, tzinfo=UTC),
        ),
        (
            datetime(2026, 10, 31, 22, tzinfo=UTC),
            datetime(2026, 10, 31, 22, tzinfo=UTC),
            datetime(2026, 11, 30, 22, tzinfo=UTC),
        ),
        (
            datetime(2026, 3, 10, 0, tzinfo=UTC),
            datetime(2026, 2, 28, 22, tzinfo=UTC),
            datetime(2026, 3, 31, 21, tzinfo=UTC),
        ),
    ],
)
def test_month_bounds_kyiv_new_year_and_dst(now, lower, upper):
    assert month_bounds(now) == (lower, upper)


def add_completions(factory, ids, users):
    lower, upper = month_bounds(NOW)
    with factory() as session:
        for index, instant in [
            (4, lower - timedelta(microseconds=1)),
            (10, lower),
            (16, upper - timedelta(microseconds=1)),
            (22, upper),
            (23, lower),
        ]:
            order = session.get(Order, ids[index])
            order.status = OrderStatus.COMPLETED
            # updated_at deliberately differs from the completion event.
            order.updated_at = NOW
            session.add(
                OrderStatusHistory(
                    order_id=order.id,
                    old_status="READY",
                    new_status="COMPLETED",
                    changed_by_id=users["admin"],
                    changed_at=instant,
                )
            )
        session.commit()


@pytest.mark.postgres
def test_metrics_match_control_data_and_completion_event_not_updated_at(list_setup):
    _, factory, ids, users = list_setup
    add_completions(factory, ids, users)
    with factory() as session:
        result = dashboard_service.snapshot(session, session.get(User, users["admin"]), now=NOW)
        assert {
            key: result[key]
            for key in ("total", "new", "in_progress", "ready", "completed_month", "overdue")
        } == {
            "total": 24,
            "new": 5,
            "in_progress": 4,
            "ready": 4,
            "completed_month": 2,
            "overdue": 7,
        }
        assert result["by_status"] == {
            OrderStatus.NEW: 5,
            OrderStatus.CONFIRMED: 4,
            OrderStatus.IN_PROGRESS: 4,
            OrderStatus.READY: 4,
            OrderStatus.COMPLETED: 4,
            OrderStatus.CANCELLED: 3,
        }
        expected = session.scalars(
            select(Order)
            .where(Order.is_archived.is_(False))
            .order_by(Order.created_at.desc(), Order.id.desc())
            .limit(10)
        ).all()
        assert [o.id for o in result["recent"]] == [o.id for o in expected]
        assert len(result["upcoming"]) == 5
        assert all(
            o.deadline_at > NOW and o.status not in {OrderStatus.COMPLETED, OrderStatus.CANCELLED}
            for o in result["upcoming"]
        )
        assert [o.deadline_at for o in result["upcoming"]] == sorted(
            o.deadline_at for o in result["upcoming"]
        )


@pytest.mark.postgres
def test_visibility_consistent_in_metrics_chart_recent_and_deadlines(list_setup):
    _, factory, ids, users = list_setup
    add_completions(factory, ids, users)
    with factory() as session:
        manager = session.get(User, users["manager"])
        common = dashboard_service.snapshot(session, manager, now=NOW)
        assert common["total"] == 24
        own = dashboard_service.snapshot(session, manager, "assigned", now=NOW)
        assert own["total"] == 13 and own["completed_month"] == 2
        assert own["by_status"][OrderStatus.CONFIRMED] == 0
        assert all(o.manager_id == manager.id for o in own["recent"] + own["upcoming"])
        other = dashboard_service.snapshot(
            session, session.get(User, users["other"]), "assigned", now=NOW
        )
        assert other["total"] == 11 and other["completed_month"] == 0
        assert sum(other["by_status"].values()) == other["total"]


@pytest.mark.postgres
def test_snapshot_has_four_queries_without_n_plus_one(list_setup):
    _, factory, _, users = list_setup
    with factory() as session:
        actor = session.get(User, users["admin"])
        queries = []

        def record(conn, cursor, statement, parameters, context, many):
            queries.append(statement)

        engine = session.get_bind()
        event.listen(engine, "before_cursor_execute", record)
        try:
            data = dashboard_service.snapshot(session, actor, now=NOW)
            for order in data["recent"] + data["upcoming"]:
                assert order.client.name and order.manager.first_name
            assert len(queries) == 4
        finally:
            event.remove(engine, "before_cursor_execute", record)


@pytest.mark.postgres
def test_html_chart_data_totals_and_visibility(list_setup):
    app, factory, ids, users = list_setup
    add_completions(factory, ids, users)
    with TestClient(app) as browser, patch("app.web.routes.workspace.utc_now", return_value=NOW):
        assert browser.get("/dashboard", follow_redirects=False).status_code == 303
        login(browser)
        response = browser.get("/dashboard")
        assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
        assert 'data-metric="total">24<' in response.text
        assert 'data-metric="completed_month">2<' in response.text
        chart = json.loads(
            re.search(r'id="status-chart-data">(.*?)</script>', response.text, re.S)[1]
        )
        assert chart["values"] == [5, 4, 4, 4, 4, 3]
        assert "chart.js@4.4.8" in response.text and "Таблиця містить усі значення" in response.text
        assert browser.get("/static/js/dashboard.js").status_code == 200
        login(browser, email="manager@example.com")
        app.state.settings.manager_order_visibility = "assigned"
        response = browser.get("/dashboard")
        assert 'data-metric="total">13<' in response.text
        assert all(f'href="/orders/{ids[index]}"' not in response.text for index in range(1, 25, 2))


@pytest.mark.postgres
def test_empty_dashboard_has_zero_metrics_and_clear_empty_states(business_setup):
    app, factory = business_setup
    with factory() as session:
        actor = session.scalar(select(User).where(User.email == "admin@example.com"))
        data = dashboard_service.snapshot(session, actor, now=NOW)
        assert data["total"] == 0 and data["completed_month"] == 0 and data["overdue"] == 0
        assert data["recent"] == [] and data["upcoming"] == []
        assert all(count == 0 for count in data["by_status"].values())
    with TestClient(app) as browser:
        login(browser)
        response = browser.get("/dashboard")
        assert response.status_code == 200 and "Замовлень ще немає" in response.text
        assert "Майбутніх дедлайнів немає" in response.text
        assert 'id="status-chart"' not in response.text

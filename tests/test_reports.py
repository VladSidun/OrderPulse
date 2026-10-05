import csv
import io
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import select

from app.core.errors import PermissionDenied
from app.models import Client, Order, OrderStatus, OrderStatusHistory, User
from app.schemas.report import ReportFilters
from app.services import order_service, report_service
from tests.test_authentication import login
from tests.test_clients import business_setup as business_fixture  # noqa: F401
from tests.test_orders import data


@pytest.fixture(name="reports_setup")
def setup_reports(business_setup):
    app, factory = business_setup
    with factory() as session:
        client = Client(
            name='=HYPERLINK("http://invalid");Кирилиця',
            phone="secret-phone",
            email="private@example.com",
            address="secret-address",
            note="secret-note",
        )
        session.add(client)
        session.commit()
        users = {row.email.split("@")[0]: row.id for row in session.scalars(select(User))}
        ids = []
        for index in range(14):
            order_id = order_service.create(
                session,
                session.get(User, users["admin"]),
                data(
                    client.id,
                    users["manager"] if index % 2 == 0 else users["other"],
                    comment="secret-order-comment",
                ),
            )
            ids.append(order_id)
            order = session.get(Order, order_id)
            order.created_at = datetime(2026, 3, 28, 22, tzinfo=UTC)
            # Kyiv March 29 begins 22:00 UTC March 28, ends 21:00 UTC March 29 (DST).
            if index in (0, 1, 2, 3):
                order.status = OrderStatus.COMPLETED
                completed_at = [
                    datetime(2026, 3, 28, 22, tzinfo=UTC),
                    datetime(2026, 3, 29, 20, 59, 59, tzinfo=UTC),
                    datetime(2026, 3, 29, 21, tzinfo=UTC),
                    datetime(2026, 3, 28, 21, 59, 59, tzinfo=UTC),
                ][index]
                session.add(
                    OrderStatusHistory(
                        order_id=order_id,
                        old_status=OrderStatus.READY,
                        new_status=OrderStatus.COMPLETED,
                        changed_by_id=users["admin"],
                        changed_at=completed_at,
                    )
                )
            if index == 13:
                order.status = OrderStatus.CANCELLED
                order.is_archived = True
            session.commit()
    return app, factory, users, ids


def parse(content):
    return list(csv.reader(io.StringIO(content.decode("utf-8-sig")), delimiter=";"))


@pytest.mark.parametrize(
    "values",
    [
        {"date_basis": "updated"},
        {"start_date": "2026-03-30", "end_date": "2026-03-29"},
        {"end_date": "9999-12-31"},
        {"manager_id": 0},
        {"page_size": 30},
        {"extra": "x"},
        {"page": 0},
        {"status": "INVALID"},
    ],
)
def test_report_filter_validation(values):
    with pytest.raises(ValidationError):
        ReportFilters(**values)


def test_completed_mode_forces_completed_and_optional_empty():
    filters = ReportFilters(date_basis="completed", status="NEW", manager_id="", start_date="")
    assert filters.status == OrderStatus.COMPLETED and filters.manager_id is None


@pytest.mark.parametrize(
    "value",
    ["=1+1", "+1", "-1", "@SUM(1)", "  =1", "\t1", "\r1", "\n1", "＝1", "＋1", "－1", "＠1"],
)
def test_formula_cells_are_neutralized(value):
    assert report_service.safe_cell(value) == "'" + value


@pytest.mark.postgres
def test_totals_export_all_pages_no_pii_and_csv_roundtrip(reports_setup):
    _, factory, users, ids = reports_setup
    filters = ReportFilters(page_size=10, page=2)
    with factory() as session:
        user = session.get(User, users["admin"])
        report = report_service.snapshot(session, user, filters)
        content = report_service.export_csv(session, user, filters)
        rows = parse(content)
        assert report["total"] == 13 and len(report["rows"]) == 3
        assert len(rows) == 14 and content.startswith(b"\xef\xbb\xbf")
        assert sum((Decimal(row[8]) for row in rows[1:]), Decimal("0")) == report["amount"]
        assert report["amount"] == Decimal("292.63")
        assert all(row[1].startswith("'=") and row[9] == "EUR" for row in rows[1:])
        assert rows[0][1] == "Клієнт" and len(rows[1]) == 10
        assert "Кирилиця" in rows[1][1] and ";" in rows[1][1]
        for sensitive in [
            "secret-phone",
            "private@example.com",
            "secret-address",
            "secret-note",
            "secret-order-comment",
        ]:
            assert sensitive not in content.decode("utf-8-sig")
        assert set(order.id for order, _ in report["rows"]).issubset(set(ids))


@pytest.mark.postgres
def test_completed_period_uses_history_dst_bounds_not_updated(reports_setup):
    _, factory, users, ids = reports_setup
    filters = ReportFilters(
        date_basis="completed",
        status="NEW",
        start_date=date(2026, 3, 29),
        end_date=date(2026, 3, 29),
    )
    with factory() as session:
        for order in session.scalars(select(Order)):
            order.updated_at = datetime(2030, 1, 1, tzinfo=UTC)
        session.commit()
        user = session.get(User, users["admin"])
        report = report_service.snapshot(session, user, filters)
        rows = parse(report_service.export_csv(session, user, filters))
        assert {order.id for order, _ in report["rows"]} == {ids[0], ids[1]}
        assert report["total"] == 2 and report["amount"] == Decimal("45.02")
        assert len(rows) == 3 and all(row[3] == "Завершене" for row in rows[1:])


@pytest.mark.postgres
def test_created_period_manager_and_status_filters(reports_setup):
    _, factory, users, _ = reports_setup
    with factory() as session:
        user = session.get(User, users["admin"])
        filters = ReportFilters(
            start_date="2026-03-29",
            end_date="2026-03-29",
            manager_id=users["manager"],
            status="NEW",
        )
        report = report_service.snapshot(session, user, filters)
        assert report["total"] == 5 and report["amount"] == Decimal("112.55")
        assert len(parse(report_service.export_csv(session, user, filters))) == 6
        empty = report_service.snapshot(
            session, user, ReportFilters(start_date="2026-03-30", end_date="2026-03-30")
        )
        assert empty["total"] == 0 and empty["amount"] == Decimal("0.00")


@pytest.mark.postgres
def test_visibility_archive_permissions_and_totals(reports_setup):
    _, factory, users, _ = reports_setup
    with factory() as session:
        admin, manager = session.get(User, users["admin"]), session.get(User, users["manager"])
        assert (
            report_service.snapshot(session, admin, ReportFilters(include_archived=True))["total"]
            == 14
        )
        assert report_service.snapshot(session, manager, ReportFilters(), "all")["total"] == 13
        report = report_service.snapshot(session, manager, ReportFilters(), "assigned")
        assert (
            report["total"] == 7
            and len(parse(report_service.export_csv(session, manager, ReportFilters(), "assigned")))
            == 8
        )
        assert (
            report_service.snapshot(
                session, manager, ReportFilters(manager_id=users["other"]), "assigned"
            )["total"]
            == 0
        )
        for action in (report_service.snapshot, report_service.export_csv):
            with pytest.raises(PermissionDenied):
                action(session, manager, ReportFilters(include_archived=True))


@pytest.mark.postgres
def test_report_http_filters_export_pagination_empty_and_permissions(reports_setup):
    app, _, users, _ = reports_setup
    with TestClient(app) as client:
        assert client.get("/reports", follow_redirects=False).status_code == 303
        login(client)
        report = client.get(
            "/reports?page_size=10&manager_id=&start_date=2026-03-29&end_date=2026-03-29"
        )
        assert report.status_code == 200 and 'data-report="total">13' in report.text
        assert "page=2" in report.text and "start_date=2026-03-29" in report.text
        export = client.get("/reports/export.csv?page=2&page_size=10")
        assert export.status_code == 200 and len(parse(export.content)) == 14
        assert "attachment" in export.headers["content-disposition"]
        invalid = client.get("/reports?start_date=2026-04-01&end_date=2026-03-29")
        assert invalid.status_code == 422 and 'value="2026-04-01"' in invalid.text
        assert "Початкова дата" in invalid.text
        assert client.get("/reports/export.csv?unknown=x").status_code == 422
        assert "замовлень немає" in client.get("/reports?start_date=2030-01-01").text
        completed = client.get("/reports?date_basis=completed&status=NEW")
        assert completed.status_code == 200 and 'value="COMPLETED" selected' in completed.text
        login(client, email="manager@example.com")
        assert client.get("/reports?include_archived=true").status_code == 403
        assert client.get("/reports/export.csv?include_archived=true").status_code == 403
        app.state.settings.manager_order_visibility = "assigned"
        assert 'data-report="total">7' in client.get("/reports").text
        assert len(parse(client.get("/reports/export.csv").content)) == 8

"""Cross-module acceptance using the public HTML and JSON interfaces."""

import csv
import io
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.models import User
from tests.test_authentication import login, token
from tests.test_clients import business_setup as business_fixture  # noqa: F401


@pytest.mark.postgres
def test_complete_business_lifecycle_and_html_api_parity(business_setup):
    app, factory = business_setup
    with factory() as session:
        manager_id = session.scalar(select(User.id).where(User.email == "manager@example.com"))

    with TestClient(app) as admin, TestClient(app) as manager, TestClient(app) as other:
        assert login(admin).status_code == 303
        assert login(manager, email="manager@example.com").status_code == 303
        assert login(other, email="other@example.com").status_code == 303
        headers = {"X-CSRF-Token": admin.get("/api/v1/csrf").json()["csrf_token"]}
        manager_headers = {"X-CSRF-Token": manager.get("/api/v1/csrf").json()["csrf_token"]}
        other_headers = {"X-CSRF-Token": other.get("/api/v1/csrf").json()["csrf_token"]}

        created_client = admin.post(
            "/clients/new",
            data={"csrf_token": token(admin.get("/clients/new")), "name": "ТОВ Альфа"},
            follow_redirects=False,
        )
        assert created_client.status_code == 303
        client_id = int(created_client.headers["location"].split("/")[-1])
        created_order = admin.post(
            "/api/v1/orders",
            headers=headers,
            json={
                "client_id": client_id,
                "manager_id": manager_id,
                "deadline_at": (datetime.now(UTC) + timedelta(days=2)).isoformat(),
                "items": [
                    {"name": "Дизайн", "quantity": "2.00", "unit_price": "25.50"},
                    {"name": "Друк", "quantity": "0.50", "unit_price": "0.01"},
                ],
            },
        )
        assert created_order.status_code == 201
        order = created_order.json()
        order_id, number = order["id"], order["number"]
        api_path, html_path = f"/api/v1/orders/{order_id}", f"/orders/{order_id}"
        assert number.startswith("ORD-") and order["total_amount"] == "51.01"
        assert order["status"] == "NEW" and len(order["status_history"]) == 1
        assert "51.01 EUR" in admin.get(html_path).text

        # Read permissions and write permissions remain different in all mode.
        assert number in other.get(html_path).text
        assert 'href="' + html_path + '/edit"' not in other.get(html_path).text
        assert other.get(html_path + "/edit").status_code == 403
        assert other.patch(api_path, headers=other_headers, json={"version": 1}).status_code == 403
        assert manager.get("/users").status_code == 403

        changed = manager.patch(
            api_path,
            headers=manager_headers,
            json={"version": 1, "deadline_at": (datetime.now(UTC) - timedelta(days=1)).isoformat()},
        )
        assert changed.status_code == 200
        assert "Прострочено" in admin.get(html_path).text
        assert admin.get("/api/v1/orders?overdue=true").json()["total"] == 1
        assert number in admin.get("/dashboard").text
        assert number in admin.get("/orders?q=" + number).text
        assert 'data-report="amount">51.01 EUR' in admin.get("/reports").text

        # A stale client cannot overwrite the latest change.
        assert admin.patch(api_path, headers=headers, json={"version": 1}).status_code == 409
        version = changed.json()["version"]
        rejected = manager.post(
            api_path + "/status",
            headers=manager_headers,
            json={"version": version, "status": "READY"},
        )
        assert rejected.status_code == 409
        for target in ["CONFIRMED", "IN_PROGRESS", "READY", "COMPLETED"]:
            response = manager.post(
                html_path + "/status",
                data={
                    "csrf_token": manager_headers["X-CSRF-Token"],
                    "version": version,
                    "status": target,
                    "comment": "Погоджений етап",
                },
                follow_redirects=False,
            )
            assert response.status_code == 303
            current = admin.get(api_path).json()
            assert current["status"] == target
            version = current["version"]
        assert [row["new_status"] for row in current["status_history"]] == [
            "NEW",
            "CONFIRMED",
            "IN_PROGRESS",
            "READY",
            "COMPLETED",
        ]
        assert "Прострочено" not in admin.get(html_path).text
        assert admin.get("/api/v1/orders?overdue=true").json()["total"] == 0
        assert (
            manager.patch(api_path, headers=manager_headers, json={"version": version}).status_code
            == 403
        )
        assert number in admin.get("/reports?date_basis=completed").text
        rows = list(
            csv.reader(
                io.StringIO(
                    admin.get("/reports/export.csv?date_basis=completed").content.decode(
                        "utf-8-sig"
                    )
                ),
                delimiter=";",
            )
        )
        assert len(rows) == 2 and number in rows[1] and "51.01" in rows[1]

        archived = admin.post(
            html_path + "/archive",
            data={"version": version, "csrf_token": headers["X-CSRF-Token"]},
            follow_redirects=False,
        )
        assert archived.status_code == 303
        assert admin.get("/api/v1/orders").json()["total"] == 0
        assert admin.get("/api/v1/orders?archived=true").json()["total"] == 1
        assert number not in admin.get("/reports").text
        assert number in admin.get("/reports?include_archived=true").text
        assert manager.get(html_path).status_code == 404
        assert manager.get("/reports/export.csv?include_archived=true").status_code == 403
        assert (
            manager.post(
                "/logout",
                data={"csrf_token": manager_headers["X-CSRF-Token"]},
                follow_redirects=False,
            ).status_code
            == 303
        )
        assert manager.get("/api/v1/orders").status_code == 401

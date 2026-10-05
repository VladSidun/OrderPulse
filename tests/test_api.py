from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError

from app.models import Client, Order, OrderStatusHistory
from app.schemas.api import ClientPatch, OrderPatch
from tests.test_authentication import login
from tests.test_clients import business_setup as business_fixture  # noqa: F401
from tests.test_orders import create_one  # noqa: F401
from tests.test_orders import order_setup as order_fixture  # noqa: F401


def headers(client):
    response = client.get("/api/v1/csrf")
    assert response.status_code == 200
    return {"X-CSRF-Token": response.json()["csrf_token"]}


def order_data(client_id, manager_id=None, **overrides):
    return (
        dict(
            client_id=client_id,
            manager_id=manager_id,
            items=[
                dict(name="Дизайн", quantity="0.50", unit_price="0.01"),
                dict(name="Друк", quantity="2.25", unit_price="10.00"),
            ],
        )
        | overrides
    )


@pytest.mark.parametrize(
    "values",
    [
        {"version": True},
        {"version": 1.5},
        {"version": 0},
        {"version": 1, "items": []},
        {"version": 1, "items": None},
        {"version": 1, "client_id": None},
        {"version": 1, "priority": None},
        {"version": 1, "manager_id": True},
        {"version": 1, "status": "READY"},
        {"version": 1, "total_amount": "0"},
        {"version": 1, "deadline_at": "2026-10-04T14:00:00"},
    ],
)
def test_order_patch_validation(values):
    with pytest.raises(ValidationError):
        OrderPatch(**values)


def test_client_patch_distinguishes_omitted_and_null():
    assert ClientPatch(note=None).model_dump(exclude_unset=True) == {"note": None}
    assert ClientPatch().model_dump(exclude_unset=True) == {}
    with pytest.raises(ValidationError):
        ClientPatch(name=None)


@pytest.mark.postgres
@pytest.mark.parametrize(
    "method,path",
    [
        ("POST", "/api/v1/clients"),
        ("PATCH", "/api/v1/clients/1"),
        ("POST", "/api/v1/orders"),
        ("PATCH", "/api/v1/orders/1"),
        ("POST", "/api/v1/orders/1/status"),
    ],
)
def test_each_api_mutation_rejects_missing_csrf_before_writing(business_setup, method, path):
    app, factory = business_setup
    with TestClient(app) as client:
        login(client)
        response = client.request(method, path, json={})
        assert response.status_code == 403 and "detail" in response.json()
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(Client)) == 0
        assert session.scalar(select(func.count()).select_from(Order)) == 0


@pytest.mark.postgres
def test_anonymous_api_returns_401_json_without_redirect(business_setup):
    app, _ = business_setup
    with TestClient(app) as client:
        for method, path in [
            ("GET", "/api/v1/csrf"),
            ("GET", "/api/v1/orders"),
            ("GET", "/api/v1/orders/1"),
            ("GET", "/api/v1/clients"),
            ("POST", "/api/v1/orders"),
            ("PATCH", "/api/v1/orders/1"),
            ("POST", "/api/v1/orders/1/status"),
            ("POST", "/api/v1/clients"),
            ("PATCH", "/api/v1/clients/1"),
        ]:
            response = client.request(
                method, path, json={} if method != "GET" else None, follow_redirects=False
            )
            assert response.status_code == 401 and "detail" in response.json()
            assert (
                "location" not in response.headers
                and response.headers["cache-control"] == "no-store"
            )


@pytest.mark.postgres
def test_clients_api_partial_updates_search_paging_and_csrf(business_setup):
    app, factory = business_setup
    with TestClient(app) as client:
        login(client, email="manager@example.com")
        csrf = headers(client)
        created = client.post(
            "/api/v1/clients",
            headers=csrf,
            json={
                "name": "ТОВ Альфа",
                "email": " ALPHA@Example.com ",
                "phone": "123",
                "note": "Примітка",
            },
        )
        assert created.status_code == 201
        original = created.json()
        assert original["email"] == "alpha@example.com" and original["name"] == "ТОВ Альфа"
        client_id = original["id"]
        updated = client.patch(f"/api/v1/clients/{client_id}", headers=csrf, json={"note": None})
        assert updated.status_code == 200 and updated.json()["note"] is None
        assert (
            updated.json()["name"] == original["name"]
            and updated.json()["email"] == original["email"]
        )
        page = client.get("/api/v1/clients?q=Альфа&page_size=10").json()
        assert set(page) == {"items", "total", "page", "page_size"}
        assert (
            page["total"] == 1 and page["page_size"] == 10 and page["items"][0]["id"] == client_id
        )
        assert client.get("/api/v1/clients?q=%25").json()["total"] == 0
        assert (
            client.patch(f"/api/v1/clients/{client_id}", json={"name": "Інша"}).status_code == 403
        )
        assert (
            client.post(
                "/api/v1/clients", json={"name": "Інша"}, headers={"X-CSRF-Token": "wrong"}
            ).status_code
            == 403
        )
        assert (
            client.patch(
                f"/api/v1/clients/{client_id}", headers=csrf, json={"name": None}
            ).status_code
            == 422
        )
        assert (
            client.patch("/api/v1/clients/999999", headers=csrf, json={"name": "Інша"}).status_code
            == 404
        )
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(Client)) == 1


@pytest.mark.postgres
def test_order_api_creation_decimal_partial_items_and_version(request):
    app, factory, client_id, users = request.getfixturevalue("order_fixture")
    with TestClient(app) as client:
        login(client)
        csrf = headers(client)
        created = client.post(
            "/api/v1/orders",
            headers=csrf,
            json=order_data(
                client_id,
                users["manager"],
                deadline_at=(datetime.now(UTC) + timedelta(days=1)).isoformat(),
                comment="Коментар",
            ),
        )
        assert created.status_code == 201
        order = created.json()
        assert (
            order["total_amount"] == "22.51"
            and order["currency"] == "EUR"
            and order["version"] == 1
        )
        assert [item["line_total"] for item in order["items"]] == ["0.01", "22.50"]
        assert (
            len(order["status_history"]) == 1 and order["status_history"][0]["new_status"] == "NEW"
        )
        assert created.headers["location"] == f"/api/v1/orders/{order['id']}"
        assert (
            "password_hash" not in created.text
            and "auth_version" not in created.text
            and "admin@example.com" not in created.text
        )
        path = f"/api/v1/orders/{order['id']}"
        patched = client.patch(
            path, headers=csrf, json={"version": 1, "comment": None, "deadline_at": None}
        )
        assert patched.status_code == 200
        result = patched.json()
        assert (
            result["version"] == 2 and result["comment"] is None and result["deadline_at"] is None
        )
        assert result["items"] == order["items"] and result["client_id"] == client_id
        replaced = client.patch(
            path,
            headers=csrf,
            json={
                "version": 2,
                "items": [{"name": "Інша", "quantity": "2.00", "unit_price": "4.00"}],
            },
        )
        assert replaced.status_code == 200 and replaced.json()["total_amount"] == "8.00"
        assert len(replaced.json()["items"]) == 1 and replaced.json()["version"] == 3
        conflict = client.patch(path, headers=csrf, json={"version": 1, "comment": "Застарілий"})
        assert conflict.status_code == 409 and "detail" in conflict.json()
        assert client.get(path).json()["comment"] is None
        page = client.get("/api/v1/orders?page_size=10&sort=total_amount&direction=asc").json()
        assert set(page) == {"items", "total", "page", "page_size"} and page["total"] == 1
        assert page["items"][0]["total_amount"] == "8.00" and "items" not in page["items"][0]
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(Order)) == 1


@pytest.mark.postgres
def test_status_workflow_response_history_terminal_and_html_parity(request):
    setup = request.getfixturevalue("order_fixture")
    app, _, _, _ = setup
    order_id = create_one(setup)
    with TestClient(app) as client:
        login(client, email="manager@example.com")
        csrf = headers(client)
        path = f"/api/v1/orders/{order_id}"
        assert (
            client.post(
                path + "/status", headers=csrf, json={"version": 1, "status": "READY"}
            ).status_code
            == 409
        )
        for version, status in enumerate(
            ["CONFIRMED", "IN_PROGRESS", "READY", "COMPLETED"], start=1
        ):
            response = client.post(
                path + "/status",
                headers=csrf,
                json={"version": version, "status": status, "comment": "Перехід"},
            )
            assert response.status_code == 200
            order = response.json()
            assert order["version"] == version + 1 and order["status"] == status
            assert (
                len(order["status_history"]) == version + 1
                and order["status_history"][-1]["new_status"] == status
            )
            assert order["status_history"][-1]["changed_by"]["id"] == order["manager_id"]
            assert "Статус" in client.get(f"/orders/{order_id}").text
        assert (
            client.patch(path, headers=csrf, json={"version": 5, "comment": "Зміна"}).status_code
            == 403
        )
        assert (
            client.post(
                path + "/status", headers=csrf, json={"version": 5, "status": "CANCELLED"}
            ).status_code
            == 403
        )
        assert client.delete(path, headers=csrf).status_code == 405
        assert client.post(path + "/archive", headers=csrf, json={"version": 5}).status_code == 404


@pytest.mark.postgres
def test_manager_permissions_assignment_all_assigned_and_archive(request):
    setup = request.getfixturevalue("order_fixture")
    app, _, client_id, users = setup
    other_order = create_one(setup, manager_id=users["other"])
    with TestClient(app) as client:
        login(client, email="manager@example.com")
        csrf = headers(client)
        path = f"/api/v1/orders/{other_order}"
        assert client.get(path).status_code == 200
        assert (
            client.patch(path, headers=csrf, json={"version": 1, "comment": "Зміна"}).status_code
            == 403
        )
        assert (
            client.post(
                path + "/status", headers=csrf, json={"version": 1, "status": "CONFIRMED"}
            ).status_code
            == 403
        )
        assert (
            client.post(
                "/api/v1/orders", headers=csrf, json=order_data(client_id, users["other"])
            ).status_code
            == 403
        )
        created = client.post("/api/v1/orders", headers=csrf, json=order_data(client_id))
        assert created.status_code == 201 and created.json()["manager_id"] == users["manager"]
        own_path = f"/api/v1/orders/{created.json()['id']}"
        assert (
            client.patch(
                own_path, headers=csrf, json={"version": 1, "manager_id": users["other"]}
            ).status_code
            == 403
        )
        assert client.get("/api/v1/orders").json()["total"] == 2
        assert client.get("/api/v1/orders?archived=true").status_code == 403
        app.state.settings.manager_order_visibility = "assigned"
        assert client.get(path).status_code == 404
        assert client.get("/api/v1/orders").json()["total"] == 1
        assert client.get(f"/api/v1/orders?manager_id={users['other']}").json()["total"] == 0


@pytest.mark.postgres
@pytest.mark.parametrize(
    "overrides",
    [
        {"status": "COMPLETED"},
        {"number": "ORD-MANUAL"},
        {"is_archived": True},
        {"version": 100},
        {"total_amount": "0"},
        {"deadline_at": "2026-10-04T15:00:00"},
        {"items": [{"name": "Неправильне", "quantity": 1.5, "unit_price": "1.00"}]},
        {"items": [{"name": "Неправильне", "quantity": "1.001", "unit_price": "1.00"}]},
    ],
)
def test_api_rejects_unknown_and_invalid_order_inputs(request, overrides):
    app, _, client_id, users = request.getfixturevalue("order_fixture")
    with TestClient(app) as client:
        login(client)
        response = client.post(
            "/api/v1/orders",
            headers=headers(client),
            json=order_data(client_id, users["manager"], **overrides),
        )
        assert response.status_code == 422 and "detail" in response.json()
        assert client.get("/api/v1/orders").json()["total"] == 0


@pytest.mark.postgres
def test_api_business_400_schema_422_notfound_and_bad_query(request):
    app, _, client_id, users = request.getfixturevalue("order_fixture")
    with TestClient(app) as client:
        login(client)
        csrf = headers(client)
        for values in [
            order_data(999999, users["manager"]),
            order_data(client_id, None),
            order_data(client_id, users["admin"]),
            order_data(client_id, users["manager"], deadline_at="2020-01-01T00:00:00Z"),
        ]:
            assert client.post("/api/v1/orders", headers=csrf, json=values).status_code == 400
        assert client.get("/api/v1/orders/999999").status_code == 404
        assert (
            client.patch("/api/v1/orders/999999", headers=csrf, json={"version": 1}).status_code
            == 404
        )
        assert (
            client.patch(
                "/api/v1/orders/1", headers=csrf, json={"comment": "No version"}
            ).status_code
            == 422
        )
        for query in [
            "unknown=x",
            "sort=number",
            "start_date=2026-10-05&end_date=2026-10-04",
            "start_date=0001-01-01",
            "page_size=30",
        ]:
            assert client.get("/api/v1/orders?" + query).status_code == 422
        assert client.get("/api/v1/clients?unknown=x").status_code == 422


@pytest.mark.postgres
def test_concurrent_api_patch_returns_one_success_one_conflict(request):
    setup = request.getfixturevalue("order_fixture")
    app, factory, _, _ = setup
    order_id = create_one(setup)
    barrier = Barrier(2)

    def mutate(comment):
        with TestClient(app) as client:
            login(client)
            csrf = headers(client)
            barrier.wait(timeout=10)
            return client.patch(
                f"/api/v1/orders/{order_id}", headers=csrf, json={"version": 1, "comment": comment}
            ).status_code

    with ThreadPoolExecutor(2) as pool:
        assert sorted(pool.map(mutate, ["Перша", "Друга"])) == [200, 409]
    with factory() as session:
        order = session.get(Order, order_id)
        assert order.version == 2 and order.comment in {"Перша", "Друга"}
        assert session.scalar(select(func.count()).select_from(OrderStatusHistory)) == 1


@pytest.mark.postgres
def test_ready_db_failures_and_unexpected_errors_are_safe_json(business_setup):
    app, _ = business_setup
    with TestClient(app, raise_server_exceptions=False) as client:
        assert client.get("/ready").json() == {"status": "ready"}
        login(client)
        error = OperationalError("secret-sql", {}, Exception("secret-database-password"))
        with patch("app.repositories.order_list_repository.search", side_effect=error):
            response = client.get("/api/v1/orders")
            assert response.status_code == 503
            assert "secret" not in response.text and "detail" in response.json()
        with patch(
            "app.repositories.order_list_repository.search",
            side_effect=RuntimeError("private-traceback"),
        ):
            response = client.get("/api/v1/orders")
            assert response.status_code == 500 and "private-traceback" not in response.text
            assert "detail" in response.json()
        with patch.object(app.state, "database_factory", side_effect=error):
            response = client.get("/ready")
            assert response.status_code == 503 and response.json() == {"status": "unavailable"}
        assert client.get("/health").status_code == 200


def test_openapi_describes_endpoints_cookie_csrf_money_strings_and_partial_updates(client):
    schema = client.get("/openapi.json").json()
    expected = {
        "/api/v1/csrf",
        "/api/v1/orders",
        "/api/v1/orders/{order_id}",
        "/api/v1/orders/{order_id}/status",
        "/api/v1/clients",
        "/api/v1/clients/{client_id}",
        "/ready",
        "/health",
    }
    assert set(schema["paths"]) == expected
    assert schema["components"]["securitySchemes"]["SessionCookie"]["in"] == "cookie"
    operation = schema["paths"]["/api/v1/orders"]["post"]
    assert operation["security"] == [{"SessionCookie": []}]
    assert any(param["name"] == "X-CSRF-Token" for param in operation["parameters"])
    assert (
        schema["components"]["schemas"]["OrderRead"]["properties"]["total_amount"]["type"]
        == "string"
    )
    assert schema["components"]["schemas"]["OrderPatch"]["required"] == ["version"]
    assert schema["components"]["schemas"]["ClientPatch"]["additionalProperties"] is False

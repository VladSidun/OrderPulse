"""Public navigation and progressive enhancement contracts of the product UI."""

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.models import Order
from tests.test_authentication import login, token
from tests.test_clients import business_setup as business_fixture  # noqa: F401
from tests.test_orders import create_one, form_data
from tests.test_orders import order_setup as order_setup_fixture  # noqa: F401


def test_public_landing_has_real_login_and_section_targets_without_database(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "Кожне замовлення." in response.text
    assert "Демонстраційні дані" in response.text
    for section in ("features", "workflow", "team"):
        assert f'href="#{section}"' in response.text
        assert f'id="{section}"' in response.text
    assert 'href="/login"' in response.text
    assert "login-dialog" not in response.text
    assert "data-select" not in response.text
    assert response.headers["cache-control"] == "no-store"


def test_draft_rows_without_js_preserve_values_and_never_save(request):
    order_setup = request.getfixturevalue("order_setup_fixture")
    app, factory, client_id, users = order_setup
    with TestClient(app) as browser:
        login(browser)
        values = form_data(token(browser.get("/orders/new")), client_id, users["manager"])
        response = browser.post("/orders/new", data={**values, "_items_action": "add"})
        assert response.status_code == 200
        assert 'name="items.2.name"' in response.text
        assert 'value="Послуга &lt;script&gt;"' in response.text
        assert "Коментар &lt;script&gt;" in response.text
        response = browser.post("/orders/new", data={**values, "_items_action": "remove:0"})
        assert response.status_code == 200
        assert 'value="Друга"' in response.text
        assert 'name="items.1.name"' not in response.text.split("<template")[0]
        with factory() as session:
            assert session.scalar(select(func.count(Order.id))) == 0
        browser.post("/orders/new", data={**values, "_items_action": "add", "csrf_token": "bad"})
        with factory() as session:
            assert session.scalar(select(func.count(Order.id))) == 0


def test_draft_rows_keep_stale_version_and_enforce_bounds(request):
    order_setup = request.getfixturevalue("order_setup_fixture")
    app, factory, client_id, users = order_setup
    order_id = create_one(order_setup)
    with TestClient(app) as browser:
        login(browser)
        values = form_data(
            token(browser.get(f"/orders/{order_id}/edit")), client_id, users["manager"], version="0"
        )
        response = browser.post(f"/orders/{order_id}/edit", data={**values, "_items_action": "add"})
        assert response.status_code == 200
        assert 'name="version" value="0"' in response.text
        one = {key: value for key, value in values.items() if not key.startswith("items.1.")}
        response = browser.post(
            f"/orders/{order_id}/edit", data={**one, "_items_action": "remove:0"}
        )
        assert response.status_code == 422
        hundred = {key: value for key, value in values.items() if not key.startswith("items.")}
        hundred.update({f"items.{i}.name": "Позиція" for i in range(100)})
        response = browser.post(
            f"/orders/{order_id}/edit", data={**hundred, "_items_action": "add"}
        )
        assert response.status_code == 422
        assert 'name="items.100.name"' not in response.text
        with factory() as session:
            assert session.get(Order, order_id).version == 1


def test_new_item_template_never_inherits_server_row_errors(request):
    app, _, client_id, users = request.getfixturevalue("order_setup_fixture")
    with TestClient(app) as browser:
        login(browser)
        values = form_data(token(browser.get("/orders/new")), client_id, users["manager"])
        values["items.0.quantity"] = "0"
        response = browser.post("/orders/new", data=values)
        assert response.status_code == 422
        assert 'aria-describedby="items.0.quantity-error"' in response.text
        template = response.text.split("<template data-item-template>", 1)[1].split(
            "</template>", 1
        )[0]
        assert "aria-invalid" not in template
        assert "aria-describedby" not in template
        assert 'id="items.0.quantity-error"' not in template

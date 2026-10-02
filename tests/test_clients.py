from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import func, select

from app.core.config import Settings
from app.core.errors import AuthenticationRequired
from app.core.security import hash_password
from app.db.session import create_session_factory
from app.main import create_app
from app.models import Client, Order, OrderStatus, User, UserRole
from app.repositories import client_repository
from app.schemas.client import ClientInput
from app.services import client_service
from tests.test_authentication import TEST_PASSWORD, TEST_SECRET, login, token


@pytest.fixture
def business_setup(migrated_engine):
    factory = create_session_factory(migrated_engine)
    with factory() as session:
        for email, role in [
            ("admin@example.com", UserRole.ADMIN),
            ("manager@example.com", UserRole.MANAGER),
            ("other@example.com", UserRole.MANAGER),
        ]:
            session.add(
                User(
                    email=email,
                    role=role,
                    is_active=True,
                    first_name="Іван",
                    last_name="Петренко",
                    password_hash=hash_password(TEST_PASSWORD),
                )
            )
        session.commit()
    app = create_app(
        Settings(_env_file=None, app_env="testing", database_url=None, secret_key=TEST_SECRET)
    )
    app.state.database_factory = factory
    return app, factory


@pytest.mark.parametrize(
    "values",
    [
        {"name": "x"},
        {"name": " "},
        {"name": "x" * 161},
        {"name": "Клієнт", "email": "invalid"},
        {"name": "Клієнт", "phone": "x" * 51},
        {"name": "Клієнт", "address": "x" * 256},
        {"name": "Клієнт", "note": "x" * 2001},
        {"name": "Клієнт", "id": 10},
    ],
)
def test_client_validation(values):
    with pytest.raises(ValidationError):
        ClientInput(**values)


def test_normalization_and_optional_fields():
    data = ClientInput(name="  Клієнт  ", email=" USER@Example.com ", phone=" ", note="")
    assert data.name == "Клієнт" and data.email == "user@example.com"
    assert data.phone is None and data.note is None


@pytest.mark.postgres
@pytest.mark.parametrize("email", ["admin@example.com", "manager@example.com"])
def test_client_lifecycle_validation_csrf_and_no_delete(business_setup, email):
    app, factory = business_setup
    with TestClient(app) as browser:
        assert browser.get("/clients/new", follow_redirects=False).status_code == 303
        login(browser, email=email)
        csrf = token(browser.get("/clients/new"))
        assert browser.post("/clients/new", data={"name": "Клієнт"}).status_code == 403
        response = browser.post(
            "/clients/new",
            data={
                "name": "Клієнт <script>",
                "email": "invalid",
                "note": "Зберегти",
                "csrf_token": csrf,
            },
        )
        assert response.status_code == 422 and "Зберегти" in response.text
        assert "aria-invalid" in response.text and "<script>" not in response.text
        response = browser.post(
            "/clients/new",
            data={"name": "Клієнт <script>", "email": "USER@Example.com", "csrf_token": csrf},
            follow_redirects=False,
        )
        assert response.status_code == 303
        path = response.headers["location"]
        assert "&lt;script&gt;" in browser.get(path).text
        edit = browser.get(path + "/edit")
        assert 'value="user@example.com"' in edit.text
        response = browser.post(
            path + "/edit",
            data={"name": "Оновлений клієнт", "phone": "+380501234567", "csrf_token": csrf},
        )
        assert response.status_code == 200 and "Оновлений клієнт" in response.text
        assert "Оновлений клієнт" in browser.get("/clients?q=1234567").text
        assert "Клієнтів не знайдено" in browser.get("/clients?q=missing").text
        assert browser.delete(path, headers={"X-CSRF-Token": csrf}).status_code == 405
        assert browser.get("/clients/99999").status_code == 404
        assert browser.post("/clients/99999/edit", data={"csrf_token": csrf}).status_code == 404
    with factory() as session:
        assert session.scalar(select(func.count(Client.id))) == 1


@pytest.mark.postgres
def test_search_literal_wildcards_pagination_and_visibility(business_setup):
    app, factory = business_setup
    with factory() as session:
        manager = session.scalar(select(User).where(User.email == "manager@example.com"))
        other = session.scalar(select(User).where(User.email == "other@example.com"))
        client = Client(name="100% клієнт_", phone="+380", email="search@example.com")
        session.add(client)
        session.add_all([Client(name=f"Клієнт {i:02}") for i in range(25)])
        session.flush()
        for number, owner, archived in [
            ("OWN", manager, False),
            ("OTHER", other, False),
            ("ARCHIVED", manager, True),
        ]:
            session.add(
                Order(
                    number=number,
                    client=client,
                    manager=owner,
                    status=OrderStatus.NEW,
                    is_archived=archived,
                )
            )
        session.commit()
        client_id = client.id
        assert client_repository.search(session, "%", 1, 20)[1] == 1
        assert client_repository.search(session, "_", 1, 20)[1] == 1
        assert len(client_repository.search(session, "", 2, 20)[0]) == 6
        assert len(client_repository.visible_orders(session, client_id, manager, "all")) == 2
        assert len(client_repository.visible_orders(session, client_id, manager, "assigned")) == 1
    with TestClient(app) as browser:
        login(browser, email="manager@example.com")
        page = browser.get("/clients?q=Клієнт&page_size=10")
        assert "q=" in page.text and "page=2" in page.text and "page_size=10" in page.text
        assert "OTHER" in browser.get(f"/clients/{client_id}").text
        app.state.settings.manager_order_visibility = "assigned"
        detail = browser.get(f"/clients/{client_id}").text
        assert "OTHER" not in detail and "ARCHIVED" not in detail and "OWN" in detail


@pytest.mark.postgres
def test_service_rolls_back_failed_commit_and_rejects_inactive(business_setup):
    _, factory = business_setup
    with factory() as session:
        user = session.scalar(select(User))
        with patch.object(session, "commit", side_effect=RuntimeError("injected")):
            with pytest.raises(RuntimeError):
                client_service.save(session, user, ClientInput(name="Rollback"))
        assert session.scalar(select(func.count(Client.id))) == 0
        user.is_active = False
        with pytest.raises(AuthenticationRequired):
            client_service.save(session, user, ClientInput(name="Заборонено"))

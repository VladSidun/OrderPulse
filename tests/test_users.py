from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import func, select

from app.core.errors import DomainError, NotFound, PermissionDenied
from app.core.security import verify_password
from app.models import Order, OrderStatus, User, UserRole
from app.schemas.user import PasswordReset, UserCreate, UserUpdate
from app.schemas.workflow import StatusChange
from app.services import order_service, user_service
from tests.test_authentication import TEST_PASSWORD, login, token
from tests.test_clients import business_setup as business_fixture  # noqa: F401
from tests.test_orders import create_one  # noqa: F401
from tests.test_orders import order_setup as order_fixture  # noqa: F401


def values(**overrides):
    return dict(first_name="Олена", last_name="Приклад", role="MANAGER", is_active=True) | overrides


@pytest.mark.parametrize(
    "overrides",
    [
        {"first_name": "x"},
        {"last_name": "x" * 81},
        {"email": "invalid"},
        {"password": "short"},
        {"role": "OWNER"},
        {"auth_version": 100},
    ],
)
def test_user_validation(overrides):
    with pytest.raises(ValidationError):
        UserCreate(**(values(email="new@example.com", password=TEST_PASSWORD) | overrides))


@pytest.mark.postgres
def test_user_creation_duplicate_and_no_sensitive_data(business_setup):
    app, factory = business_setup
    with TestClient(app) as client:
        login(client)
        csrf = token(client.get("/users/new"))
        data = values(email=" New@Example.com ", password=TEST_PASSWORD, csrf_token=csrf)
        assert client.post("/users/new", data=data, follow_redirects=False).status_code == 303
        duplicate = client.post("/users/new", data=data)
        assert duplicate.status_code == 400
        assert TEST_PASSWORD not in duplicate.text
        assert 'value=" New@Example.com "' in duplicate.text
        listing = client.get("/users")
        assert "new@example.com" in listing.text
        assert "password_hash" not in listing.text and "$argon2" not in listing.text
    with factory() as session:
        target = session.scalar(select(User).where(User.email == "new@example.com"))
        assert verify_password(TEST_PASSWORD, target.password_hash)
        assert session.scalar(select(func.count()).select_from(User)) == 4


@pytest.mark.postgres
@pytest.mark.parametrize("role,active", [("MANAGER", True), ("ADMIN", False)])
def test_last_admin_protected_and_fields_preserved(business_setup, role, active):
    app, factory = business_setup
    with factory() as session:
        admin_id = session.scalar(select(User.id).where(User.role == UserRole.ADMIN))
    with TestClient(app) as client:
        login(client)
        response = client.post(
            f"/users/{admin_id}/edit",
            data=values(
                role=role,
                is_active=str(active).lower(),
                csrf_token=token(client.get("/users")),
            ),
        )
        assert response.status_code == 400 and "останнього" in response.text
        assert 'value="Олена"' in response.text
    with factory() as session:
        admin = session.get(User, admin_id)
        assert admin.is_active and admin.role == UserRole.ADMIN and admin.auth_version == 1


@pytest.mark.postgres
def test_concurrent_admin_deactivation_preserves_one(business_setup):
    _, factory = business_setup
    with factory() as session:
        actor = session.scalar(select(User).where(User.role == UserRole.ADMIN))
        second_id = user_service.create(
            session,
            actor,
            UserCreate(**values(email="second@example.com", password=TEST_PASSWORD, role="ADMIN")),
        )
        first_id = actor.id
    barrier = Barrier(2)

    def deactivate(user_id):
        with factory() as session:
            actor = session.get(User, user_id)
            barrier.wait(timeout=10)
            try:
                user_service.update(
                    session, actor, user_id, UserUpdate(**values(role="ADMIN", is_active=False))
                )
                return "ok"
            except DomainError:
                return "blocked"

    with ThreadPoolExecutor(2) as pool:
        outcomes = list(pool.map(deactivate, [first_id, second_id]))
    assert sorted(outcomes) == ["blocked", "ok"]
    with factory() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(User)
                .where(User.role == UserRole.ADMIN, User.is_active.is_(True))
            )
            == 1
        )


@pytest.mark.postgres
@pytest.mark.parametrize("role,active", [("ADMIN", True), ("MANAGER", False)])
def test_manager_requires_reassignment_but_keeps_terminal_history(request, role, active):
    setup = request.getfixturevalue("order_fixture")
    _, factory, _, users = setup
    order_id = create_one(setup)
    with factory() as session:
        admin = session.get(User, users["admin"])
        with pytest.raises(DomainError, match="перепризначте"):
            user_service.update(
                session, admin, users["manager"], UserUpdate(**values(role=role, is_active=active))
            )
        order = session.get(Order, order_id)
        order_service.change_status(
            session, admin, order_id, StatusChange(version=order.version, status="CANCELLED")
        )
        user_service.update(
            session, admin, users["manager"], UserUpdate(**values(role=role, is_active=active))
        )
        order = session.get(Order, order_id)
        assert order.manager_id == users["manager"] and order.status == OrderStatus.CANCELLED
        session.expire(order, ["status_history"])
        assert len(order.status_history) == 2


@pytest.mark.postgres
@pytest.mark.parametrize("action", ["password", "deactivate", "role"])
def test_changes_revoke_existing_sessions(business_setup, action):
    app, factory = business_setup
    with factory() as session:
        manager_id = session.scalar(select(User.id).where(User.email == "manager@example.com"))
    with TestClient(app) as admin, TestClient(app) as manager:
        login(admin)
        login(manager, email="manager@example.com")
        csrf = token(admin.get("/users"))
        if action == "password":
            response = admin.post(
                f"/users/{manager_id}/password",
                data={"csrf_token": csrf, "password": "New-password-123!"},
                follow_redirects=False,
            )
        else:
            response = admin.post(
                f"/users/{manager_id}/edit",
                data=values(
                    role="ADMIN" if action == "role" else "MANAGER",
                    is_active="false" if action == "deactivate" else "true",
                    csrf_token=csrf,
                ),
                follow_redirects=False,
            )
        assert response.status_code == 303
        assert manager.get("/dashboard", follow_redirects=False).status_code == 303
        if action == "password":
            assert login(manager, email="manager@example.com").status_code == 401
            assert (
                login(
                    manager, email="manager@example.com", password="New-password-123!"
                ).status_code
                == 303
            )
    with factory() as session:
        assert session.get(User, manager_id).auth_version == 2


@pytest.mark.postgres
def test_admin_only_csrf_validation_missing_and_password_redaction(business_setup):
    app, factory = business_setup
    with factory() as session:
        manager_id = session.scalar(select(User.id).where(User.email == "manager@example.com"))
    with TestClient(app) as client:
        login(client, email="manager@example.com")
        csrf = token(client.get("/dashboard"))
        for path in ("/users", "/users/new", f"/users/{manager_id}/edit"):
            assert client.get(path).status_code == 403
        for path in ("/users/new", f"/users/{manager_id}/edit", f"/users/{manager_id}/password"):
            assert client.post(path, data={"csrf_token": csrf}).status_code == 403
        login(client)
        csrf = token(client.get("/users"))
        for path in ("/users/new", f"/users/{manager_id}/edit", f"/users/{manager_id}/password"):
            assert client.post(path, data={}).status_code == 403
        bad = client.post(
            f"/users/{manager_id}/password", data={"csrf_token": csrf, "password": "secret"}
        )
        assert bad.status_code == 422 and "secret" not in bad.text
        assert client.get("/users/999999/edit").status_code == 404
        extra = client.post(
            f"/users/{manager_id}/edit", data=values(email="changed@example.com", csrf_token=csrf)
        )
        assert extra.status_code == 422


@pytest.mark.postgres
def test_service_permissions_and_missing(business_setup):
    _, factory = business_setup
    with factory() as session:
        manager = session.scalar(select(User).where(User.role == UserRole.MANAGER))
        with pytest.raises(PermissionDenied):
            user_service.create(
                session,
                manager,
                UserCreate(**values(email="new@example.com", password=TEST_PASSWORD)),
            )
        admin = session.scalar(select(User).where(User.role == UserRole.ADMIN))
        with pytest.raises(NotFound):
            user_service.reset_password(
                session, admin, 999999, PasswordReset(password=TEST_PASSWORD)
            )

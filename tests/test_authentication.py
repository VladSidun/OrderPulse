import base64
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import Request
from fastapi.testclient import TestClient
from itsdangerous import TimestampSigner
from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from app.core.config import Settings
from app.core.dependencies import CurrentUser, get_web_db
from app.core.errors import SeedConflict
from app.core.security import SESSION_MAX_AGE, hash_password, verify_password
from app.db import seed
from app.db.session import create_session_factory
from app.main import create_app
from app.models import User, UserRole
from app.schemas.auth import AdminSeedInput
from app.services.seed_service import seed_admin

pytestmark = pytest.mark.postgres
TEST_SECRET = "session-signing-key-only-for-automated-tests"
TEST_PASSWORD = "Auth-test-password-123!"


def token(response):
    return re.search(r'name="csrf_token" value="([^"]+)"', response.text).group(1)


def sign_payload(data):
    return TimestampSigner(TEST_SECRET).sign(base64.b64encode(json.dumps(data).encode())).decode()


def payload(client):
    encoded = TimestampSigner(TEST_SECRET).unsign(client.cookies.get("order_session"))
    return json.loads(base64.b64decode(encoded))


def login(client, email="admin@example.com", password=TEST_PASSWORD, next="/dashboard"):
    csrf = token(client.get("/login"))
    return client.post(
        "/login",
        data={"email": email, "password": password, "csrf_token": csrf, "next": next},
        follow_redirects=False,
    )


@pytest.fixture
def auth_setup(migrated_engine):
    factory = create_session_factory(migrated_engine)
    with factory() as session:
        for email, role, active in [
            ("admin@example.com", UserRole.ADMIN, True),
            ("manager@example.com", UserRole.MANAGER, True),
            ("inactive@example.com", UserRole.ADMIN, False),
        ]:
            session.add(
                User(
                    email=email,
                    role=role,
                    is_active=active,
                    first_name="Іван",
                    last_name="Петренко",
                    password_hash=hash_password(TEST_PASSWORD),
                )
            )
        session.commit()
    app = create_app(
        Settings(
            _env_file=None,
            app_env="testing",
            debug=False,
            secret_key=TEST_SECRET,
            database_url=None,
        )
    )
    app.state.database_factory = factory

    @app.post("/test-cookie-api")
    def cookie_api(request: Request, user: CurrentUser):
        return {"user_id": user.id}

    return app, factory


@pytest.fixture
def auth_client(auth_setup):
    with TestClient(auth_setup[0]) as client:
        yield client


def test_admin_login_rotates_session_and_csrf_and_renders_layout(auth_client):
    initial = token(auth_client.get("/login"))
    response = login(auth_client, email=" ADMIN@Example.com ", next="/users")
    assert response.status_code == 303 and response.headers["location"] == "/users"
    data = payload(auth_client)
    assert set(data) == {"user_id", "auth_version", "logged_in_at", "csrf_token"}
    assert data["csrf_token"] != initial
    assert TEST_PASSWORD not in json.dumps(data) and "email" not in data
    assert "httponly" in response.headers["set-cookie"]
    assert "samesite=lax" in response.headers["set-cookie"]
    assert "Max-Age=28800" in response.headers["set-cookie"]
    dashboard = auth_client.get("/dashboard")
    assert dashboard.status_code == 200
    assert 'aria-current="page"' in dashboard.text
    assert "Іван Петренко" in dashboard.text and "Адміністратор" in dashboard.text
    assert 'action="http://testserver/logout" method="post"' in dashboard.text
    assert dashboard.headers["cache-control"] == "no-store"
    assert auth_client.get("/users").status_code == 200


def test_anonymous_redirects_to_login_with_local_next(auth_client):
    response = auth_client.get("/dashboard?view=all", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/login?next=%2Fdashboard%3Fview%3Dall"
    assert auth_client.get("/users", follow_redirects=False).status_code == 303


def test_manager_cannot_open_admin_route_or_see_its_navigation(auth_client):
    assert login(auth_client, email="manager@example.com").status_code == 303
    assert auth_client.get("/dashboard").status_code == 200
    assert "/users" not in auth_client.get("/dashboard").text
    response = auth_client.get("/users")
    assert response.status_code == 403
    assert "лише адміністратору" in response.text


@pytest.mark.parametrize(
    "email,password",
    [
        ("admin@example.com", "wrong-password"),
        ("missing@example.com", TEST_PASSWORD),
        ("inactive@example.com", TEST_PASSWORD),
    ],
)
def test_bad_credentials_and_inactive_have_identical_public_error(auth_client, email, password):
    response = login(auth_client, email=email, password=password)
    assert response.status_code == 401
    assert "Невірний email або пароль." in response.text
    assert email in response.text and password not in response.text
    assert "user_id" not in payload(auth_client)
    assert auth_client.get("/dashboard", follow_redirects=False).status_code == 303


@pytest.mark.parametrize(
    "email,password",
    [
        ("invalid-email", TEST_PASSWORD),
        ("admin@example.com", "short"),
        ("admin@example.com", "x" * 129),
        ("x" * 256 + "@example.com", TEST_PASSWORD),
    ],
)
def test_invalid_form_preserves_email_and_never_password(auth_client, email, password):
    response = login(auth_client, email=email, password=password)
    assert response.status_code == 422
    assert email in response.text and password not in response.text
    assert 'aria-invalid="true"' in response.text
    assert 'name="password" type="password" class="form-control" minlength' in response.text


def test_login_is_protected_from_csrf_and_old_token(auth_client):
    csrf = token(auth_client.get("/login"))
    for supplied in [None, "wrong", "неправильний"]:
        data = {"email": "admin@example.com", "password": TEST_PASSWORD}
        if supplied is not None:
            data["csrf_token"] = supplied
        assert auth_client.post("/login", data=data).status_code == 403
    assert login(auth_client).status_code == 303
    assert auth_client.post("/logout", data={"csrf_token": csrf}).status_code == 403
    assert auth_client.get("/dashboard").status_code == 200


def test_logout_revokes_all_sessions_and_replay_and_is_post_only(auth_setup):
    app, factory = auth_setup
    with TestClient(app) as first, TestClient(app) as second:
        login(first)
        login(second)
        stolen_cookie = first.cookies.get("order_session")
        assert first.get("/logout").status_code == 405
        assert first.post("/logout").status_code == 403
        csrf = token(first.get("/dashboard"))
        response = first.post("/logout", data={"csrf_token": csrf}, follow_redirects=False)
        assert response.status_code == 303 and response.headers["location"] == "/login"
        assert "expires=Thu, 01 Jan 1970" in response.headers["set-cookie"]
        assert first.get("/dashboard", follow_redirects=False).status_code == 303
        assert second.get("/dashboard", follow_redirects=False).status_code == 303
        first.cookies.set("order_session", stolen_cookie)
        assert first.get("/dashboard", follow_redirects=False).status_code == 303
        assert login(first).status_code == 303
    with factory() as session:
        assert (
            session.scalar(select(User).where(User.email == "admin@example.com")).auth_version == 2
        )


@pytest.mark.parametrize("change", ["inactive", "version", "role", "deleted"])
def test_user_is_reloaded_from_database_on_every_request(auth_setup, change):
    app, factory = auth_setup
    with TestClient(app) as client:
        login(client)
        with factory() as session:
            user = session.scalar(select(User).where(User.email == "admin@example.com"))
            if change == "inactive":
                user.is_active = False
            elif change == "version":
                user.auth_version += 1
            elif change == "role":
                user.role = UserRole.MANAGER
            else:
                session.delete(user)
            session.commit()
        response = client.get("/users", follow_redirects=False)
        assert response.status_code == (403 if change == "role" else 303)


@pytest.mark.parametrize("age", [SESSION_MAX_AGE, SESSION_MAX_AGE + 1, -100])
def test_absolute_session_expiry_cannot_be_extended_by_cookie_refresh(auth_client, age):
    login(auth_client)
    data = payload(auth_client)
    data["logged_in_at"] = int(time.time()) - age
    auth_client.cookies.clear()
    auth_client.cookies.set("order_session", sign_payload(data))
    assert auth_client.get("/dashboard", follow_redirects=False).status_code == 303


@pytest.mark.parametrize(
    "field,value",
    [("user_id", "1"), ("user_id", True), ("auth_version", 0), ("logged_in_at", "invalid")],
)
def test_invalid_signed_payload_is_rejected(auth_client, field, value):
    login(auth_client)
    data = payload(auth_client)
    data[field] = value
    auth_client.cookies.clear()
    auth_client.cookies.set("order_session", sign_payload(data))
    assert auth_client.get("/dashboard", follow_redirects=False).status_code == 303


def test_tampered_cookie_is_rejected(auth_client):
    login(auth_client)
    cookie = auth_client.cookies.get("order_session")
    auth_client.cookies.clear()
    auth_client.cookies.set("order_session", cookie[:-5] + "xxxxx")
    assert auth_client.get("/dashboard", follow_redirects=False).status_code == 303


@pytest.mark.parametrize("next", ["//evil.test", "https://evil.test", "/%2fevil.test"])
def test_login_never_redirects_to_external_origin(auth_client, next):
    response = login(auth_client, next=next)
    assert response.status_code == 303 and response.headers["location"] == "/dashboard"


def test_cookie_authenticated_json_requests_also_require_csrf(auth_client):
    login(auth_client)
    csrf = token(auth_client.get("/dashboard"))
    assert auth_client.post("/test-cookie-api", json={}).status_code == 403
    response = auth_client.post("/test-cookie-api", json={}, headers={"X-CSRF-Token": csrf})
    assert response.status_code == 200


def test_seed_is_idempotent_and_preserves_manual_edits_and_password(migrated_engine):
    factory = create_session_factory(migrated_engine)
    data = AdminSeedInput(
        email=" SEED@Example.com ",
        password=TEST_PASSWORD,
        first_name="Початковий",
        last_name="Адміністратор",
    )
    with factory() as session:
        assert seed_admin(session, data)
        admin = session.scalar(select(User))
        encoded = admin.password_hash
        assert verify_password(TEST_PASSWORD, encoded)
        admin.first_name = "Змінений"
        admin.auth_version = 5
        session.commit()
        data = AdminSeedInput(**{**data.model_dump(), "password": "another-password"})
        assert not seed_admin(session, data)
        session.expire_all()
        admin = session.scalar(select(User))
        assert admin.first_name == "Змінений" and admin.password_hash == encoded
        assert admin.auth_version == 5
        assert len(session.scalars(select(User)).all()) == 1


@pytest.mark.parametrize("role,active", [(UserRole.MANAGER, True), (UserRole.ADMIN, False)])
def test_seed_never_promotes_or_activates_existing_user(auth_setup, role, active):
    _, factory = auth_setup
    with factory() as session:
        user = session.scalar(select(User).where(User.email == "admin@example.com"))
        user.role, user.is_active = role, active
        session.commit()
        data = AdminSeedInput(
            email=user.email, password=TEST_PASSWORD, first_name="Іван", last_name="Петренко"
        )
        with pytest.raises(SeedConflict):
            seed_admin(session, data)
        session.refresh(user)
        assert user.role == role and user.is_active == active


def test_database_outage_is_friendly_and_does_not_log_secrets(auth_setup, caplog):
    app, _ = auth_setup

    def failing_db():
        raise OperationalError("query", {"password": TEST_PASSWORD}, Exception("private-details"))
        yield

    app.dependency_overrides[get_web_db] = failing_db
    with TestClient(app) as client:
        response = login(client)
        assert response.status_code == 503
        assert "тимчасово недоступна" in response.text
        assert TEST_PASSWORD not in response.text and "private-details" not in response.text
        assert TEST_PASSWORD not in caplog.text and "private-details" not in caplog.text


def test_seed_command_uses_environment_and_is_repeatable(auth_setup, monkeypatch, capsys):
    app, _ = auth_setup
    settings = Settings(
        _env_file=None,
        default_admin_email="cli@example.com",
        default_admin_password="Cli-only-test-password-123!",
        database_url=None,
    )
    monkeypatch.setattr(seed, "get_settings", lambda: settings)
    engine = app.state.database_factory.kw["bind"]
    monkeypatch.setattr(seed, "create_database_engine", lambda _: engine)
    monkeypatch.setattr("sys.argv", ["seed"])
    assert seed.main() == 0
    assert "Адміністратора створено." in capsys.readouterr().out
    assert seed.main() == 0
    assert "вже існує" in capsys.readouterr().out


def test_seed_command_does_not_echo_invalid_password(monkeypatch, capsys):
    settings = Settings(
        _env_file=None,
        default_admin_email="invalid-email",
        default_admin_password="secret",
        database_url=None,
    )
    monkeypatch.setattr(seed, "get_settings", lambda: settings)
    monkeypatch.setattr("sys.argv", ["seed"])
    assert seed.main() == 1
    assert "secret" not in capsys.readouterr().out


def test_concurrent_seed_creates_one_admin(migrated_engine):
    factory = create_session_factory(migrated_engine)
    data = AdminSeedInput(
        email="concurrent@example.com",
        password=TEST_PASSWORD,
        first_name="Початковий",
        last_name="Адміністратор",
    )

    def run():
        with factory() as session:
            return seed_admin(session, data)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: run(), range(2)))
    assert sorted(results) == [False, True]
    with factory() as session:
        assert len(session.scalars(select(User)).all()) == 1

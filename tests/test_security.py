import pytest
from pydantic import ValidationError

from app.core.errors import AuthenticationRequired, PermissionDenied
from app.core.policies import require_active, require_administrator
from app.core.security import csrf_matches, hash_password, safe_next, verify_password
from app.models import User, UserRole
from app.schemas.auth import AdminSeedInput, LoginInput


def test_argon2_hash_is_salted_and_verifies_password():
    password = "Пароль з пробілами 123!"
    encoded = hash_password(password)
    assert encoded.startswith("$argon2id$")
    assert encoded != hash_password(password)
    assert password not in encoded
    assert verify_password(password, encoded)
    assert not verify_password("incorrect-password", encoded)
    assert not verify_password(password, "invalid-hash")


@pytest.mark.parametrize(
    "value",
    [
        None,
        "",
        "https://evil.test",
        "//evil.test",
        "/\\evil.test",
        "/%2fevil.test",
        "/%252fevil.test",
        "/%5cevil.test",
        "/%0d%0aHost:evil",
        "/\n/evil.test",
        "javascript:alert(1)",
        "/" + "a" * 2048,
    ],
)
def test_external_or_ambiguous_next_is_rejected(value):
    assert safe_next(value) == "/dashboard"


@pytest.mark.parametrize("value", ["/users", "/dashboard?x=1&y=2", "/", "/dashboard#content"])
def test_local_next_is_preserved(value):
    assert safe_next(value) == value


@pytest.mark.parametrize("supplied", [None, "", "different", "токен", "a" * 257])
def test_csrf_comparison_handles_invalid_and_unicode_input(supplied):
    assert not csrf_matches("expected", supplied)
    assert csrf_matches("expected", "expected")


def test_credentials_normalize_email_without_trimming_password_or_exposing_it():
    credentials = LoginInput(email=" ADMIN@Example.com ", password=" password123 ")
    assert credentials.email == "admin@example.com"
    assert credentials.password.get_secret_value() == " password123 "
    assert "password123" not in repr(credentials)


@pytest.mark.parametrize(
    "field,value", [("email", "invalid"), ("password", "short"), ("password", "x" * 129)]
)
def test_invalid_credentials_are_rejected(field, value):
    data = {"email": "admin@example.com", "password": "valid-password"}
    data[field] = value
    with pytest.raises(ValidationError):
        LoginInput(**data)


def test_seed_validates_names():
    with pytest.raises(ValidationError):
        AdminSeedInput(
            email="admin@example.com", password="password123", first_name=" ", last_name="A"
        )


def test_active_user_and_admin_policies():
    user = User(role=UserRole.MANAGER, is_active=True)
    assert require_active(user) is user
    with pytest.raises(PermissionDenied):
        require_administrator(user)
    user.role = UserRole.ADMIN
    assert require_administrator(user) is user
    user.is_active = False
    with pytest.raises(AuthenticationRequired):
        require_administrator(user)
    with pytest.raises(AuthenticationRequired):
        require_active(None)

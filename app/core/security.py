import secrets
from functools import lru_cache
from urllib.parse import unquote, urlsplit

from pwdlib import PasswordHash
from pwdlib.exceptions import UnknownHashError

SESSION_MAX_AGE = 8 * 60 * 60
password_hasher = PasswordHash.recommended()


def hash_password(password: str) -> str:
    return password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return password_hasher.verify(password, password_hash)
    except (UnknownHashError, ValueError):
        return False


@lru_cache
def dummy_password_hash() -> str:
    # Missing and inactive users still perform the expensive password verification.
    return hash_password(secrets.token_urlsafe(32))


def new_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def csrf_matches(expected: object, supplied: object) -> bool:
    return (
        isinstance(expected, str)
        and isinstance(supplied, str)
        and 0 < len(supplied) <= 256
        and secrets.compare_digest(expected.encode("utf-8"), supplied.encode("utf-8"))
    )


def safe_next(value: str | None) -> str:
    if not value or len(value) > 2048:
        return "/dashboard"
    decoded = value
    # Inspect nested escapes too: browsers and proxies normalize URL paths differently.
    for _ in range(8):
        if (
            not decoded.startswith("/")
            or decoded.startswith("//")
            or "\\" in decoded
            or any(ord(char) < 32 or ord(char) == 127 for char in decoded)
        ):
            return "/dashboard"
        try:
            parts = urlsplit(decoded)
        except ValueError:
            return "/dashboard"
        if parts.scheme or parts.netloc:
            return "/dashboard"
        expanded = unquote(decoded)
        if expanded == decoded:
            return value
        decoded = expanded
    return "/dashboard"

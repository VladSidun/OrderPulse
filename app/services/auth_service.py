import logging
import time
from collections.abc import Mapping

from sqlalchemy.orm import Session

from app.core.errors import InvalidCredentials
from app.core.policies import require_active
from app.core.security import SESSION_MAX_AGE, dummy_password_hash, verify_password
from app.models import User
from app.repositories import user_repository
from app.schemas.auth import LoginInput

logger = logging.getLogger(__name__)


def authenticate(session: Session, credentials: LoginInput) -> User:
    try:
        user = user_repository.find_by_email(session, str(credentials.email), lock=True)
        encoded = user.password_hash if user and user.is_active else dummy_password_hash()
        valid = verify_password(credentials.password.get_secret_value(), encoded)
        if user is None or not user.is_active or not valid:
            logger.info("Login failed")
            raise InvalidCredentials("Невірний email або пароль.")
        session.commit()
        logger.info("Login succeeded: user_id=%s", user.id)
        return user
    except Exception:
        session.rollback()
        raise


def current_user(session: Session, payload: Mapping) -> User:
    user_id = payload.get("user_id")
    version = payload.get("auth_version")
    logged_in_at = payload.get("logged_in_at")
    valid = (
        type(user_id) is int
        and user_id > 0
        and type(version) is int
        and version > 0
        and type(logged_in_at) is int
        and 0 <= time.time() - logged_in_at < SESSION_MAX_AGE
    )
    user = user_repository.find_by_id(session, user_id) if valid else None
    if user is not None and user.auth_version != version:
        user = None
    return require_active(user)


def logout(session: Session, user: User) -> None:
    try:
        # Conditional UPDATE avoids a stale logout revoking sessions issued after another logout.
        user_repository.revoke_sessions(session, user.id, user.auth_version)
        session.commit()
    except Exception:
        session.rollback()
        raise

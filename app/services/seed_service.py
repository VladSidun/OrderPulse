from sqlalchemy.orm import Session

from app.core.errors import SeedConflict
from app.core.security import hash_password
from app.models import UserRole
from app.repositories import user_repository
from app.schemas.auth import AdminSeedInput


def seed_admin(session: Session, data: AdminSeedInput) -> bool:
    try:
        existing = user_repository.find_by_email(session, str(data.email))
        if existing is None:
            created = user_repository.insert_admin(
                session,
                {
                    "email": str(data.email),
                    "first_name": data.first_name,
                    "last_name": data.last_name,
                    "password_hash": hash_password(data.password.get_secret_value()),
                },
            )
            if created is not None:
                session.commit()
                return True
            existing = user_repository.find_by_email(session, str(data.email))
        if existing.role != UserRole.ADMIN or not existing.is_active:
            raise SeedConflict("Email вже належить іншому або неактивному користувачу.")
        session.commit()
        return False
    except Exception:
        session.rollback()
        raise

import argparse
from getpass import getpass

from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import get_settings
from app.core.errors import SeedConflict
from app.db.session import create_database_engine, create_session_factory
from app.schemas.auth import AdminSeedInput
from app.services.seed_service import seed_admin


def main() -> int:
    parser = argparse.ArgumentParser(description="Створення початкового адміністратора")
    parser.add_argument("--email")
    parser.add_argument("--first-name", default="Адміністратор")
    parser.add_argument("--last-name", default="Системи")
    arguments = parser.parse_args()
    settings = get_settings()
    email = arguments.email or settings.default_admin_email
    if not email:
        parser.error("Вкажіть --email або DEFAULT_ADMIN_EMAIL.")
    try:
        password = (
            settings.default_admin_password.get_secret_value()
            if settings.default_admin_password
            else getpass("Пароль адміністратора (8–128 символів): ")
        )
        data = AdminSeedInput(
            email=email,
            password=password,
            first_name=arguments.first_name,
            last_name=arguments.last_name,
        )
    except (ValidationError, EOFError):
        print("Перевірте email, імена (2–80 символів) та пароль (8–128 символів).")
        return 1
    engine = None
    try:
        engine = create_database_engine(settings)
        with create_session_factory(engine)() as session:
            created = seed_admin(session, data)
        print("Адміністратора створено." if created else "Адміністратор вже існує; дані збережено.")
        return 0
    except SeedConflict as error:
        print(str(error))
        return 1
    except (SQLAlchemyError, ValueError):
        print("БД недоступна або не підготовлена. Перевірте DATABASE_URL та alembic upgrade head.")
        return 1
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())

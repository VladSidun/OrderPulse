import argparse

from sqlalchemy.exc import SQLAlchemyError

from app.core.config import get_settings
from app.core.errors import SeedConflict
from app.db.session import create_database_engine, create_session_factory
from app.services.demo_service import seed_demo


def main() -> int:
    argparse.ArgumentParser(description="Завантаження development demo у порожню БД").parse_args()
    settings = get_settings()
    if settings.app_env == "production":
        print("Демонстраційні дані заборонено у production.")
        return 1
    engine = None
    try:
        engine = create_database_engine(settings)
        with create_session_factory(engine)() as session:
            created = seed_demo(session, settings)
        print(
            "Demo створено: 3 користувачі, 5 клієнтів, 16 замовлень."
            if created
            else "Demo вже існує; паролі та ручні зміни збережено."
        )
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

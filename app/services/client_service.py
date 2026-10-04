from sqlalchemy.orm import Session

from app.core.errors import NotFound
from app.core.policies import require_active
from app.models import Client, User
from app.repositories import client_repository
from app.schemas.api import ClientPatch
from app.schemas.client import ClientInput


def patch(session: Session, user: User, client_id: int, data: ClientPatch) -> int:
    try:
        require_active(user)
        client = client_repository.get(session, client_id, lock=True)
        if client is None:
            raise NotFound("Клієнта не знайдено.")
        values = {field: getattr(client, field) for field in ClientInput.model_fields}
        values.update(data.model_dump(exclude_unset=True))
        return save(session, user, ClientInput.model_validate(values), client_id)
    except Exception:
        session.rollback()
        raise


def get(session: Session, user: User, client_id: int) -> Client:
    require_active(user)
    client = client_repository.get(session, client_id)
    if client is None:
        raise NotFound("Клієнта не знайдено.")
    return client


def save(session: Session, user: User, data: ClientInput, client_id: int | None = None) -> int:
    try:
        require_active(user)
        client = get(session, user, client_id) if client_id is not None else Client()
        for field, value in data.model_dump().items():
            setattr(client, field, value)
        session.add(client)
        session.flush()
        result = client.id
        session.commit()
        return result
    except Exception:
        session.rollback()
        raise

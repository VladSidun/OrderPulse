from collections.abc import Iterator
from typing import Annotated
from urllib.parse import quote

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.errors import AuthenticationRequired
from app.core.policies import require_administrator
from app.core.security import csrf_matches, new_csrf_token
from app.models import User
from app.services import auth_service


def require_sessions(request: Request) -> None:
    if "session" not in request.scope:
        raise HTTPException(503, "Налаштуйте SECRET_KEY (мінімум 32 символи) для входу.")


def csrf_token(request: Request) -> str:
    require_sessions(request)
    if not isinstance(request.session.get("csrf_token"), str):
        request.session["csrf_token"] = new_csrf_token()
    return request.session["csrf_token"]


async def validate_csrf(request: Request) -> None:
    # API authenticates first, then performs the same check via its router dependency.
    if request.url.path.startswith("/api/"):
        return
    await check_csrf(request)


async def check_csrf(request: Request) -> None:
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return
    require_sessions(request)
    supplied = request.headers.get("X-CSRF-Token")
    if supplied is None:
        content_type = request.headers.get("content-type", "").split(";", 1)[0]
        if content_type in {"application/x-www-form-urlencoded", "multipart/form-data"}:
            form = await request.form(max_files=0)
            supplied = form.get("csrf_token")
    if not csrf_matches(request.session.get("csrf_token"), supplied):
        raise HTTPException(403, "Перевірка безпеки не пройшла. Оновіть сторінку та повторіть дію.")


def get_web_db(request: Request) -> Iterator[Session]:
    factory = request.app.state.database_factory
    if factory is None:
        raise HTTPException(503, "Налаштуйте DATABASE_URL та застосуйте міграції.")
    with factory() as session:
        try:
            yield session
        except Exception:
            session.rollback()
            raise


Database = Annotated[Session, Depends(get_web_db)]


def get_current_user(request: Request, session: Database) -> User:
    require_sessions(request)
    try:
        user = auth_service.current_user(session, request.session)
    except AuthenticationRequired:
        request.session.clear()
        raise
    # Error handlers run after dependency rollback/close: templates need a plain snapshot.
    request.state.current_user = {
        "id": user.id,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "role": user.role,
    }
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_admin(user: CurrentUser) -> User:
    return require_administrator(user)


Administrator = Annotated[User, Depends(require_admin)]


def login_location(request: Request) -> str:
    path = request.url.path
    if request.url.query:
        path += "?" + request.url.query
    return "/login?next=" + quote(path, safe="")

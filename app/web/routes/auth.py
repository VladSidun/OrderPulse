import time
from typing import Annotated

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import ValidationError

from app.core.dependencies import CurrentUser, Database, csrf_token
from app.core.errors import InvalidCredentials
from app.core.security import new_csrf_token, safe_next
from app.schemas.auth import LoginInput
from app.services import auth_service
from app.web.rendering import render

router = APIRouter(include_in_schema=False)


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request, next: str | None = None) -> HTMLResponse:
    csrf_token(request)
    return render(request, "login.html", email="", next=safe_next(next), errors={})


@router.post("/login", response_class=HTMLResponse, response_model=None)
def login(
    request: Request,
    session: Database,
    email: Annotated[str, Form()] = "",
    password: Annotated[str, Form()] = "",
    next: Annotated[str, Form()] = "/dashboard",
) -> HTMLResponse | RedirectResponse:
    destination = safe_next(next)
    try:
        credentials = LoginInput(email=email, password=password)
    except ValidationError as error:
        messages = {
            "email": "Вкажіть коректний email (до 255 символів).",
            "password": "Пароль має містити 8–128 символів.",
        }
        errors = {item["loc"][0]: messages[item["loc"][0]] for item in error.errors()}
        return render(
            request, "login.html", status_code=422, email=email, next=destination, errors=errors
        )
    try:
        user = auth_service.authenticate(session, credentials)
    except InvalidCredentials as error:
        return render(
            request,
            "login.html",
            status_code=401,
            email=email,
            next=destination,
            errors={"credentials": str(error)},
        )
    request.session.clear()
    request.session.update(
        user_id=user.id,
        auth_version=user.auth_version,
        logged_in_at=int(time.time()),
        csrf_token=new_csrf_token(),
    )
    return RedirectResponse(destination, status_code=303, headers={"Cache-Control": "no-store"})


@router.post("/logout")
def logout(request: Request, user: CurrentUser, session: Database) -> RedirectResponse:
    auth_service.logout(session, user)
    request.session.clear()
    return RedirectResponse("/login", status_code=303, headers={"Cache-Control": "no-store"})

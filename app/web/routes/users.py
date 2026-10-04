from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse
from pydantic import ValidationError

from app.core.dependencies import Administrator, Database, csrf_token
from app.core.errors import DomainError, NotFound, PermissionDenied
from app.schemas.user import PasswordReset, UserCreate, UserUpdate
from app.services import user_service
from app.web.forms import FormValues, validation_errors
from app.web.rendering import render

router = APIRouter(include_in_schema=False)


@router.get("/users")
def users(request: Request, session: Database, user: Administrator):
    csrf_token(request)
    return render(
        request, "users.html", active_page="users", users=user_service.list_users(session, user)
    )


@router.get("/users/new")
def new_user(request: Request, user: Administrator):
    csrf_token(request)
    return render(
        request,
        "user_form.html",
        active_page="users",
        values={"role": "MANAGER", "is_active": True},
        errors={},
    )


@router.post("/users/new")
def create_user(request: Request, session: Database, user: Administrator, values: FormValues):
    return save_form(request, session, user, values)


@router.get("/users/{user_id}/edit")
def edit_user(request: Request, user_id: int, session: Database, user: Administrator):
    csrf_token(request)
    target = user_service.get(session, user, user_id)
    values = {field: getattr(target, field) for field in UserUpdate.model_fields}
    values["role"] = target.role.value
    return render(
        request,
        "user_form.html",
        active_page="users",
        values=values,
        errors={},
        user_id=user_id,
        email=target.email,
    )


@router.post("/users/{user_id}/edit")
def update_user(
    request: Request, user_id: int, session: Database, user: Administrator, values: FormValues
):
    target = user_service.get(session, user, user_id)
    return save_form(request, session, user, values, user_id, target.email)


def save_form(request, session, user, values, user_id=None, email=None):
    values.setdefault("is_active", False)
    schema = UserCreate if user_id is None else UserUpdate
    try:
        data = schema.model_validate(values)
        if user_id is None:
            user_service.create(session, user, data)
        else:
            user_service.update(session, user, user_id, data)
    except ValidationError as error:
        errors, status = validation_errors(error), 422
    except (NotFound, PermissionDenied):
        raise
    except DomainError as error:
        errors, status = {"": str(error)}, error.status_code
    else:
        return RedirectResponse("/users", status_code=303)
    values.pop("password", None)
    values["is_active"] = values.get("is_active") in {True, "true", "on", "1"}
    return render(
        request,
        "user_form.html",
        status_code=status,
        active_page="users",
        values=values,
        errors=errors,
        user_id=user_id,
        email=email,
    )


@router.post("/users/{user_id}/password")
def reset_password(
    request: Request, user_id: int, session: Database, user: Administrator, values: FormValues
):
    target = user_service.get(session, user, user_id)
    try:
        data = PasswordReset.model_validate(values)
    except ValidationError as error:
        return render(
            request,
            "password_form.html",
            status_code=422,
            active_page="users",
            errors=validation_errors(error),
            user_id=user_id,
            email=target.email,
        )
    user_service.reset_password(session, user, user_id, data)
    return RedirectResponse("/users", status_code=303)

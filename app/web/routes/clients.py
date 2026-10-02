from fastapi import APIRouter, Query, Request
from fastapi.responses import RedirectResponse
from pydantic import ValidationError

from app.core.dependencies import CurrentUser, Database, csrf_token
from app.repositories import client_repository
from app.schemas.client import ClientInput
from app.services import client_service
from app.web.forms import FormValues, validation_errors
from app.web.rendering import render

router = APIRouter(include_in_schema=False)


@router.get("/clients")
def clients(
    request: Request,
    session: Database,
    user: CurrentUser,
    q: str = Query(default="", max_length=160),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=10, le=50),
):
    if page_size not in {10, 20, 50}:
        page_size = 20
    csrf_token(request)
    rows, total = client_repository.search(session, q.strip(), page, page_size)
    return render(
        request,
        "clients.html",
        active_page="clients",
        clients=rows,
        q=q,
        page=page,
        page_size=page_size,
        total=total,
    )


@router.get("/clients/new")
def new_client(request: Request, user: CurrentUser):
    csrf_token(request)
    return render(request, "client_form.html", active_page="clients", values={}, errors={})


@router.post("/clients/new")
def create_client(request: Request, session: Database, user: CurrentUser, values: FormValues):
    return save_form(request, session, user, values)


@router.get("/clients/{client_id}")
def client_detail(request: Request, client_id: int, session: Database, user: CurrentUser):
    csrf_token(request)
    client = client_service.get(session, user, client_id)
    orders = client_repository.visible_orders(
        session, client_id, user, request.app.state.settings.manager_order_visibility
    )
    return render(
        request, "client_detail.html", active_page="clients", client=client, orders=orders
    )


@router.get("/clients/{client_id}/edit")
def edit_client(request: Request, client_id: int, session: Database, user: CurrentUser):
    csrf_token(request)
    client = client_service.get(session, user, client_id)
    values = {field: getattr(client, field) or "" for field in ClientInput.model_fields}
    return render(
        request,
        "client_form.html",
        active_page="clients",
        values=values,
        errors={},
        client_id=client_id,
    )


@router.post("/clients/{client_id}/edit")
def update_client(
    request: Request, client_id: int, session: Database, user: CurrentUser, values: FormValues
):
    client_service.get(session, user, client_id)
    return save_form(request, session, user, values, client_id)


def save_form(request, session, user, values, client_id=None):
    try:
        data = ClientInput.model_validate(values)
    except ValidationError as error:
        return render(
            request,
            "client_form.html",
            status_code=422,
            active_page="clients",
            values=values,
            errors=validation_errors(error),
            client_id=client_id,
        )
    saved_id = client_service.save(session, user, data, client_id)
    return RedirectResponse(f"/clients/{saved_id}", status_code=303)

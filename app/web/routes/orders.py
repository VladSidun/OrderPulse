import re

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse
from pydantic import ValidationError

from app.core.business_time import local_input, parse_local_deadline
from app.core.dependencies import CurrentUser, Database, csrf_token
from app.core.errors import InputError, InvalidArchive, InvalidStatusTransition, VersionConflict
from app.core.policies import can_edit_order, require_administrator, require_order_edit
from app.models import OrderPriority, OrderStatus, UserRole
from app.repositories import order_repository
from app.schemas.order import OrderInput, OrderUpdate
from app.schemas.workflow import StatusChange, VersionInput
from app.services import order_service
from app.web.forms import FormValues, validation_errors
from app.web.rendering import render

router = APIRouter(include_in_schema=False)
ITEM_FIELD = re.compile(r"^items\.(\d{1,3})\.(name|quantity|unit_price)$")


def visibility(request):
    return request.app.state.settings.manager_order_visibility


def form_response(request, session, values, errors=None, *, order_id=None, status_code=200):
    clients, managers = order_repository.choices(session)
    return render(
        request,
        "order_form.html",
        status_code=status_code,
        active_page="orders",
        values=values,
        errors=errors or {},
        clients=clients,
        managers=managers,
        priorities=list(OrderPriority),
        order_id=order_id,
    )


def structured_values(flat):
    values = {}
    items = {}
    for key, value in flat.items():
        match = ITEM_FIELD.fullmatch(key)
        if match:
            index = int(match[1])
            items.setdefault(index, {})[match[2]] = value
        else:
            values[key] = value
    values["items"] = [items[index] for index in sorted(items)]
    return values


@router.get("/orders")
def orders(request: Request, session: Database, user: CurrentUser, archived: bool = False):
    csrf_token(request)
    if archived:
        require_administrator(user)
    rows = order_repository.list_recent(session, user, visibility(request), archived=archived)
    return render(request, "orders.html", active_page="orders", orders=rows, archived=archived)


@router.get("/orders/new")
def new_order(request: Request, session: Database, user: CurrentUser):
    csrf_token(request)
    return form_response(request, session, {"priority": "NORMAL", "items": [{}]})


@router.post("/orders/new")
def create_order(request: Request, session: Database, user: CurrentUser, flat: FormValues):
    return save_form(request, session, user, flat)


@router.get("/orders/{order_id}")
def order_detail(request: Request, order_id: int, session: Database, user: CurrentUser):
    csrf_token(request)
    return detail_response(request, session, user, order_id)


def detail_response(request, session, user, order_id, *, values=None, errors=None, status_code=200):
    order = order_service.get(session, user, order_id, visibility(request))
    return render(
        request,
        "order_detail.html",
        active_page="orders",
        order=order,
        can_edit=can_edit_order(user, order),
        transitions=order_service.ALLOWED_TRANSITIONS[order.status],
        can_archive=(
            user.role == UserRole.ADMIN
            and not order.is_archived
            and order.status in {OrderStatus.COMPLETED, OrderStatus.CANCELLED}
        ),
        values=values or {},
        errors=errors or {},
        status_code=status_code,
    )


@router.post("/orders/{order_id}/status")
def change_status(
    request: Request, order_id: int, session: Database, user: CurrentUser, values: FormValues
):
    return workflow_form(request, session, user, order_id, values, archive=False)


@router.post("/orders/{order_id}/archive")
def archive_order(
    request: Request, order_id: int, session: Database, user: CurrentUser, values: FormValues
):
    return workflow_form(request, session, user, order_id, values, archive=True)


def workflow_form(request, session, user, order_id, values, *, archive):
    try:
        if archive:
            order_service.archive(session, user, order_id, VersionInput.model_validate(values))
        else:
            order_service.change_status(
                session, user, order_id, StatusChange.model_validate(values), visibility(request)
            )
    except (ValidationError, InvalidArchive, InvalidStatusTransition, VersionConflict) as error:
        errors = (
            validation_errors(error)
            if isinstance(error, ValidationError)
            else {getattr(error, "field", "version"): str(error)}
        )
        return detail_response(
            request,
            session,
            user,
            order_id,
            values=values,
            errors=errors,
            status_code=422 if isinstance(error, ValidationError) else 409,
        )
    return RedirectResponse(f"/orders/{order_id}", status_code=303)


@router.get("/orders/{order_id}/edit")
def edit_order(request: Request, order_id: int, session: Database, user: CurrentUser):
    csrf_token(request)
    order = order_service.get(session, user, order_id, visibility(request))
    require_order_edit(user, order, visibility(request))
    values = {
        "client_id": order.client_id,
        "manager_id": order.manager_id,
        "priority": order.priority.value,
        "deadline_at": local_input(order.deadline_at),
        "comment": order.comment or "",
        "version": order.version,
        "items": [
            {"name": item.name, "quantity": str(item.quantity), "unit_price": str(item.unit_price)}
            for item in order.items
        ],
    }
    return form_response(request, session, values, order_id=order_id)


@router.post("/orders/{order_id}/edit")
def update_order(
    request: Request, order_id: int, session: Database, user: CurrentUser, flat: FormValues
):
    order = order_service.get(session, user, order_id, visibility(request))
    require_order_edit(user, order, visibility(request))
    return save_form(request, session, user, flat, order_id)


def save_form(request, session, user, flat, order_id=None):
    values = structured_values(flat)
    # Keep display data separate so invalid dates and stale versions remain visible.
    payload = dict(values)
    try:
        try:
            payload["deadline_at"] = parse_local_deadline(values.get("deadline_at"))
        except ValueError as error:
            raise InputError("deadline_at", str(error)) from error
        schema = OrderUpdate if order_id is not None else OrderInput
        data = schema.model_validate(payload)
        result = (
            order_service.create(session, user, data)
            if order_id is None
            else order_service.update(session, user, order_id, data, visibility(request))
        )
    except ValidationError as error:
        return form_response(
            request, session, values, validation_errors(error), order_id=order_id, status_code=422
        )
    except InputError as error:
        return form_response(
            request, session, values, {error.field: str(error)}, order_id=order_id, status_code=422
        )
    except VersionConflict as error:
        return form_response(
            request, session, values, {"version": str(error)}, order_id=order_id, status_code=409
        )
    return RedirectResponse(f"/orders/{result}", status_code=303)

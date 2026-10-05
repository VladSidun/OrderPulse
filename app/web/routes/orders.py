import re

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse
from pydantic import ValidationError

from app.core.business_time import local_input, parse_local_deadline, utc_now
from app.core.dependencies import CurrentUser, Database, csrf_token
from app.core.errors import InputError, InvalidArchive, InvalidStatusTransition, VersionConflict
from app.core.order_rules import is_overdue
from app.core.policies import can_edit_order, require_order_edit
from app.models import OrderPriority, OrderStatus, UserRole
from app.repositories import order_list_repository, order_repository
from app.schemas.order import OrderInput, OrderUpdate
from app.schemas.order_filters import OrderFilters
from app.schemas.workflow import StatusChange, VersionInput
from app.services import order_list_service, order_service
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
def orders(request: Request, session: Database, user: CurrentUser):
    csrf_token(request)
    now = utc_now()
    raw = dict(request.query_params)
    errors, rows, total, page, pages = {}, [], 0, 1, 1
    values = OrderFilters().model_dump(mode="json") | raw
    try:
        filters = OrderFilters.model_validate(raw)
        rows, total, page, pages = order_list_service.search(
            session, user, filters, visibility(request), now=now
        )
        values = filters.model_dump(mode="json")
    except ValidationError as error:
        errors = validation_errors(error)
        if any(item["loc"] == () for item in error.errors()):
            errors["period"] = "Перевірте порядок дат та допустимий календарний період."
    return render(
        request,
        "orders.html",
        active_page="orders",
        orders=rows,
        values=values,
        errors=errors,
        total=total,
        page=page,
        pages=pages,
        managers=order_list_repository.managers(session),
        statuses=list(OrderStatus),
        priorities=list(OrderPriority),
        now=now,
        is_overdue=is_overdue,
        editable_ids={order.id for order in rows if can_edit_order(user, order)},
        status_code=422 if errors else 200,
    )


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
        overdue=is_overdue(order, utc_now()),
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
    # Progressive enhancement: changing draft rows without JS does not save an order.
    draft_action = values.pop("_items_action", None)
    if draft_action is not None:
        errors = {}
        items = values["items"]
        if draft_action == "add" and len(items) < 100:
            items.append({})
        elif re.fullmatch(r"remove:\d{1,2}", draft_action):
            index = int(draft_action.split(":")[1])
            if len(items) > 1 and index < len(items):
                items.pop(index)
            else:
                errors["items"] = "Залиште щонайменше одну позицію."
        else:
            errors["items"] = "Список не може містити понад 100 позицій."
        return form_response(
            request,
            session,
            values,
            errors,
            order_id=order_id,
            status_code=422 if errors else 200,
        )
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

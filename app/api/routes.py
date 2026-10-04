from typing import Annotated

from fastapi import APIRouter, Depends, Header, Path, Query, Request, Response

from app.core.dependencies import CurrentUser, Database, check_csrf, csrf_token
from app.repositories import client_repository
from app.schemas.api import (
    ClientFilters,
    ClientPage,
    ClientPatch,
    ClientRead,
    CsrfRead,
    ErrorRead,
    OrderCreate,
    OrderPage,
    OrderPatch,
    OrderRead,
)
from app.schemas.client import ClientInput
from app.schemas.order_filters import OrderFilters
from app.schemas.workflow import StatusChange
from app.services import client_service, order_list_service, order_service


async def api_access(
    request: Request,
    response: Response,
    user: CurrentUser,
    csrf_header: Annotated[
        str | None,
        Header(
            alias="X-CSRF-Token",
            description="Обов’язковий для POST/PATCH: отримайте через GET /api/v1/csrf.",
        ),
    ] = None,
):
    response.headers["Cache-Control"] = "no-store"
    await check_csrf(request)


router = APIRouter(
    prefix="/api/v1",
    dependencies=[Depends(api_access)],
    responses={
        code: {"model": ErrorRead, "description": description}
        for code, description in {
            400: "Порушення бізнес-правила",
            401: "Потрібен вхід через /login",
            403: "Немає права або неправильний CSRF",
            404: "Ресурс не знайдено",
            409: "Конфлікт версії або статусу",
            503: "База даних недоступна",
        }.items()
    },
)
ResourceId = Annotated[int, Path(gt=0)]


def visibility(request: Request) -> str:
    return request.app.state.settings.manager_order_visibility


@router.get("/csrf", response_model=CsrfRead, tags=["Session"])
def get_csrf(request: Request, user: CurrentUser):
    return {"csrf_token": csrf_token(request)}


@router.get("/orders", response_model=OrderPage, tags=["Orders"])
def orders(
    request: Request,
    session: Database,
    user: CurrentUser,
    filters: Annotated[OrderFilters, Query()],
):
    rows, total, page, _ = order_list_service.search(session, user, filters, visibility(request))
    return dict(items=rows, total=total, page=page, page_size=filters.page_size)


@router.get("/orders/{order_id}", response_model=OrderRead, tags=["Orders"])
def order_detail(request: Request, order_id: ResourceId, session: Database, user: CurrentUser):
    return order_service.get(session, user, order_id, visibility(request))


@router.post("/orders", response_model=OrderRead, status_code=201, tags=["Orders"])
def create_order(
    request: Request, response: Response, data: OrderCreate, session: Database, user: CurrentUser
):
    result = order_service.create(session, user, data)
    response.headers["Location"] = f"/api/v1/orders/{result}"
    return order_service.get(session, user, result, visibility(request))


@router.patch("/orders/{order_id}", response_model=OrderRead, tags=["Orders"])
def update_order(
    request: Request, order_id: ResourceId, data: OrderPatch, session: Database, user: CurrentUser
):
    order_service.patch(session, user, order_id, data, visibility(request))
    return order_service.get(session, user, order_id, visibility(request))


@router.post("/orders/{order_id}/status", response_model=OrderRead, tags=["Orders"])
def change_status(
    request: Request, order_id: ResourceId, data: StatusChange, session: Database, user: CurrentUser
):
    order_service.change_status(session, user, order_id, data, visibility(request))
    return order_service.get(session, user, order_id, visibility(request))


@router.get("/clients", response_model=ClientPage, tags=["Clients"])
def clients(session: Database, user: CurrentUser, filters: Annotated[ClientFilters, Query()]):
    rows, total = client_repository.search(session, filters.q, filters.page, filters.page_size)
    return dict(items=rows, total=total, page=filters.page, page_size=filters.page_size)


@router.post("/clients", response_model=ClientRead, status_code=201, tags=["Clients"])
def create_client(data: ClientInput, session: Database, user: CurrentUser):
    result = client_service.save(session, user, data)
    return client_service.get(session, user, result)


@router.patch("/clients/{client_id}", response_model=ClientRead, tags=["Clients"])
def update_client(client_id: ResourceId, data: ClientPatch, session: Database, user: CurrentUser):
    client_service.patch(session, user, client_id, data)
    return client_service.get(session, user, client_id)

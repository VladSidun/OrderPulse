from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app.core.business_time import KYIV, utc_now
from app.core.dependencies import Administrator, CurrentUser, Database, csrf_token
from app.core.order_rules import is_overdue
from app.services import dashboard_service
from app.web.rendering import STATUS_LABELS, render

router = APIRouter(include_in_schema=False)


@router.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, session: Database, user: CurrentUser) -> HTMLResponse:
    csrf_token(request)
    now = utc_now()
    data = dashboard_service.snapshot(
        session, user, request.app.state.settings.manager_order_visibility, now=now
    )
    chart = {
        "labels": [STATUS_LABELS[status.value] for status in data["by_status"]],
        "values": list(data["by_status"].values()),
    }
    return render(
        request,
        "workspace.html",
        active_page="dashboard",
        data=data,
        chart=chart,
        now=now,
        is_overdue=is_overdue,
        month=now.astimezone(KYIV).strftime("%m.%Y"),
    )


@router.get("/users", response_class=HTMLResponse)
def users(request: Request, user: Administrator) -> HTMLResponse:
    csrf_token(request)
    return render(request, "users.html", active_page="users")

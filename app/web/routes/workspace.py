from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app.core.dependencies import Administrator, CurrentUser, csrf_token
from app.web.rendering import render

router = APIRouter(include_in_schema=False)


@router.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, user: CurrentUser) -> HTMLResponse:
    csrf_token(request)
    return render(request, "workspace.html", active_page="dashboard")


@router.get("/users", response_class=HTMLResponse)
def users(request: Request, user: Administrator) -> HTMLResponse:
    csrf_token(request)
    return render(request, "users.html", active_page="users")

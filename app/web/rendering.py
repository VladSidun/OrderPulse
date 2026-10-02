from pathlib import Path

from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

templates = Jinja2Templates(directory=Path(__file__).resolve().parent / "templates")


def render(request: Request, name: str, *, status_code: int = 200, **context) -> HTMLResponse:
    settings = request.app.state.settings
    return templates.TemplateResponse(
        request=request,
        name=name,
        status_code=status_code,
        headers={"Cache-Control": "no-store"},
        context={
            "app_name": settings.app_name,
            "currency": settings.currency,
            "timezone": settings.app_timezone,
            "current_user": getattr(request.state, "current_user", None),
            "csrf_token": request.scope.get("session", {}).get("csrf_token", ""),
            **context,
        },
    )

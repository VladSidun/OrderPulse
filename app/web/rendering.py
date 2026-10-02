from pathlib import Path

from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.core.business_time import display_time

templates = Jinja2Templates(directory=Path(__file__).resolve().parent / "templates")
templates.env.filters["business_time"] = display_time
templates.env.filters["money"] = lambda value: format(value, ".2f")
STATUS_LABELS = {
    "NEW": "Нове",
    "CONFIRMED": "Підтверджене",
    "IN_PROGRESS": "У роботі",
    "READY": "Готове",
    "COMPLETED": "Завершене",
    "CANCELLED": "Скасоване",
}
PRIORITY_LABELS = {"LOW": "Низький", "NORMAL": "Звичайний", "HIGH": "Високий"}
templates.env.filters["status_label"] = lambda value: STATUS_LABELS[value]
templates.env.filters["priority_label"] = lambda value: PRIORITY_LABELS[value]


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

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.web.rendering import render

router = APIRouter()


@router.get("/health", tags=["System"])
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/", response_class=HTMLResponse, response_model=None, include_in_schema=False)
def home(request: Request) -> HTMLResponse | RedirectResponse:
    if request.scope.get("session", {}).get("user_id"):
        return RedirectResponse("/dashboard", status_code=303)
    return render(request, "home.html")

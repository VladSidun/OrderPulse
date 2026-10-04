import logging
from typing import Literal

from fastapi import APIRouter, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.web.rendering import render

router = APIRouter()
logger = logging.getLogger(__name__)


class Readiness(BaseModel):
    status: Literal["ready", "unavailable"]


@router.get(
    "/ready", tags=["System"], response_model=Readiness, responses={503: {"model": Readiness}}
)
def ready(request: Request, response: Response):
    response.headers["Cache-Control"] = "no-store"
    factory = request.app.state.database_factory
    if factory is not None:
        try:
            with factory() as session:
                session.execute(text("SELECT 1"))
            return {"status": "ready"}
        except SQLAlchemyError as error:
            logger.error("Readiness failed: %s", type(error).__name__)
    response.status_code = 503
    return {"status": "unavailable"}


@router.get("/health", tags=["System"])
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/", response_class=HTMLResponse, response_model=None, include_in_schema=False)
def home(request: Request) -> HTMLResponse | RedirectResponse:
    if request.scope.get("session", {}).get("user_id"):
        return RedirectResponse("/dashboard", status_code=303)
    return render(request, "home.html")

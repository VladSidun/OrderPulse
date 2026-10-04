import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Request, Security
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.security import APIKeyCookie
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException
from starlette.middleware.sessions import SessionMiddleware

from app.api.routes import router as api_router
from app.core.config import Settings, get_settings
from app.core.dependencies import login_location, validate_csrf
from app.core.errors import AuthenticationRequired, DomainError, InputError
from app.core.security import SESSION_MAX_AGE
from app.db.session import create_database_engine, create_session_factory
from app.web.rendering import render
from app.web.routes.auth import router as auth_router
from app.web.routes.clients import router as clients_router
from app.web.routes.orders import router as orders_router
from app.web.routes.reports import router as reports_router
from app.web.routes.system import router
from app.web.routes.users import router as users_router
from app.web.routes.workspace import router as workspace_router

logger = logging.getLogger(__name__)
APP_DIRECTORY = Path(__file__).resolve().parent


def error_response(request, status_code, message):
    if request.url.path.startswith("/api/") or request.url.path == "/ready":
        return JSONResponse(
            {"detail": message}, status_code=status_code, headers={"Cache-Control": "no-store"}
        )
    return render(request, "error.html", status_code=status_code, message=message)


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    logger.info("Application started in %s mode", application.state.settings.app_env)
    yield
    if application.state.database_engine is not None:
        application.state.database_engine.dispose()
    logger.info("Application stopped")


def create_app(settings: Settings | None = None) -> FastAPI:
    configuration = settings if settings is not None else get_settings()
    application = FastAPI(
        title=configuration.app_name,
        version="0.1.0",
        debug=configuration.debug,
        docs_url="/docs" if configuration.app_env != "production" else None,
        redoc_url=None,
        openapi_url="/openapi.json" if configuration.app_env != "production" else None,
        lifespan=lifespan,
        dependencies=[Depends(validate_csrf)],
    )
    application.state.settings = configuration
    engine = create_database_engine(configuration) if configuration.database_url else None
    application.state.database_engine = engine
    application.state.database_factory = create_session_factory(engine) if engine else None
    if configuration.secret_key and len(configuration.secret_key.get_secret_value()) >= 32:
        application.add_middleware(
            SessionMiddleware,
            secret_key=configuration.secret_key.get_secret_value(),
            session_cookie=configuration.session_cookie_name,
            max_age=SESSION_MAX_AGE,
            same_site="lax",
            https_only=configuration.app_env == "production",
        )

    @application.exception_handler(AuthenticationRequired)
    async def authentication_error(request: Request, error: AuthenticationRequired):
        if request.url.path.startswith("/api/"):
            return error_response(request, 401, "Увійдіть у систему через /login.")
        return RedirectResponse(
            login_location(request), status_code=303, headers={"Cache-Control": "no-store"}
        )

    @application.exception_handler(DomainError)
    async def domain_error(request: Request, error: DomainError):
        status = (
            400
            if request.url.path.startswith("/api/") and isinstance(error, InputError)
            else error.status_code
        )
        return error_response(request, status, str(error))

    @application.exception_handler(HTTPException)
    async def http_error(request: Request, error: HTTPException):
        message = error.detail if error.status_code != 404 else "Сторінку не знайдено."
        return error_response(request, error.status_code, message)

    @application.exception_handler(SQLAlchemyError)
    async def database_error(request: Request, error: SQLAlchemyError):
        # Exception text can contain credentials or PII; only log the exception type.
        logger.error("Database operation failed: %s", type(error).__name__)
        return error_response(
            request, 503, "База даних тимчасово недоступна. Повторіть спробу пізніше."
        )

    @application.exception_handler(Exception)
    async def unexpected_error(request: Request, error: Exception):
        logger.error("Unexpected operation failure: %s", type(error).__name__)
        return error_response(
            request, 500, "Сталася неочікувана помилка. Повторіть спробу пізніше."
        )

    application.mount("/static", StaticFiles(directory=APP_DIRECTORY / "static"), name="static")
    application.include_router(router)
    application.include_router(auth_router)
    application.include_router(workspace_router)
    application.include_router(clients_router)
    application.include_router(orders_router)
    application.include_router(users_router)
    application.include_router(reports_router)
    application.include_router(
        api_router,
        dependencies=[
            Security(
                APIKeyCookie(
                    name=configuration.session_cookie_name,
                    auto_error=False,
                    scheme_name="SessionCookie",
                )
            )
        ],
    )
    return application


app = create_app()

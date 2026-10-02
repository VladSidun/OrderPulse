import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.core.config import Settings, get_settings
from app.web.routes.system import router

logger = logging.getLogger(__name__)
APP_DIRECTORY = Path(__file__).resolve().parent


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    logger.info("Application started in %s mode", application.state.settings.app_env)
    yield
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
    )
    application.state.settings = configuration
    application.mount("/static", StaticFiles(directory=APP_DIRECTORY / "static"), name="static")
    application.include_router(router)
    return application


app = create_app()

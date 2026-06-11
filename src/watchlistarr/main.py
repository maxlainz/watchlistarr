import asyncio
import re
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import structlog
from alembic import command
from alembic.config import Config as AlembicConfig
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from starlette.exceptions import HTTPException as StarletteHTTPException

from watchlistarr import __version__
from watchlistarr.config import get_settings
from watchlistarr.db import (
    dispose_engine,
    get_session_factory,
    init_engine,
    session_scope,
)
from watchlistarr.logging import setup_logging
from watchlistarr.routes.api.admin import router as admin_router
from watchlistarr.routes.api.radarr import router as radarr_router
from watchlistarr.routes.api.v1 import router as api_v1_router
from watchlistarr.scheduler import JobScheduler
from watchlistarr.services.log_buffer import install_buffer_handler
from watchlistarr.services.scrape.audit import fail_interrupted_runs

logger = structlog.get_logger(__name__)

_ALEMBIC_INI = Path(__file__).resolve().parent.parent.parent / "alembic.ini"
_STATIC_DIR = Path(__file__).resolve().parent / "static"
_INDEX_HTML = _STATIC_DIR / "index.html"


def _alembic_upgrade_sync() -> None:
    cfg = AlembicConfig(str(_ALEMBIC_INI))
    command.upgrade(cfg, "head")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    setup_logging(level=settings.log_level, fmt=settings.log_format)
    install_buffer_handler()
    logger.info("watchlistarr.startup", version=__version__)

    await asyncio.to_thread(_alembic_upgrade_sync)
    # alembic.fileConfig reasignó los handlers del root logger; restablecemos
    # nuestra config para que los logs INFO posteriores sigan saliendo a stdout.
    setup_logging(level=settings.log_level, fmt=settings.log_format)
    install_buffer_handler()
    init_engine(settings.database_url)
    await fail_interrupted_runs(get_session_factory())

    scheduler = JobScheduler(get_session_factory(), settings)
    await scheduler.sync_jobs()
    scheduler.start()
    app.state.scheduler = scheduler

    logger.info("watchlistarr.ready", database_url=settings.database_url)
    try:
        yield
    finally:
        await scheduler.shutdown()
        await dispose_engine()
        logger.info("watchlistarr.shutdown")


def create_app() -> FastAPI:
    app = FastAPI(title="watchlistarr", version=__version__, lifespan=lifespan)

    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    @app.get("/healthz")
    async def healthz() -> JSONResponse:
        try:
            async with session_scope() as session:
                await session.execute(text("SELECT 1"))
        except Exception as exc:
            logger.warning("healthz.db_unreachable", error=str(exc))
            return JSONResponse({"status": "error", "db": "unreachable"}, status_code=503)
        return JSONResponse({"status": "ok", "version": __version__})

    @app.exception_handler(Exception)
    async def _log_unhandled(request: Request, exc: Exception) -> Response:
        if isinstance(exc, StarletteHTTPException):
            raise exc
        logger.exception(
            "request.unhandled_exception",
            path=request.url.path,
            method=request.method,
            error=str(exc),
        )
        return JSONResponse({"detail": "Internal Server Error"}, status_code=500)

    app.include_router(admin_router)
    app.include_router(api_v1_router)
    app.include_router(radarr_router)

    # Cache-buster: append ?v=<startup-id> a cada referencia estática del shell
    # para forzar al navegador a re-descargar styles.css y los .jsx tras cada
    # restart del contenedor. Sin esto, Babel-standalone y el navegador cachean
    # los .jsx y los cambios de UI no se ven hasta hard-refresh.
    _build_id = f"{__version__}-{int(time.time())}"
    _shell_html = _INDEX_HTML.read_text(encoding="utf-8")
    _shell_html = re.sub(
        r'(src|href)="(/static/[^"?]+)"',
        rf'\1="\2?v={_build_id}"',
        _shell_html,
    )

    @app.get("/", include_in_schema=False)
    async def spa_index() -> HTMLResponse:
        return HTMLResponse(
            _shell_html,
            headers={"Cache-Control": "no-cache, must-revalidate"},
        )

    return app


app = create_app()

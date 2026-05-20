from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import structlog
from alembic import command
from alembic.config import Config as AlembicConfig
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import text

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
from watchlistarr.routes.ui.activity import router as ui_activity_router
from watchlistarr.routes.ui.combined import router as ui_combined_router
from watchlistarr.routes.ui.dashboard import router as ui_dashboard_router
from watchlistarr.routes.ui.endpoints import router as ui_endpoints_router
from watchlistarr.routes.ui.settings import router as ui_settings_router
from watchlistarr.routes.ui.sublists import router as ui_sublists_router
from watchlistarr.routes.ui.users import router as ui_users_router
from watchlistarr.scheduler import JobScheduler
from watchlistarr.services.settings import seed_defaults

logger = structlog.get_logger(__name__)

_ALEMBIC_INI = Path(__file__).resolve().parent.parent.parent / "alembic.ini"


def _alembic_upgrade_sync() -> None:
    cfg = AlembicConfig(str(_ALEMBIC_INI))
    command.upgrade(cfg, "head")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    setup_logging(level=settings.log_level, fmt=settings.log_format)
    logger.info("watchlistarr.startup", version=__version__)

    await asyncio.to_thread(_alembic_upgrade_sync)
    init_engine(settings.database_url)
    async with session_scope() as session:
        await seed_defaults(session, settings)
        await session.commit()

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

    @app.get("/healthz")
    async def healthz() -> JSONResponse:
        try:
            async with session_scope() as session:
                await session.execute(text("SELECT 1"))
        except Exception as exc:
            logger.warning("healthz.db_unreachable", error=str(exc))
            return JSONResponse({"status": "error", "db": "unreachable"}, status_code=503)
        return JSONResponse({"status": "ok", "version": __version__})

    app.include_router(admin_router)
    app.include_router(ui_dashboard_router)
    app.include_router(ui_users_router)
    app.include_router(ui_sublists_router)
    app.include_router(ui_combined_router)
    app.include_router(ui_settings_router)
    app.include_router(ui_activity_router)
    app.include_router(ui_endpoints_router)
    app.include_router(radarr_router)
    return app


app = create_app()

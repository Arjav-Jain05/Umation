"""FastAPI main application entry point."""

from __future__ import annotations

# Compatibility fix for newer PyAV (v14+) where metadata_errors was removed from av.open
try:
    import av
    _orig_av_open = av.open
    def _compat_av_open(*args, **kwargs):
        kwargs.pop("metadata_errors", None)
        return _orig_av_open(*args, **kwargs)
    av.open = _compat_av_open
except Exception:
    pass

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.api.clips import router as clips_router
from app.api.export import router as export_router
from app.api.jobs import router as jobs_router
from app.api.results import router as results_router
from app.api.system import router as system_router
from app.core.db import init_db
from app.core.errors import (
    AppError,
    Canceled,
    DiskSpace,
    GeminiQuotaExceeded,
    GeminiUnavailable,
    InvalidUrl,
    LiveNotFinished,
    SourceBlocked,
    SourceUnavailable,
    TooLong,
    to_api,
)
from app.core.worker import worker
from app.utils.logging_setup import get_logger, setup_logging
from config.settings import get_settings

logger = get_logger("app.main")


def _status_code_for_error(err: AppError) -> int:
    if isinstance(err, (InvalidUrl, SourceBlocked, LiveNotFinished, TooLong)):
        return 422
    if isinstance(err, SourceUnavailable):
        return 404
    if isinstance(err, DiskSpace):
        return 507
    if isinstance(err, GeminiQuotaExceeded):
        return 429
    if isinstance(err, GeminiUnavailable):
        return 503
    if isinstance(err, Canceled):
        return 409
    return 400


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Startup and shutdown lifespan handler."""
    settings = get_settings()
    setup_logging(settings)
    logger.info("Initializing database at %s", settings.data_dir / "app.db")
    init_db(settings.data_dir / "app.db")
    logger.info("Starting background pipeline worker thread")
    worker.start()
    logger.info("Shorts Engine startup complete. Listening on %s:%d", settings.host, settings.port)
    yield
    logger.info("Stopping worker and shutting down Shorts Engine")
    worker.stop()


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    settings = get_settings()
    app = FastAPI(
        title="Shorts Engine",
        version="1.0.0",
        description="Local YouTube to vertical shorts engine",
        lifespan=lifespan,
    )

    # Global custom exception handler for AppError
    @app.exception_handler(AppError)
    async def app_error_handler(_request: Request, exc: AppError) -> JSONResponse:
        status_code = _status_code_for_error(exc)
        return JSONResponse(
            status_code=status_code,
            content={"error": to_api(exc)},
        )

    # Include API routers
    app.include_router(system_router)
    app.include_router(jobs_router)
    app.include_router(clips_router)
    app.include_router(export_router)
    app.include_router(results_router)

    # Static mounts
    web_dir = settings.project_root / "web"
    output_dir = settings.output_dir
    web_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    app.mount("/web", StaticFiles(directory=str(web_dir), html=True), name="web")
    app.mount("/files/output", StaticFiles(directory=str(output_dir)), name="output_files")

    # Redirect root to web UI
    @app.get("/", include_in_schema=False)
    async def root_redirect() -> RedirectResponse:
        return RedirectResponse(url="/web/index.html")

    return app


app = create_app()

"""FastAPI application factory.

Run from ``backend/``:  ``uvicorn main:app --port 5000``  (or ``python main.py``).
"""
import asyncio
import os
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app import db, lag_monitor
from app.api import router as api_router
from app.config import settings
from app.errors import register_error_handlers
from app.services import links, retitle, guests
from app.services.progress_data import use_timezone


async def _name_old_videos() -> None:
    """Notes imported from YouTube before titles were fetched are renamed to the real title (best effort, never blocks startup)."""
    try:
        fixed = await asyncio.to_thread(links.fix_video_names)
        if fixed:
            logging.getLogger(__name__).info("Gave %d imported videos their real titles", fixed)
    except Exception:  # noqa: BLE001 - a cosmetic job: any failure just leaves the old name
        logging.getLogger(__name__).warning("Could not rename old video notes", exc_info=True)


async def _retitle_old_notes() -> None:
    """Notes stored before human titles existed get a real title and a source type; the same link added twice becomes one."""
    try:
        await asyncio.to_thread(retitle.retitle_existing)
    except Exception:  # noqa: BLE001 - cosmetic: a failure just leaves the old names
        logging.getLogger(__name__).warning("Could not re-title old notes", exc_info=True)


async def _clear_old_guests() -> None:
    try:
        await asyncio.to_thread(guests.purge_old)
    except Exception:  # noqa: BLE001 - housekeeping: they are cleared on the next start
        logging.getLogger(__name__).warning("Could not clear old guests", exc_info=True)


async def _seed_demo_class() -> None:
    """The teacher dashboard must look alive on first load: build the demo class if it does not exist yet."""
    try:
        from app.ps02 import logins, seed
        await asyncio.to_thread(seed.ensure_seeded)
        await asyncio.to_thread(logins.ensure_demo_accounts)
    except Exception:  # noqa: BLE001 - the app still works; POST /api/demo/seed rebuilds it
        logging.getLogger(__name__).warning("Could not seed the PS02 demo class", exc_info=True)


@asynccontextmanager
async def lifespan(_: FastAPI):
    class_seeder = asyncio.create_task(_seed_demo_class())
    watcher = asyncio.create_task(lag_monitor.watch())
    renamer = asyncio.create_task(_name_old_videos())
    retitler = asyncio.create_task(_retitle_old_notes())
    sweeper = asyncio.create_task(_clear_old_guests())
    try:
        yield
    finally:
        watcher.cancel()
        renamer.cancel()
        retitler.cancel()
        sweeper.cancel()
        class_seeder.cancel()


def create_app() -> FastAPI:
    logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    db.init_db()

    docs = settings.enable_docs   # the interactive API docs only when asked for (ENABLE_DOCS=true), never by default in production
    app = FastAPI(title="Eklavya API", lifespan=lifespan, docs_url="/docs" if docs else None, redoc_url="/redoc" if docs else None,
                  openapi_url="/openapi.json" if docs else None)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_methods=["*"],
        allow_headers=["*"],
    )
    register_error_handlers(app)

    @app.middleware("http")
    async def student_timezone(request: Request, call_next):
        use_timezone(request.headers.get("x-timezone"))   # "today" means the student's today, not the server's
        return await call_next(request)

    @app.middleware("http")
    async def ps02_logins(request: Request, call_next):
        """Who is calling (student / teacher), and teacher-only pages. Does nothing unless PS02_AUTH_REQUIRED is on."""
        from fastapi.responses import JSONResponse
        from app.errors import AppError
        from app.ps02 import logins
        token = None
        header = request.headers.get("authorization", "")
        if header.lower().startswith("bearer "):
            token = header[7:].strip() or None
        try:
            logins.CALLER.set(logins.caller_from_token(token) if logins.required() and token else None)
            path = request.url.path
            if logins.required() and request.method != "OPTIONS" and (path.startswith(("/api/teacher/", "/api/students")) or path == "/api/demo/seed-class"):
                logins.check_teacher()
        except AppError as exc:
            return JSONResponse({"error": exc.message if hasattr(exc, "message") else str(exc), "code": exc.code}, status_code=exc.status_code)
        return await call_next(request)
    app.include_router(api_router)

    @app.get("/api/health")
    def health():
        """Answers instantly without touching the database: the page and the keep-alive job use it to see that the server is awake."""
        commit = os.environ.get("RENDER_GIT_COMMIT", "")   # set by Render: lets anyone see which version is live
        return {"ok": True, **({"version": commit[:7]} if commit else {})}

    @app.get("/")
    def root():
        return {"status": "ok", "service": "Eklavya API"}

    return app


app = create_app()

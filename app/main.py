"""FastAPI application entrypoint.

Run locally (mock camera):  CAMERA_BACKEND=mock uvicorn app.main:app --reload
Run on the Pi:              uvicorn app.main:app --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import db
from .config import ensure_dirs
from .illumination import get_illumination
from .routers import capture, experiments, gallery, illumination, images, presets
from .scheduler import make_scheduler, reconcile_on_startup

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


def static_url(path: str) -> str:
    """URL for a static file, versioned by its mtime so a deploy that changes it busts
    the browser cache. Without this Chrome can pair freshly fetched HTML with a stale
    cached script, leaving new buttons with no handlers."""
    try:
        version = int((STATIC_DIR / path).stat().st_mtime)
    except OSError:
        return f"/static/{path}"
    return f"/static/{path}?v={version}"


templates.env.globals["static_url"] = static_url


@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_dirs()
    db.init_db()
    # Start the timecourse scheduler and re-arm any run that was active before a
    # restart (SQLite is the source of truth for runs; see app/scheduler.py).
    scheduler = make_scheduler()
    scheduler.start()
    app.state.scheduler = scheduler
    reconcile_on_startup(scheduler)
    try:
        yield
    finally:
        scheduler.shutdown(wait=False)
        # Tear down BLE panel connections cleanly (no-op for the mock backend).
        get_illumination().close()


app = FastAPI(title="rlab-camera", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# Share templates with routers without a circular import.
app.state.templates = templates

app.include_router(capture.router)
app.include_router(illumination.router)
app.include_router(images.router)
app.include_router(presets.router)
app.include_router(experiments.router)
app.include_router(gallery.router)
app.include_router(gallery.page_router)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}

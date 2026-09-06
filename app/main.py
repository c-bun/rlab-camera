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
from .routers import capture, experiments, gallery, images, presets
from .scheduler import make_scheduler, reconcile_on_startup

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


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


app = FastAPI(title="rlab-camera", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

# Share templates with routers without a circular import.
app.state.templates = templates

app.include_router(capture.router)
app.include_router(images.router)
app.include_router(presets.router)
app.include_router(experiments.router)
app.include_router(experiments.page_router)
app.include_router(gallery.router)
app.include_router(gallery.page_router)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}

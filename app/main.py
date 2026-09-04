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
from .routers import capture, images

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_dirs()
    db.init_db()
    yield


app = FastAPI(title="rlab-camera", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

# Share templates with routers without a circular import.
app.state.templates = templates

app.include_router(capture.router)
app.include_router(images.router)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}

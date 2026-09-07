"""Test fixtures: force the mock camera and an isolated data dir per test session."""

from __future__ import annotations

import importlib

import pytest


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("CAMERA_BACKEND", "mock")
    monkeypatch.setenv("RLAB_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RLAB_DB_PATH", str(tmp_path / "test.db"))

    # Reload modules that read config/env at import time so overrides take effect.
    from app import config

    importlib.reload(config)
    from app import db as db_module

    importlib.reload(db_module)
    from app.camera import factory

    importlib.reload(factory)
    factory.get_camera.cache_clear()

    # Illumination defaults to the mock backend (no RLAB_PANELS set), like the camera.
    # Reload the package too so its re-exported get_illumination (used by the app via
    # `from .illumination import get_illumination`) rebinds to the fresh, cache-cleared
    # factory function — otherwise the app and the tests hold different singletons.
    from app.illumination import factory as illum_factory

    importlib.reload(illum_factory)
    import app.illumination as illum_pkg

    importlib.reload(illum_pkg)
    illum_pkg.get_illumination.cache_clear()

    # Modules that read config/db at import time, in dependency order.
    from app import capture_service

    importlib.reload(capture_service)
    from app import scheduler as scheduler_module

    importlib.reload(scheduler_module)
    from app.routers import experiments as experiments_module

    importlib.reload(experiments_module)
    # Routers that hold get_illumination/perform_capture bindings must reload after those
    # modules so they don't keep a stale singleton from a previous test's reload.
    from app.routers import capture as capture_router

    importlib.reload(capture_router)
    from app.routers import illumination as illumination_router

    importlib.reload(illumination_router)

    from app import main

    importlib.reload(main)

    from fastapi.testclient import TestClient

    with TestClient(main.app) as c:
        yield c

    factory.get_camera.cache_clear()
    illum_pkg.get_illumination.cache_clear()

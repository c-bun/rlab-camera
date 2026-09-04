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

    from app import main

    importlib.reload(main)

    from fastapi.testclient import TestClient

    with TestClient(main.app) as c:
        yield c

    factory.get_camera.cache_clear()

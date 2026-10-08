import pytest_asyncio

from app.repositories import UiHealthLogStore
from app.db import engine
from app.services import services


@pytest_asyncio.fixture(autouse=True)
async def clear_memory_state(tmp_path, monkeypatch):
    monkeypatch.setattr(services, "ui_health_logs", UiHealthLogStore(tmp_path / "ui-health-logs"))
    await engine.dispose()
    await services.jobs.clear()
    await services.runners.clear()
    await services.ui_health.clear()
    yield
    await services.jobs.clear()
    await services.runners.clear()
    await services.ui_health.clear()
    await engine.dispose()

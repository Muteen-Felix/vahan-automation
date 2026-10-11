import pytest_asyncio
from sqlalchemy import delete, insert
from uuid import uuid4

from app.db import engine, schema as db
from app.repositories.postgres import now, require_test_database
from app.repositories import ui_contract
from app.security import issue_access_token
from app.services import services


@pytest_asyncio.fixture(autouse=True)
async def reset_test_database():
    require_test_database()
    await engine.dispose()
    await services.jobs.clear()
    await services.runners.clear()
    async with engine.begin() as connection:
        await connection.execute(delete(db.ui_preflight_checks))
        await connection.execute(delete(db.ui_health_checks))
        await connection.execute(delete(db.app_settings))
        await connection.execute(delete(db.main_reports))
        await connection.execute(delete(db.report_update_history))
    yield
    await services.jobs.clear()
    await services.runners.clear()
    await engine.dispose()


@pytest_asyncio.fixture
async def admin_token():
    await services.users.bootstrap("test-admin", "test-only-admin-password")
    session = await services.users.create_session("test-admin")
    return issue_access_token("test-admin", session)


@pytest_asyncio.fixture
async def admin_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


@pytest_asyncio.fixture
async def approve_workers():
    async def approve(runner_ids):
        observed = [{**seed, "found": True, "count": 1, "name": seed["field"],
                     "label": seed["field"], "matchedBy": "selector", "inputType": "text"}
                    for seed in ui_contract.SEEDS]
        for runner_id in runner_ids:
            result = await ui_contract.evaluate({"status": "PASS", "observedControls": observed}, runner_id)
        gate_id = str(uuid4())
        async with engine.begin() as connection:
            await connection.execute(insert(db.ui_preflight_checks).values(
                id=gate_id, owner_username="test-admin", runner_ids=runner_ids,
                version_id=result["versionId"], status="PASS", reports=[result], created_at=now()))
        return gate_id
    return approve

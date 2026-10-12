"""Current and legacy dashboard requests cannot configure schedule capacity."""
from datetime import timedelta
from uuid import uuid4

from httpx import ASGITransport, AsyncClient
import pytest

from app.main import application
from app.models.filter_profile import ProfileWrite
from app.repositories.filter_profiles import FilterProfileRepository
from app.repositories.run_schedules import RunScheduleRepository, now
from app.run_scheduler import scheduler_tick
from app.worker_pool import pool_status


@pytest.mark.parametrize('legacy', [False, True])
async def test_schedule_create_and_resume_ignore_removed_worker_control(admin_headers, legacy):
    profile = await FilterProfileRepository().save('test-admin', ProfileWrite.model_validate({
        'name': 'API capacity fixture', 'definition': {'report': {'year': 2024}, 'fields': {
            'delhiNcr': {'values': ['ALL STATES']}, 'states': {'values': ['State']},
            'rtos': {'values': ['Office']}, 'archivedFlags': {'values': ['ACTIVE']}}}}))
    payload = {'profileId': profile['id'], 'year': 2024, 'startsAt': (now() + timedelta(hours=1)).isoformat()}
    if legacy:
        payload['workerCount'] = 9999
    repo = RunScheduleRepository()
    async with AsyncClient(transport=ASGITransport(app=application), base_url='http://test', headers=admin_headers) as client:
        response = await client.post('/api/run-schedules', json=payload)
        assert response.status_code == 201, response.text
        saved = response.json()
        assert 'workerCount' not in saved
        assert 'workerCount' not in await repo.get(saved['id'])
        # Emulate a paused schedule written by an old version before any queue
        # existed. Resuming with no browsers must wait and never apply 9999.
        await repo.patch(saved['id'], {'workerCount': 9999, 'status': 'PAUSED', 'sessionId': str(uuid4())})
        response = await client.post(f"/api/run-schedules/{saved['id']}/resume", json={'workerCount': 9999} if legacy else {})
        assert response.status_code == 200, response.text
        assert response.json()['status'] == 'RESUMING'
        assert 'workerCount' not in response.json()
        assert 'workerCount' not in await repo.get(saved['id'])
    before = (await pool_status())['desiredCount']
    await scheduler_tick()
    current = await repo.get(saved['id'])
    assert current['status'] == 'RESUMING'
    assert 'Waiting for a connected' in current['message']
    assert (await pool_status())['desiredCount'] == before

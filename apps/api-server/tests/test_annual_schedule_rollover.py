from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from app.models.filter_profile import ProfileDefinition, ProfileWrite
from app.models.run_schedule import RunScheduleCreate
from app.repositories.filter_profiles import FilterProfileRepository
from app.repositories.run_schedules import RunScheduleRepository
import app.repositories.run_schedules as schedule_module


def filter_definition(year):
    return {'report': {'year': year, 'period': 'CALENDAR YEAR', 'yAxis': 'Maker', 'xAxis': 'Month Wise'},
        'fields': {'delhiNcr': {'values': ['ALL STATES']}, 'states': {'mode': 'iterate'},
            'rtos': {'mode': 'iterate'}, 'archivedFlags': {'values': ['ACTIVE_COMPLIANT']}}}


@pytest.mark.asyncio
async def test_monthly_schedule_creates_independent_next_year_filter_and_schedule(admin_headers, monkeypatch):
    owner = 'test-admin'
    year = datetime.now().year
    profiles = FilterProfileRepository()
    source = await profiles.save(owner, ProfileWrite.model_validate({
        'name': 'Monthly vehicle reports', 'definition': filter_definition(year)}))
    starts_at = datetime.now(timezone.utc) + timedelta(hours=1)
    command = RunScheduleCreate.model_validate({'profileId': source['id'], 'year': year,
        'startsAt': starts_at.isoformat(), 'timeZone': 'Asia/Kolkata', 'repeat': 'monthly'})
    schedules = RunScheduleRepository()
    created = await schedules.create(owner, command)
    session_id = 'monthly-year-end-session'
    running = await schedules.patch(created['id'], {'sessionId': session_id, 'status': 'RUNNING', 'executionEpoch': 1})
    finished = datetime(year, 12, 31, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(schedule_module, 'now', lambda: finished)

    completed = await schedules.complete(running, {'total': 3, 'done': 3, 'withData': 3, 'noData': 0, 'failed': 0})

    assert completed['status'] == 'COMPLETED'
    assert completed['enabled'] is False
    assert completed['nextRunAt'] is None
    assert completed['annualRolloverYear'] == year + 1
    assert completed['message'].find(f'Year {year} is complete') >= 0
    assert completed['profileId'] == source['id']

    successor = await schedules.get(completed['annualSuccessorScheduleId'], owner)
    copied_profile = await profiles.get(owner, successor['profileId'])
    assert successor['id'] != created['id']
    assert successor['profileId'] != source['id']
    assert successor['annualSeriesId'] == created['annualSeriesId']
    assert successor['annualSourceScheduleId'] == created['id']
    assert successor['year'] == year + 1
    assert successor['repeat'] == 'monthly'
    assert successor['timeZone'] == created['timeZone']
    assert copied_profile['definition'] == {
        **source['definition'],
        'report': {**source['definition']['report'], 'year': year + 1},
    }
    assert copied_profile['definition']['fields'] == source['definition']['fields']
    assert copied_profile['id'] != source['id']
    assert copied_profile['name'].endswith(f'({year + 1})')

    zone = ZoneInfo(successor['timeZone'])
    start = datetime.fromisoformat(successor['startsAt']).astimezone(zone)
    next_run = datetime.fromisoformat(successor['nextRunAt']).astimezone(zone)
    original = starts_at.astimezone(zone)
    assert (start.year, start.month, start.day, start.hour, start.minute) == (
        year + 1, 1, original.day, original.hour, original.minute)
    assert next_run == start
    assert await schedules.complete(running, {'total': 3, 'done': 3, 'withData': 3, 'noData': 0, 'failed': 0}) is None
    with pytest.raises(ValueError, match='has ended'):
        await schedules.toggle(created['id'], owner, True)


@pytest.mark.asyncio
async def test_disabled_monthly_schedule_does_not_create_next_year_schedule(admin_headers, monkeypatch):
    owner = 'test-admin'
    year = datetime.now().year
    profiles = FilterProfileRepository()
    source = await profiles.save(owner, ProfileWrite.model_validate({
        'name': 'Paused annual reports', 'definition': filter_definition(year)}))
    starts_at = datetime.now(timezone.utc) + timedelta(hours=1)
    command = RunScheduleCreate.model_validate({'profileId': source['id'], 'year': year,
        'startsAt': starts_at.isoformat(), 'repeat': 'monthly'})
    schedules = RunScheduleRepository()
    created = await schedules.create(owner, command)
    running = await schedules.patch(created['id'], {'sessionId': 'disabled-year-end-session',
        'status': 'RUNNING', 'executionEpoch': 1})
    running = await schedules.toggle(created['id'], owner, False)
    monkeypatch.setattr(schedule_module, 'now', lambda: datetime(year, 12, 31, 12, 0, tzinfo=timezone.utc))

    completed = await schedules.complete(running, {'total': 1, 'done': 1, 'withData': 1, 'noData': 0, 'failed': 0})

    assert completed['enabled'] is False
    assert completed.get('annualSuccessorScheduleId') is None
    assert completed['nextRunAt'] is not None


def test_filter_profiles_accept_the_next_calendar_year_for_automatic_rollover():
    next_year = datetime.now().year + 1
    saved = ProfileDefinition.model_validate(filter_definition(next_year))
    assert saved.report.year == next_year
    with pytest.raises(ValueError, match='following year'):
        ProfileDefinition.model_validate(filter_definition(next_year + 1))


def test_new_schedules_allow_once_and_monthly_but_not_daily():
    inputs = {'profileId': '7d3627cc-703f-4a91-8871-e8c92ad44837', 'year': datetime.now().year,
        'startsAt': (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()}
    assert RunScheduleCreate.model_validate({**inputs, 'repeat': 'once'}).repeat == 'once'
    assert RunScheduleCreate.model_validate({**inputs, 'repeat': 'monthly'}).repeat == 'monthly'
    with pytest.raises(ValidationError):
        RunScheduleCreate.model_validate({**inputs, 'repeat': 'daily'})


@pytest.mark.asyncio
async def test_once_schedule_completes_without_creating_next_year_filter_or_schedule(admin_headers, monkeypatch):
    owner = 'test-admin'
    year = datetime.now().year
    profiles = FilterProfileRepository()
    source = await profiles.save(owner, ProfileWrite.model_validate({
        'name': 'One time vehicle reports', 'definition': filter_definition(year)}))
    starts_at = datetime.now(timezone.utc) + timedelta(hours=1)
    command = RunScheduleCreate.model_validate({'profileId': source['id'], 'year': year,
        'startsAt': starts_at.isoformat(), 'repeat': 'once'})
    schedules = RunScheduleRepository()
    created = await schedules.create(owner, command)
    session_id = 'one-time-report-session'
    running = await schedules.patch(created['id'], {'sessionId': session_id, 'status': 'RUNNING', 'executionEpoch': 1})
    monkeypatch.setattr(schedule_module, 'now', lambda: datetime(year, 12, 31, 12, 0, tzinfo=timezone.utc))

    completed = await schedules.complete(running, {'total': 1, 'done': 1, 'withData': 1, 'noData': 0, 'failed': 0})

    assert completed['status'] == 'COMPLETED'
    assert completed['enabled'] is False
    assert completed['nextRunAt'] is None
    assert completed.get('annualSuccessorScheduleId') is None
    assert await schedules.list(owner) == [completed]

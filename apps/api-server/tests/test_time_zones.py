from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from app.repositories.run_schedules import annual_profile_name, monthly_start_for_year, next_monthly_run


@pytest.mark.parametrize('zone,offset', [('Asia/Ho_Chi_Minh', '+07:00'), ('Asia/Kolkata', '+05:30')])
@pytest.mark.parametrize('year,last_february_day', [(2024, 29), (2026, 28)])
def test_monthly_schedule_clamps_february_then_recovers_original_day(zone, offset, year, last_february_day):
    anchor = f'{year}-01-31T23:45:00{offset}'
    feb = datetime.fromisoformat(next_monthly_run(anchor, datetime(year, 2, 1, tzinfo=timezone.utc), zone))
    local = feb.astimezone(ZoneInfo(zone))
    assert (local.month, local.day, local.hour, local.minute) == (2, last_february_day, 23, 45)
    march = datetime.fromisoformat(next_monthly_run(anchor, datetime(year, 3, 1, tzinfo=timezone.utc), zone))
    local = march.astimezone(ZoneInfo(zone))
    assert (local.month, local.day, local.hour, local.minute) == (3, 31, 23, 45)


@pytest.mark.parametrize('zone,offset', [('Asia/Ho_Chi_Minh', '+07:00'), ('Asia/Kolkata', '+05:30')])
def test_annual_monthly_schedule_starts_in_january_with_same_wall_clock(zone, offset):
    anchor = f'2026-10-12T08:35:00{offset}'
    current = datetime(2026, 12, 31, 12, 0, tzinfo=timezone.utc)
    starts_at, next_run = monthly_start_for_year(anchor, 2027, current, zone)
    local_start = datetime.fromisoformat(starts_at).astimezone(ZoneInfo(zone))
    local_next = datetime.fromisoformat(next_run).astimezone(ZoneInfo(zone))
    assert (local_start.year, local_start.month, local_start.day, local_start.hour, local_start.minute) == (2027, 1, 12, 8, 35)
    assert local_next == local_start


@pytest.mark.parametrize('zone', ['Asia/Ho_Chi_Minh', 'Asia/Kolkata'])
def test_annual_monthly_schedule_catches_up_if_january_slot_passed(zone):
    anchor = '2026-10-12T08:35:00+00:00'
    current = datetime(2027, 1, 20, 9, 0, tzinfo=timezone.utc)
    starts_at, next_run = monthly_start_for_year(anchor, 2027, current, zone)
    assert datetime.fromisoformat(next_run) == current
    assert datetime.fromisoformat(starts_at).astimezone(ZoneInfo(zone)).month == 1


def test_annual_profile_name_changes_year_without_accumulating_suffixes():
    assert annual_profile_name('Monthly registration filters (2026)', 2026, 2027) == 'Monthly registration filters (2027)'
    assert annual_profile_name('Monthly registration filters', 2026, 2027) == 'Monthly registration filters (2027)'

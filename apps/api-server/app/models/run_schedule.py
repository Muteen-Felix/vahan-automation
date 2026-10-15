from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

from pydantic import Field, field_validator, model_validator
from app.models.filter_profile import StrictModel


class AutomaticWorkersCommand(StrictModel):
    @model_validator(mode='before')
    @classmethod
    def ignore_legacy_worker_count(cls, value):
        # Older dashboards may still send the removed setting. It must never
        # select a pool or resize a saved queue.
        if isinstance(value, dict):
            value = {key: item for key, item in value.items() if key not in {'workerCount', 'worker_count'}}
        return value


class RunScheduleCreate(AutomaticWorkersCommand):
    profile_id: UUID = Field(alias='profileId')
    starts_at: datetime = Field(alias='startsAt')
    time_zone: Literal['Asia/Ho_Chi_Minh', 'Asia/Kolkata'] = Field(default='Asia/Ho_Chi_Minh', alias='timeZone')
    year: int = Field(ge=1900, strict=True)
    repeat: Literal['once', 'monthly'] = 'once'

    @field_validator('starts_at')
    @classmethod
    def future_time(cls, value):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError('Include the time zone in the scheduled date and time.')
        value = value.astimezone(timezone.utc)
        if value <= datetime.now(timezone.utc):
            raise ValueError('Choose a future date and time.')
        return value

    @field_validator('year')
    @classmethod
    def valid_year(cls, value):
        if value > datetime.now().year + 1:
            raise ValueError('Choose the current calendar year or the following year.')
        return value


class RunScheduleTimeZone(StrictModel):
    time_zone: Literal['Asia/Ho_Chi_Minh', 'Asia/Kolkata'] = Field(alias='timeZone')


class RunScheduleToggle(StrictModel):
    enabled: bool = Field(strict=True)


class RunScheduleResume(AutomaticWorkersCommand):
    pass

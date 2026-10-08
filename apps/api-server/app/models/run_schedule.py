from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

from pydantic import Field, field_validator
from app.models.filter_profile import StrictModel


class RunScheduleCreate(StrictModel):
    profile_id: UUID = Field(alias='profileId')
    starts_at: datetime = Field(alias='startsAt')
    worker_count: int = Field(alias='workerCount', ge=1, le=10, strict=True)
    year: int = Field(ge=1900, strict=True)
    repeat: Literal['once', 'daily', 'monthly'] = 'once'

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
        if value > datetime.now().year:
            raise ValueError('Choose the current calendar year or an earlier year.')
        return value


class RunScheduleToggle(StrictModel):
    enabled: bool = Field(strict=True)


class RunScheduleResume(StrictModel):
    worker_count: int = Field(alias='workerCount', ge=1, le=10, strict=True)

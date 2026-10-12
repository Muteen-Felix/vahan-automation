from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


DEFAULT_UI_HEALTH_INTERVAL_DAYS = 3


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class UiHealthSchedule(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    interval_days: int = Field(default=DEFAULT_UI_HEALTH_INTERVAL_DAYS, alias="intervalDays", ge=1, le=365)
    updated_at: datetime = Field(default_factory=utc_now, alias="updatedAt")
    next_check_at: datetime = Field(alias="nextCheckAt")

    @classmethod
    def default(cls) -> "UiHealthSchedule":
        updated_at = utc_now()
        return cls(
            intervalDays=DEFAULT_UI_HEALTH_INTERVAL_DAYS,
            updatedAt=updated_at,
            nextCheckAt=updated_at + timedelta(days=DEFAULT_UI_HEALTH_INTERVAL_DAYS),
        )


class UiHealthLogRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    health_check: dict[str, Any] = Field(alias="healthCheck")
    page_url: str = Field(default="", alias="pageUrl", max_length=2_000)
    runner_id: str | None = Field(default=None, alias="runnerId", max_length=128)


class UiHealthLogResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    ok: bool = True
    log_id: str = Field(alias="logId")
    file_name: str = Field(alias="fileName")
    row_count: int = Field(alias="rowCount", ge=1)
    from_date: str = Field(alias="fromDate")
    to_date: str = Field(alias="toDate")
    part: int = Field(ge=1)
    validation: dict[str, Any] | None = None


class UiHealthDaySummary(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    date: str
    total: int = 0
    passed: int = Field(default=0, alias="pass")
    data_changed: int = Field(default=0, alias="dataChanged")
    data_changed_errors: int = Field(default=0, alias="dataChangedErrors")
    ui_drift: int = Field(default=0, alias="uiDrift")
    ui_drift_errors: int = Field(default=0, alias="uiDriftErrors")
    check_error: int = Field(default=0, alias="checkError")
    latest_checked_at: str = Field(default="", alias="latestCheckedAt")


class UiHealthReportFile(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    file_name: str = Field(alias="fileName")
    from_date: str = Field(alias="fromDate")
    to_date: str = Field(alias="toDate")
    part: int = Field(ge=1)
    row_count: int = Field(alias="rowCount", ge=0)
    size_bytes: int = Field(alias="sizeBytes", ge=0)
    updated_at: str = Field(alias="updatedAt")
    contains_selected_date: bool = Field(alias="containsSelectedDate")
    download_url: str = Field(alias="downloadUrl")


class UiHealthReportsResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    selected_date: str | None = Field(default=None, alias="selectedDate")
    available_dates: list[UiHealthDaySummary] = Field(default_factory=list, alias="availableDates")
    reports: list[UiHealthReportFile] = Field(default_factory=list)
    rows: list[dict[str, str]] = Field(default_factory=list)

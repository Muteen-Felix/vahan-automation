from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from app.models.filters import VahanFilters


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class JobStatus(StrEnum):
    QUEUED = "QUEUED"
    ASSIGNED = "ASSIGNED"
    OPENING_VAHAN = "OPENING_VAHAN"
    CAPTURING_CAPTCHA = "CAPTURING_CAPTCHA"
    FILLING_FILTERS = "FILLING_FILTERS"
    WAITING_CAPTCHA = "WAITING_CAPTCHA"
    SUBMITTING = "SUBMITTING"
    WAITING_RESULT = "WAITING_RESULT"
    COMPLETED = "COMPLETED"
    NO_DATA = "NO_DATA"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class ReportSource(StrEnum):
    NEW = "new"
    OLD = "old"


ALLOWED_JOB_TRANSITIONS: dict[JobStatus, set[JobStatus]] = {
    JobStatus.QUEUED: {JobStatus.ASSIGNED, JobStatus.FAILED, JobStatus.CANCELLED},
    JobStatus.ASSIGNED: {JobStatus.OPENING_VAHAN, JobStatus.FAILED, JobStatus.CANCELLED},
    JobStatus.OPENING_VAHAN: {
        JobStatus.CAPTURING_CAPTCHA,
        JobStatus.FILLING_FILTERS,
        JobStatus.FAILED,
        JobStatus.CANCELLED,
    },
    JobStatus.CAPTURING_CAPTCHA: {JobStatus.WAITING_CAPTCHA, JobStatus.FAILED, JobStatus.CANCELLED},
    JobStatus.FILLING_FILTERS: {
        JobStatus.CAPTURING_CAPTCHA,
        JobStatus.WAITING_CAPTCHA,
        JobStatus.SUBMITTING,
        JobStatus.FAILED,
        JobStatus.CANCELLED,
    },
    JobStatus.WAITING_CAPTCHA: {JobStatus.SUBMITTING, JobStatus.FAILED, JobStatus.CANCELLED},
    JobStatus.SUBMITTING: {JobStatus.WAITING_RESULT, JobStatus.WAITING_CAPTCHA, JobStatus.FAILED, JobStatus.CANCELLED},
    JobStatus.WAITING_RESULT: {JobStatus.WAITING_CAPTCHA, JobStatus.COMPLETED, JobStatus.NO_DATA, JobStatus.FAILED, JobStatus.CANCELLED},
    JobStatus.COMPLETED: set(),
    JobStatus.NO_DATA: set(),
    JobStatus.FAILED: set(),
    JobStatus.CANCELLED: set(),
}


def can_transition(current: JobStatus, target: JobStatus) -> bool:
    return current == target or target in ALLOWED_JOB_TRANSITIONS[current]


class CreateJobRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    runner_id: str = Field(alias="runnerId", min_length=1, max_length=128)
    filters: VahanFilters
    scenario_name: str | None = Field(default=None, alias="scenarioName")
    session_id: UUID | None = Field(default=None, alias="sessionId")
    retry_of_job_id: UUID | None = Field(default=None, alias="retryOfJobId")
    source: ReportSource = ReportSource.NEW


class Job(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: UUID = Field(default_factory=uuid4)
    owner_username: str | None = Field(default=None, alias="ownerUsername")
    runner_id: str = Field(alias="runnerId")
    session_id: UUID = Field(default_factory=uuid4, alias="sessionId")
    retry_of_job_id: UUID | None = Field(default=None, alias="retryOfJobId")
    case_id: UUID | None = Field(default=None, alias="caseId")
    status: JobStatus = JobStatus.QUEUED
    filters: VahanFilters
    scenario_name: str | None = Field(default=None, alias="scenarioName")
    source: ReportSource = ReportSource.NEW
    captcha_id: str | None = Field(default=None, alias="captchaId")
    captcha_image_data_url: str | None = Field(default=None, alias="captchaImageDataUrl", exclude=True)
    error: str | None = None
    excel_file_name: str | None = Field(default=None, alias="excelFileName")
    excel_file_size: int | None = Field(default=None, alias="excelFileSize")
    no_data_file_name: str | None = Field(default=None, alias="noDataFileName")
    result_message: str | None = Field(default=None, alias="resultMessage")
    result_observed_at: datetime | None = Field(default=None, alias="resultObservedAt")
    report_table_count: int | None = Field(default=None, alias="reportTableCount")
    report_row_count: int | None = Field(default=None, alias="reportRowCount")
    main_report_saved_at: datetime | None = Field(default=None, alias="mainReportSavedAt")
    main_report_checksum: str | None = Field(default=None, alias="mainReportChecksum")
    main_report_summary: dict | None = Field(default=None, alias="mainReportSummary")
    result_checksum: str | None = Field(default=None, alias="resultChecksum")
    filter_execution: dict = Field(default_factory=dict, alias="filterExecution")
    successful_apply_count: int = Field(default=0, alias="successfulApplyCount", ge=0)
    successful_apply_click_ids: list[str] = Field(default_factory=list, exclude=True)
    created_at: datetime = Field(default_factory=utc_now, alias="createdAt")
    updated_at: datetime = Field(default_factory=utc_now, alias="updatedAt")

    def touch(self) -> None:
        self.updated_at = utc_now()

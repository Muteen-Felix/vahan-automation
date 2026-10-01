from datetime import datetime, timezone
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field
from app.models.job import ReportSource


class RunnerStatus(StrEnum):
    ONLINE = "ONLINE"
    BUSY = "BUSY"
    RECONNECTING = "RECONNECTING"


class Runner(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    name: str
    version: str | None = None
    source: ReportSource = ReportSource.NEW
    socket_id: str = Field(alias="socketId", exclude=True)
    status: RunnerStatus = RunnerStatus.ONLINE
    current_job_id: str | None = Field(default=None, alias="currentJobId")
    last_seen_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        alias="lastSeenAt",
    )

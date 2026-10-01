import asyncio
from collections.abc import Callable
from uuid import UUID

from app.models.job import Job, JobStatus, can_transition


class InMemoryJobRepository:
    def __init__(self) -> None:
        self._jobs: dict[UUID, Job] = {}
        self._lock = asyncio.Lock()

    async def create(self, job: Job) -> Job:
        async with self._lock:
            self._jobs[job.id] = job
            return job.model_copy(deep=True)

    async def get(self, job_id: UUID) -> Job | None:
        async with self._lock:
            job = self._jobs.get(job_id)
            return job.model_copy(deep=True) if job else None

    async def update_status(
        self,
        job_id: UUID,
        status: JobStatus,
        *,
        error: str | None = None,
        captcha_id: str | None = None,
        captcha_image_data_url: str | None = None,
    ) -> Job | None:
        async with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return None
            job.status = status
            job.error = error
            if captcha_id is not None:
                job.captcha_id = captcha_id
            if captcha_image_data_url is not None:
                job.captcha_image_data_url = captcha_image_data_url
            job.touch()
            return job.model_copy(deep=True)

    async def transition_status(
        self,
        job_id: UUID,
        status: JobStatus,
        *,
        error: str | None = None,
        no_data_writer: Callable[[Job], str] | None = None,
    ) -> Job | None:
        """Check and commit runner results and cancellation under one lock."""
        async with self._lock:
            job = self._jobs.get(job_id)
            if not job or not can_transition(job.status, status):
                return None
            if status == JobStatus.NO_DATA:
                if job.excel_file_name or no_data_writer is None:
                    return None
                if not job.no_data_file_name:
                    job.no_data_file_name = no_data_writer(job.model_copy(deep=True))
            job.status = status
            job.error = error
            job.touch()
            return job.model_copy(deep=True)

    async def set_excel_file(
        self,
        job_id: UUID,
        *,
        file_name: str,
        file_size: int,
    ) -> Job | None:
        async with self._lock:
            job = self._jobs.get(job_id)
            if not job or job.status != JobStatus.WAITING_RESULT:
                return None
            job.excel_file_name = file_name
            job.excel_file_size = file_size
            job.touch()
            return job.model_copy(deep=True)

    async def set_no_data_file(self, job_id: UUID, file_name: str) -> Job | None:
        async with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return None
            job.no_data_file_name = file_name
            job.touch()
            return job.model_copy(deep=True)

    async def record_successful_apply_click(self, job_id: UUID, click_id: str) -> Job | None:
        async with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return None
            if click_id in job.successful_apply_click_ids:
                return job.model_copy(deep=True)
            job.successful_apply_click_ids.append(click_id)
            job.successful_apply_count += 1
            job.touch()
            return job.model_copy(deep=True)

    async def list_all(self) -> list[Job]:
        async with self._lock:
            return [job.model_copy(deep=True) for job in self._jobs.values()]

    async def clear(self) -> None:
        async with self._lock:
            self._jobs.clear()

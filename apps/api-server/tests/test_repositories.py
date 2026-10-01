from uuid import UUID

from app.models.job import Job, JobStatus, can_transition
from app.models.runner import RunnerStatus
from app.repositories import InMemoryJobRepository, InMemoryRunnerRegistry


async def test_job_repository_returns_copies() -> None:
    repository = InMemoryJobRepository()
    created = await repository.create(Job(runnerId="runner-1", filters={}))
    created.status = JobStatus.FAILED

    stored = await repository.get(created.id)
    assert stored is not None
    assert stored.status == JobStatus.QUEUED


async def test_runner_registry_tracks_socket_and_busy_state() -> None:
    registry = InMemoryRunnerRegistry()
    runner = await registry.register(
        runner_id="runner-1",
        name="Chrome",
        socket_id="socket-1",
    )
    assert runner.status == RunnerStatus.ONLINE

    updated = await registry.set_job("runner-1", str(UUID(int=1)))
    assert updated is not None
    assert updated.status == RunnerStatus.BUSY

    by_socket = await registry.get_by_socket("socket-1")
    assert by_socket is not None
    assert by_socket.id == "runner-1"

    removed = await registry.remove_by_socket("socket-1")
    assert removed is not None
    assert await registry.get("runner-1") is None


async def test_runner_registry_preserves_job_on_reconnect() -> None:
    registry = InMemoryRunnerRegistry()
    await registry.register(runner_id="runner-1", name="Chrome", socket_id="socket-1")
    job_id = str(UUID(int=2))
    await registry.set_job("runner-1", job_id)
    reconnecting = await registry.mark_reconnecting("socket-1")
    assert reconnecting is not None
    assert reconnecting.status == RunnerStatus.RECONNECTING

    restored = await registry.register(runner_id="runner-1", name="Chrome", socket_id="socket-2")
    assert restored.current_job_id == job_id
    assert restored.status == RunnerStatus.BUSY
    assert await registry.get_by_socket("socket-1") is None


def test_job_state_machine_rejects_stale_terminal_updates() -> None:
    assert can_transition(JobStatus.ASSIGNED, JobStatus.OPENING_VAHAN)
    assert can_transition(JobStatus.OPENING_VAHAN, JobStatus.CAPTURING_CAPTCHA)
    assert can_transition(JobStatus.CAPTURING_CAPTCHA, JobStatus.WAITING_CAPTCHA)
    assert can_transition(JobStatus.SUBMITTING, JobStatus.WAITING_CAPTCHA)
    assert can_transition(JobStatus.WAITING_RESULT, JobStatus.COMPLETED)
    assert can_transition(JobStatus.WAITING_RESULT, JobStatus.NO_DATA)
    assert not can_transition(JobStatus.CANCELLED, JobStatus.NO_DATA)
    assert not can_transition(JobStatus.CANCELLED, JobStatus.WAITING_RESULT)
    assert not can_transition(JobStatus.COMPLETED, JobStatus.FAILED)


async def test_cancelled_job_rejects_late_no_data_and_report_results() -> None:
    repository = InMemoryJobRepository()
    job = await repository.create(Job(runnerId="runner-1", filters={}))
    await repository.update_status(job.id, JobStatus.WAITING_RESULT)
    cancelled = await repository.transition_status(job.id, JobStatus.CANCELLED)
    assert cancelled is not None and cancelled.status == JobStatus.CANCELLED

    marker_written = False

    def write_marker(_job: Job) -> str:
        nonlocal marker_written
        marker_written = True
        return "report.txt"

    assert await repository.transition_status(
        job.id, JobStatus.NO_DATA, no_data_writer=write_marker,
    ) is None
    assert await repository.transition_status(job.id, JobStatus.COMPLETED) is None
    assert await repository.set_excel_file(job.id, file_name="report.xlsx", file_size=100) is None
    assert not marker_written
    stored = await repository.get(job.id)
    assert stored is not None and stored.status == JobStatus.CANCELLED
    assert stored.no_data_file_name is None

import asyncio
from datetime import datetime, timezone

from app.models.runner import Runner, RunnerStatus
from app.models.job import ReportSource


class InMemoryRunnerRegistry:
    def __init__(self) -> None:
        self._runners: dict[str, Runner] = {}
        self._socket_to_runner: dict[str, str] = {}
        self._lock = asyncio.Lock()

    async def register(
        self,
        *,
        runner_id: str,
        name: str,
        socket_id: str,
        version: str | None = None,
        source: ReportSource = ReportSource.NEW,
    ) -> Runner:
        runner = Runner(
            id=runner_id,
            name=name,
            version=version,
            source=source,
            socketId=socket_id,
        )
        async with self._lock:
            previous = self._runners.get(runner_id)
            if previous:
                self._socket_to_runner.pop(previous.socket_id, None)
                runner.current_job_id = previous.current_job_id
                runner.status = RunnerStatus.BUSY if previous.current_job_id else RunnerStatus.ONLINE
            self._runners[runner_id] = runner
            self._socket_to_runner[socket_id] = runner_id
            return runner.model_copy(deep=True)

    async def mark_reconnecting(self, socket_id: str) -> Runner | None:
        async with self._lock:
            runner_id = self._socket_to_runner.get(socket_id)
            runner = self._runners.get(runner_id) if runner_id else None
            if not runner or runner.socket_id != socket_id:
                return None
            runner.status = RunnerStatus.RECONNECTING
            return runner.model_copy(deep=True)

    async def heartbeat(self, runner_id: str) -> Runner | None:
        async with self._lock:
            runner = self._runners.get(runner_id)
            if not runner:
                return None
            runner.last_seen_at = datetime.now(timezone.utc)
            return runner.model_copy(deep=True)

    async def get(self, runner_id: str) -> Runner | None:
        async with self._lock:
            runner = self._runners.get(runner_id)
            return runner.model_copy(deep=True) if runner else None

    async def get_by_socket(self, socket_id: str) -> Runner | None:
        async with self._lock:
            runner_id = self._socket_to_runner.get(socket_id)
            runner = self._runners.get(runner_id) if runner_id else None
            return runner.model_copy(deep=True) if runner else None

    async def list(self) -> list[Runner]:
        async with self._lock:
            return [runner.model_copy(deep=True) for runner in self._runners.values()]

    async def set_job(self, runner_id: str, job_id: str | None) -> Runner | None:
        async with self._lock:
            runner = self._runners.get(runner_id)
            if not runner:
                return None
            runner.current_job_id = job_id
            runner.status = RunnerStatus.BUSY if job_id else RunnerStatus.ONLINE
            runner.last_seen_at = datetime.now(timezone.utc)
            return runner.model_copy(deep=True)

    async def release_job(self, runner_id: str, job_id: str) -> Runner | None:
        """Release only the completed job, preserving any newer assignment."""
        async with self._lock:
            runner = self._runners.get(runner_id)
            if not runner or runner.current_job_id != job_id:
                return None
            runner.current_job_id = None
            runner.status = RunnerStatus.ONLINE
            runner.last_seen_at = datetime.now(timezone.utc)
            return runner.model_copy(deep=True)

    async def remove_by_socket(self, socket_id: str) -> Runner | None:
        async with self._lock:
            runner_id = self._socket_to_runner.pop(socket_id, None)
            if not runner_id:
                return None
            runner = self._runners.get(runner_id)
            if runner and runner.socket_id == socket_id:
                return self._runners.pop(runner_id)
            return None

    async def clear(self) -> None:
        async with self._lock:
            self._runners.clear()
            self._socket_to_runner.clear()

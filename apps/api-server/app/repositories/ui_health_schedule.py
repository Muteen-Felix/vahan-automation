from __future__ import annotations

import asyncio

from app.models.ui_health import UiHealthSchedule


class InMemoryUiHealthScheduleRepository:
    def __init__(self) -> None:
        self._schedule = UiHealthSchedule.default()
        self._lock = asyncio.Lock()

    async def get(self) -> UiHealthSchedule:
        async with self._lock:
            return self._schedule.model_copy(deep=True)

    async def update(self, interval_days: int) -> UiHealthSchedule:
        async with self._lock:
            self._schedule = UiHealthSchedule.for_interval(interval_days)
            return self._schedule.model_copy(deep=True)

    async def clear(self) -> None:
        async with self._lock:
            self._schedule = UiHealthSchedule.default()

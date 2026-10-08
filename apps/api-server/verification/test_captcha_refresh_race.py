"""The refresh event must not revive a job that moved on while it was saved."""

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from app.models.job import JobStatus, ReportSource
from app.realtime import runner_events


class CaptchaRefreshRaceTest(unittest.IsolatedAsyncioTestCase):
    async def test_initial_and_invalid_challenges_losing_cancel_race_do_not_emit(self):
        job_id = uuid4()
        runner = SimpleNamespace(id="playwright-1", source=ReportSource.NEW)
        payload = {"jobId": str(job_id), "captchaId": "new",
                   "imageDataUrl": "data:image/png;base64,AA=="}
        for handler, status in ((runner_events.captcha_required, JobStatus.FILLING_FILTERS),
                                (runner_events.captcha_invalid, JobStatus.WAITING_RESULT)):
            with self.subTest(handler=handler.__name__):
                job = SimpleNamespace(id=job_id, runner_id=runner.id,
                                      status=status, captcha_id="old")
                with patch.object(runner_events.services.runners, "get_by_socket", AsyncMock(return_value=runner)), \
                     patch.object(runner_events.services.jobs, "get", AsyncMock(return_value=job)), \
                     patch.object(runner_events.services.captcha_images, "save", AsyncMock(return_value="stored")), \
                     patch.object(runner_events.services.jobs, "update_status", AsyncMock(return_value=None)) as update, \
                     patch.object(runner_events.sio, "emit", AsyncMock()) as emit:
                    result = await handler("socket", payload)
                self.assertFalse(result["ok"])
                self.assertEqual(update.await_args.kwargs["expected_status"], status)
                emit.assert_not_awaited()

    async def test_late_refresh_cannot_revert_submitting_job(self):
        job_id = uuid4()
        runner = SimpleNamespace(id="playwright-1", source=ReportSource.NEW)
        job = SimpleNamespace(id=job_id, runner_id=runner.id,
                              status=JobStatus.SUBMITTING, captcha_id="old")
        payload = {"jobId": str(job_id), "captchaId": "new",
                   "imageDataUrl": "data:image/png;base64,AA=="}
        with patch.object(runner_events.services.runners, "get_by_socket", AsyncMock(return_value=runner)), \
             patch.object(runner_events.services.jobs, "get", AsyncMock(return_value=job)), \
             patch.object(runner_events.services.captcha_images, "save", AsyncMock()) as save, \
             patch.object(runner_events.services.jobs, "update_status", AsyncMock()) as update:
            result = await runner_events.captcha_refreshed("socket", payload)
        self.assertFalse(result["ok"])
        save.assert_not_awaited()
        update.assert_not_awaited()

    async def test_refresh_losing_status_race_returns_error_without_emitting(self):
        job_id = uuid4()
        runner = SimpleNamespace(id="playwright-1", source=ReportSource.NEW)
        job = SimpleNamespace(id=job_id, runner_id=runner.id,
                              status=JobStatus.WAITING_CAPTCHA, captcha_id="old")
        payload = {"jobId": str(job_id), "captchaId": "new",
                   "imageDataUrl": "data:image/png;base64,AA=="}
        with patch.object(runner_events.services.runners, "get_by_socket", AsyncMock(return_value=runner)), \
             patch.object(runner_events.services.jobs, "get", AsyncMock(return_value=job)), \
             patch.object(runner_events.services.captcha_images, "save", AsyncMock(return_value="stored")), \
             patch.object(runner_events.services.jobs, "update_status", AsyncMock(return_value=None)) as update, \
             patch.object(runner_events.sio, "emit", AsyncMock()) as emit:
            result = await runner_events.captcha_refreshed("socket", payload)
        self.assertFalse(result["ok"])
        update.assert_awaited_once()
        self.assertEqual(update.await_args.kwargs["expected_status"], JobStatus.WAITING_CAPTCHA)
        self.assertEqual(update.await_args.kwargs["expected_captcha_id"], "old")
        emit.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()

"""CAPTCHA events keep IDs/status only; these tests never connect to a database."""
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from app.models.job import Job, JobStatus, ReportSource
from app.realtime import runner_events
from app.repositories.postgres import job_document


class EphemeralCaptchaTests(unittest.IsolatedAsyncioTestCase):
    async def test_required_invalid_and_refreshed_do_not_store_or_forward_images(self):
        runner=SimpleNamespace(id='playwright-1',source=ReportSource.NEW)
        for handler,status in ((runner_events.captcha_required,JobStatus.FILLING_FILTERS),
                               (runner_events.captcha_invalid,JobStatus.WAITING_RESULT),
                               (runner_events.captcha_refreshed,JobStatus.WAITING_CAPTCHA)):
            for legacy in (False,True):
                with self.subTest(handler=handler.__name__,legacy=legacy):
                    job=Job(id=uuid4(),runnerId=runner.id,status=status,captchaId='old',filters={})
                    payload={'jobId':str(job.id),'captchaId':'new'}
                    if legacy:payload['imageDataUrl']='data:image/png;base64,aW1hZ2U='
                    updated=job.model_copy(update={'status':JobStatus.WAITING_CAPTCHA,'captcha_id':'new'})
                    with patch.object(runner_events.services.runners,'get_by_socket',AsyncMock(return_value=runner)), \
                         patch.object(runner_events.services.jobs,'get',AsyncMock(return_value=job)), \
                         patch.object(runner_events.services.jobs,'update_status',AsyncMock(return_value=updated)) as update, \
                         patch.object(runner_events.services.captcha_images,'save',AsyncMock(side_effect=AssertionError('no image storage'))) as save, \
                         patch.object(runner_events.sio,'emit',AsyncMock()) as emit:
                        self.assertTrue((await handler('socket',payload))['ok'])
                    save.assert_not_awaited()
                    self.assertEqual(update.await_args.kwargs['captcha_image_data_url'],'')
                    for call in emit.await_args_list:
                        self.assertNotIn('imageDataUrl',json.dumps(call.args[1]))
                        self.assertNotIn('data:image/',json.dumps(call.args[1]))

    async def test_job_sql_document_excludes_legacy_image_bytes(self):
        job=Job(runnerId='playwright-1',filters={},captchaId='fixture',
                captchaImageDataUrl='data:image/png;base64,aW1hZ2U=')
        payload=job_document(job)
        self.assertEqual(payload['captcha_id'],'fixture')
        self.assertNotIn('captcha_image_data_url',payload)
        self.assertNotIn('data:image/',json.dumps(payload))


if __name__=='__main__':unittest.main(verbosity=2)

import base64
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

from fastapi import HTTPException, Request, Response
from socketio.exceptions import TimeoutError as SocketIOTimeoutError
from app.api import run_schedules as route
from app.models.job import Job, JobStatus
from app.realtime.server import sio


class CaptchaViewTests(unittest.IsolatedAsyncioTestCase):
    def request(self, role='admin'):
        return Request({'type':'http','method':'GET','path':'/api/run-schedules/captchas',
                        'state':{'authenticated_user':'fixture','authenticated_role':role}})

    def job(self, age=0):
        return Job(id=uuid4(),runnerId='playwright-1',ownerUsername='fixture',filters={},
                   status=JobStatus.WAITING_CAPTCHA,captchaId='fixture-challenge',
                   updatedAt=datetime.now(timezone.utc)-timedelta(minutes=age))

    async def test_image_is_relayed_only_to_admin_without_caching_or_storage(self):
        job=self.job(); response=Response()
        image='data:image/png;base64,'+base64.b64encode(b'\x89PNG\r\n\x1a\nfixture').decode()
        with patch.object(route,'services_job',AsyncMock(return_value=job)), \
             patch.object(route.services.runners,'get',AsyncMock(return_value=SimpleNamespace(socket_id='worker'))), \
             patch.object(sio,'call',AsyncMock(return_value={'ok':True,'captchaId':job.captcha_id,'imageDataUrl':image})) as call, \
             patch.object(route.services.captcha_images,'save',AsyncMock(side_effect=AssertionError('must not persist images'))):
            result=await route.inspect_captcha(job.id,self.request(),response)
        self.assertEqual(result['imageDataUrl'],image)
        self.assertEqual(response.headers['Cache-Control'],'no-store')
        self.assertEqual(call.await_args.args[0],'captcha:inspect')
        self.assertEqual(call.await_args.kwargs['namespace'],'/runner')

    async def test_member_cannot_request_a_captcha_image(self):
        with self.assertRaises(HTTPException) as raised:
            await route.inspect_captcha(uuid4(),self.request('user'),Response())
        self.assertEqual(raised.exception.status_code,403)

    async def test_invalid_image_and_changed_challenge_are_rejected(self):
        job=self.job()
        for result,status in [({'ok':True,'captchaId':job.captcha_id,'imageDataUrl':'data:text/html;base64,AA=='},502),
                              ({'ok':True,'captchaId':'different','imageDataUrl':''},409)]:
            with patch.object(route,'services_job',AsyncMock(return_value=job)), \
                 patch.object(route.services.runners,'get',AsyncMock(return_value=SimpleNamespace(socket_id='worker'))), \
                 patch.object(sio,'call',AsyncMock(return_value=result)):
                with self.assertRaises(HTTPException) as raised:
                    await route.inspect_captcha(job.id,self.request(),Response())
                self.assertEqual(raised.exception.status_code,status)

    async def test_offline_worker_timeout_is_reported(self):
        job=self.job()
        with patch.object(route,'services_job',AsyncMock(return_value=job)), \
             patch.object(route.services.runners,'get',AsyncMock(return_value=SimpleNamespace(socket_id='worker'))), \
             patch.object(sio,'call',AsyncMock(side_effect=SocketIOTimeoutError())):
            with self.assertRaises(HTTPException) as raised:
                await route.inspect_captcha(job.id,self.request(),Response())
        self.assertEqual(raised.exception.status_code,504)

    async def test_expired_wait_is_failed_without_touching_current_challenge(self):
        expired=self.job(11); current=self.job(0)
        connection=SimpleNamespace(scalars=AsyncMock(return_value=[job.model_dump(mode='json',by_alias=True) for job in [expired,current]]))
        manager=AsyncMock();manager.__aenter__.return_value=connection
        with patch.object(route,'engine',SimpleNamespace(connect=Mock(return_value=manager))), \
             patch.object(route.services.jobs,'update_status',AsyncMock(return_value=expired.model_copy(update={'status':JobStatus.FAILED}))) as update, \
             patch.object(route.services.runners,'release_job',AsyncMock()) as release, \
             patch.object(sio,'emit',AsyncMock()) as emit:
            result=await route.current_captchas(self.request())
        self.assertEqual([row['jobId'] for row in result],[str(current.id)])
        self.assertEqual(update.await_args.kwargs['expected_captcha_id'],expired.captcha_id)
        self.assertEqual(update.await_args.kwargs['expected_status'],JobStatus.WAITING_CAPTCHA)
        release.assert_awaited_once()
        self.assertEqual(emit.await_args_list[0].args[0],'job:cancelled')


if __name__=='__main__':unittest.main(verbosity=2)

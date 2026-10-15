"""Actual HTTP/Socket.IO workers across an API process kill and restart.

The VAHAN network probe is a deterministic fixture; claims, authentication,
socket registration, startup recovery and result commits use production code.
"""
import asyncio
import os
from pathlib import Path
import socket
import sys
import tempfile
import unittest
from uuid import uuid4

from sqlalchemy.engine import make_url

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
database = os.environ.get('VAHAN_LIFECYCLE_TEST_DATABASE', '')
if not database.startswith('vahan_lifecycle_') or not database.endswith('_test'):
    raise RuntimeError('Use a disposable vahan_lifecycle_*_test database.')
os.environ['DATABASE_URL'] = make_url(os.environ['DATABASE_URL']).set(database=database).render_as_string(hide_password=False)
os.environ.setdefault('VAHAN_UI_AUTH_USERNAME', 'lifecycle-admin')
os.environ.setdefault('VAHAN_UI_AUTH_PASSWORD', 'lifecycle-fixture-only-password')

import httpx
import socketio
from sqlalchemy import func, insert, select
from app.api.batch_queue import QueueTaskInput
from app.config import settings
from app.db import engine, schema as db
from app.models.job import JobStatus
from app.models.report_result import ReportResultRequest
from app.repositories import ui_contract
from app.repositories.batch_queue import BatchQueueRepository
from app.repositories.postgres import now
from app.services import services
from app.worker_pool import apply_pool


class WorkerLifecycleTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await engine.dispose()
        async with engine.begin() as connection:
            from sqlalchemy import text
            await connection.execute(text('DROP SCHEMA public CASCADE'))
            await connection.execute(text('CREATE SCHEMA public'))
        await engine.dispose()
        import subprocess
        result = await asyncio.to_thread(subprocess.run, [sys.executable, '-m', 'app.migrate'], cwd=root,
            env=os.environ.copy(), capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        await services.users.bootstrap(settings.ui_auth_username, settings.ui_auth_password)
        self.owner = settings.ui_auth_username
        self.workers = [f'lifecycle-{i}' for i in range(3)]
        self.sockets = []
        self.process = None
        self.log = tempfile.TemporaryFile(mode='w+b')
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            self.port = listener.getsockname()[1]
        self.origin = f'http://127.0.0.1:{self.port}'
        self.http = httpx.AsyncClient(base_url=self.origin, timeout=15)
        await self.start_api()
        await self.connect_workers()

    async def asyncTearDown(self):
        for client in self.sockets:
            if client.connected:
                await client.disconnect()
        if self.process and self.process.returncode is None:
            self.process.kill()
            await self.process.wait()
        await self.http.aclose()
        self.log.close()
        await engine.dispose()

    async def start_api(self):
        code = (
            'import asyncio\nimport app.network_guard as guard\n'
            'async def fixture_monitor():\n    await asyncio.Event().wait()\n'
            'guard.monitor=fixture_monitor\n'
            f'import uvicorn\nuvicorn.run("app.main:application",host="127.0.0.1",port={self.port},log_level="warning")\n'
        )
        self.process = await asyncio.create_subprocess_exec(sys.executable, '-c', code,
            cwd=root, env=os.environ.copy(), stdout=self.log, stderr=self.log)
        for _ in range(100):
            if self.process.returncode is not None:
                self.log.seek(0)
                self.fail(self.log.read().decode(errors='replace'))
            try:
                if (await self.http.get('/api/ready')).status_code == 200:
                    return
            except httpx.TransportError:
                pass
            await asyncio.sleep(.1)
        self.fail('API did not start')

    async def connect_workers(self):
        self.sockets = []
        for worker in self.workers:
            client = socketio.AsyncClient(reconnection=False)
            await client.connect(self.origin, transports=['websocket'], namespaces=['/runner'], auth={
                'runnerId': worker, 'runnerName': worker, 'engine': 'playwright', 'source': 'new', 'token': settings.runner_token})
            self.sockets.append(client)

    async def claim(self, worker, session):
        response = await self.http.post('/api/runner/queue/claim', headers={
            'X-VAHAN-RUNNER-TOKEN': settings.runner_token, 'X-VAHAN-RUNNER-ID': worker}, json={'sessionId': str(session)})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    async def no_data(self, item, worker, command=None):
        client = self.sockets[self.workers.index(worker)]
        for status in ['OPENING_VAHAN', 'FILLING_FILTERS', 'SUBMITTING', 'WAITING_RESULT']:
            result = await client.call('job:status', {'jobId': item['jobId'], 'status': status}, namespace='/runner')
            self.assertTrue(result['ok'], result)
        command = command or ReportResultRequest(result='NO_RECORD', message='No record found', observedAt=now(),
            pageUrl='https://analytics.parivahan.gov.in/analytics/vahanpublicreport?lang=en')
        response = await self.http.post(f"/api/jobs/{item['jobId']}/report-result", headers={
            'X-VAHAN-RUNNER-TOKEN': settings.runner_token, 'X-VAHAN-RUNNER-ID': worker},
            json=command.model_dump(mode='json', by_alias=True))
        self.assertEqual(response.status_code, 200, response.text)
        return command

    async def test_parallel_http_workers_restart_resume_and_commit_nine_unique_cases(self):
        queue, session = BatchQueueRepository(), uuid4()
        observed = [{**seed, 'found': True, 'count': 1, 'inputType': 'text', 'matchedBy': 'selector'} for seed in ui_contract.SEEDS]
        validation = await ui_contract.evaluate({'status': 'PASS', 'observedControls': observed}, self.workers[0])
        gate = str(uuid4())
        async with engine.begin() as connection:
            await connection.execute(insert(db.ui_preflight_checks).values(id=gate, owner_username=self.owner,
                runner_ids=self.workers, version_id=validation['versionId'], status='PASS', reports=[validation], created_at=now()))
        await apply_pool(3)
        await queue.start(session, self.owner, [QueueTaskInput(name=f'Lifecycle office {i}', filters={
            'states': ['Fixture State'], 'rtos': [f'Lifecycle office {i}'], 'fromYear': '2024', 'toYear': '2024'})
            for i in range(9)], 3)
        await ui_contract.bind_gate(session, gate)
        first = await asyncio.gather(*(self.claim(worker, session) for worker in self.workers))
        self.assertEqual(len({item['jobId'] for item in first}), 3)
        self.assertTrue(all(item['job'].get('jobId', item['job'].get('id')) == item['jobId'] for item in first))
        command = await self.no_data(first[0], self.workers[0])
        self.process.kill()
        await self.process.wait()
        for client in self.sockets:
            if client.connected:
                await client.disconnect()
        await self.start_api()
        await self.connect_workers()
        recovered = await self.claim(self.workers[1], session)
        self.assertTrue(recovered['recovered'])
        self.assertEqual(recovered['jobId'], first[1]['jobId'])
        # Duplicate delivery after restart ACKs the already committed result.
        duplicate = await self.http.post(f"/api/jobs/{first[0]['jobId']}/report-result", headers={
            'X-VAHAN-RUNNER-TOKEN': settings.runner_token, 'X-VAHAN-RUNNER-ID': self.workers[0]},
            json=command.model_dump(mode='json', by_alias=True))
        self.assertEqual(duplicate.status_code, 200, duplicate.text)
        await queue.set_status(session, self.owner, 'PAUSED')
        self.assertEqual((await self.claim(self.workers[0], session))['type'], 'paused')
        await self.no_data(first[1], self.workers[1]); await self.no_data(first[2], self.workers[2])
        self.assertEqual(sum(task['status'] == 'NO_DATA' for task in (await queue.snapshot(session, self.owner))['tasks']), 3)
        await queue.set_status(session, self.owner, 'RUNNING')
        for _ in range(3):
            items = await asyncio.gather(*(self.claim(worker, session) for worker in self.workers))
            for item, worker in zip(items, self.workers):
                if item['type'] == 'assigned':
                    await self.no_data(item, worker)
            if (await queue.snapshot(session, self.owner))['retry']['complete']:
                break
        snapshot = await queue.snapshot(session, self.owner)
        self.assertTrue(all(task['status'] == 'NO_DATA' and task['attempts'] == 1 for task in snapshot['tasks']))
        self.assertEqual(len({task['jobId'] for task in snapshot['tasks']}), 9)
        async with engine.connect() as connection:
            self.assertEqual(await connection.scalar(select(func.count()).select_from(db.jobs)), 9)
            self.assertEqual(await connection.scalar(select(func.count()).select_from(db.report_update_history)), 9)
        print('Real HTTP + Socket.IO: API kill/restart, recovered jobId, duplicate result, pause/resume, 9/9 unique durable cases.')

    async def test_current_web_ui_socket_smoke_preserves_assignment_and_status_checks(self):
        runner_id = 'lifecycle-smoke'
        observed = [{**seed, 'found': True, 'count': 1, 'inputType': 'text', 'matchedBy': 'selector'} for seed in ui_contract.SEEDS]
        validation = await ui_contract.evaluate({'status': 'PASS', 'observedControls': observed}, runner_id)
        async with engine.begin() as connection:
            await connection.execute(insert(db.ui_preflight_checks).values(id=str(uuid4()), owner_username=self.owner,
                runner_ids=[runner_id], version_id=validation['versionId'], status='PASS', reports=[validation], created_at=now()))
        script = root.parent / 'web-ui/scripts/smoke-ui.mjs'
        process = await asyncio.create_subprocess_exec('node', str(script), cwd=script.parent.parent,
            env={**os.environ, 'VITE_API_URL': self.origin, 'VAHAN_SMOKE_RUNNER_ID': runner_id},
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=30)
        self.assertEqual(process.returncode, 0, stderr.decode(errors='replace'))
        self.assertIn('Web UI flow verified for job:', stdout.decode())
        jobs = await services.jobs.list_all(self.owner)
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].status, JobStatus.CANCELLED)


if __name__ == '__main__':
    unittest.main(verbosity=2)

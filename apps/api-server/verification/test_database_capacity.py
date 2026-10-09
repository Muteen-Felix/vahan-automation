"""Exercise real PostgreSQL limits/rollback/pagination in a disposable *_test DB."""
import asyncio, json, os, subprocess, sys, unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4
from unittest.mock import patch
from sqlalchemy.engine import make_url

name=os.environ.get('VAHAN_CAPACITY_TEST_DATABASE','')
if not name.startswith('vahan_capacity_') or not name.endswith('_test') or not name.replace('_','').isalnum():
    raise RuntimeError('Use a disposable vahan_capacity_*_test DB.')
os.environ['DATABASE_URL']=make_url(os.environ['DATABASE_URL']).set(database=name).render_as_string(hide_password=False)
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
subprocess.run([sys.executable,'-m','app.migrate'],check=True)

import httpx
from sqlalchemy import insert, select, delete, text
from sqlalchemy.exc import DBAPIError, TimeoutError as PoolTimeout
from starlette.requests import Request
from app.config import settings
from app.db import engine, schema as db
from app.db.pressure import pressure_code, bulk_operation, DatabaseBusy
from app.models.job import Job, JobStatus
from app.repositories.postgres import PostgresJobRepository, job_event_document, now
from app.repositories.report_sessions import read_sessions
from app.api.health import database_status
from app.main import fastapi_app
from app.services import services


class DatabaseCapacity(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await engine.dispose()
        self.session=str(uuid4()); self.owner='capacity-fixture';self.key='capacity-'+self.session
        await services.users.bootstrap(self.owner,'capacity-fixture-password')
        async with engine.begin() as c:
            await c.execute(insert(db.report_sessions).values(id=self.session,owner_username=self.owner,created_at=now()))

    async def asyncTearDown(self):
        async with engine.begin() as c:
            await c.execute(delete(db.jobs).where(db.jobs.c.session_id==self.session))
            await c.execute(delete(db.report_sessions).where(db.report_sessions.c.id==self.session))
            await c.execute(delete(db.app_settings).where(db.app_settings.c.key==self.key))
        await engine.dispose()

    async def test_summary_and_case_pages_do_not_transfer_old_embedded_images(self):
        stamp=datetime(2026,1,1,tzinfo=timezone.utc);items=[]
        for number in range(2500):
            identity=str(uuid4())
            items.append(dict(id=identity,owner_username=self.owner,session_id=self.session,runner_id='capacity-runner',
                status='COMPLETED',case_id=identity,source='new',scenario_name=f'Fixture {number}',filters={'states':['ASSAM'],'rtos':['AS27']},
                payload={'error':None,'captcha_image_data_url':'data:image/png;base64,'+'A'*50000},
                created_at=stamp+timedelta(seconds=number),updated_at=stamp+timedelta(seconds=number)))
        async with engine.begin() as c:
            for start in range(0,len(items),500):await c.execute(insert(db.jobs),items[start:start+500])
        summaries=await read_sessions(self.owner)
        result=next(row for row in summaries if row['sessionId']==self.session)
        self.assertEqual((result['jobCount'],result['completedCount'],result['jobs']),(2500,2500,[]))
        self.assertLess(len(json.dumps(result)),1500)
        detail=(await read_sessions(self.owner,session_id=self.session,job_offset=100,job_limit=100))[0]
        self.assertEqual(len(detail['jobs']),100);self.assertTrue(detail['hasMore'])
        self.assertEqual(detail['jobs'][0]['scenarioName'],'Fixture 100')
        self.assertNotIn('data:image',json.dumps(detail))
        self.assertEqual(await read_sessions('another-user',session_id=self.session),[])
        from app.db.read_cache import invalidate_report_sessions
        from app.repositories import report_sessions
        invalidate_report_sessions()
        with patch.object(report_sessions,'_fetch_summaries',wraps=report_sessions._fetch_summaries) as reads:
            results=await asyncio.gather(*(read_sessions(self.owner) for _ in range(20)))
            self.assertEqual(reads.call_count,1,'Concurrent identical lists share one SQL read')
        self.assertTrue(all(any(r['sessionId']==self.session for r in response) for response in results))
        print(f'capacity: 2,500 legacy-image jobs -> {len(json.dumps(result))} summary bytes; 20 concurrent reads passed')

    async def test_new_jobs_keep_relational_keys_and_compact_audit_events(self):
        job=Job(runnerId='capacity-runner',sessionId=self.session,ownerUsername=self.owner,
            filters={},scenarioName='Fixture',status=JobStatus.ASSIGNED)
        await PostgresJobRepository().create(job)
        job=await PostgresJobRepository().update_status(job.id,JobStatus.OPENING_VAHAN)
        async with engine.connect() as c:
            row=(await c.execute(select(db.jobs).where(db.jobs.c.id==str(job.id)))).mappings().one()
            event=await c.scalar(select(db.job_events.c.payload).where(db.job_events.c.job_id==str(job.id),db.job_events.c.event=='updated'))
        self.assertEqual(row['case_id'],str(job.id));self.assertEqual(row['scenario_name'],'Fixture')
        self.assertEqual(event['payloadVersion'],2);self.assertEqual(event['status'],'OPENING_VAHAN')
        self.assertNotIn('filters',event);self.assertNotIn('captchaImageDataUrl',event)
        job.filter_execution={'filled':{'proof':'kept'}}
        self.assertIn('filterExecution',job_event_document(job,'filters-verified'))
        self.assertNotIn('filterExecution',job_event_document(job,'updated'))

    async def test_pool_exhaustion_returns_retryable_503_and_recovers(self):
        held=[]
        try:
            for _ in range(settings.db_pool_size+settings.db_max_overflow):held.append(await engine.connect())
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=fastapi_app),base_url='http://test') as client:
                response=await client.get('/api/ready',headers={'Origin':'http://127.0.0.1:5173'})
                self.assertEqual(response.status_code,503)
                self.assertEqual(response.headers['retry-after'],'3')
                self.assertEqual(response.headers['access-control-allow-origin'],'http://127.0.0.1:5173')
                self.assertEqual(response.json()['code'],'DATABASE_BUSY')
        finally:
            for connection in held:await connection.close()
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=fastapi_app),base_url='http://test') as client:
            self.assertEqual((await client.get('/api/ready')).status_code,200)

    async def test_statement_timeout_rolls_back_write_and_releases_connection(self):
        with self.assertRaises(DBAPIError) as error:
            async with engine.begin() as c:
                await c.execute(insert(db.app_settings).values(key=self.key,value={'committed':False}))
                await c.execute(text("SET LOCAL statement_timeout='20ms'"))
                await c.execute(text('SELECT pg_sleep(0.2)'))
        self.assertEqual(pressure_code(error.exception),'DATABASE_TEMPORARILY_UNAVAILABLE')
        async with engine.connect() as c:
            self.assertIsNone(await c.scalar(select(db.app_settings.c.value).where(db.app_settings.c.key==self.key)))

    async def test_row_lock_timeout_does_not_overwrite_other_transaction(self):
        async with engine.begin() as c:await c.execute(insert(db.app_settings).values(key=self.key,value={'original':True}))
        async with engine.begin() as held:
            await held.execute(select(db.app_settings).where(db.app_settings.c.key==self.key).with_for_update())
            with self.assertRaises(DBAPIError) as error:
                async with engine.begin() as waiting:
                    await waiting.execute(text("SET LOCAL lock_timeout='50ms'"))
                    await waiting.execute(text("UPDATE app_settings SET value='{}'::jsonb WHERE key=:key"),{'key':self.key})
            self.assertEqual(pressure_code(error.exception),'DATABASE_TEMPORARILY_UNAVAILABLE')
        async with engine.connect() as c:self.assertEqual(await c.scalar(select(db.app_settings.c.value).where(db.app_settings.c.key==self.key)),{'original':True})

    async def test_heavy_operations_are_bounded(self):
        import app.db.pressure as pressure
        with patch.object(pressure,'_bulk_slots',asyncio.Semaphore(2)):
            async with bulk_operation():
                async with bulk_operation():
                    with self.assertRaises(DatabaseBusy):
                        async with bulk_operation():pass
            async with bulk_operation():pass

    async def test_runtime_role_can_write_data_but_cannot_change_schema(self):
        from sqlalchemy.ext.asyncio import create_async_engine
        from sqlalchemy.pool import NullPool
        from app.db.provision import provision
        from app.config import settings
        role='vahan_capacity_runtime_test';password='capacity_fixture_only_'+('A'*40)
        async with engine.connect() as c:
            self.assertIsNone(await c.scalar(text('SELECT 1 FROM pg_roles WHERE rolname=:role'),{'role':role}))
        with patch.dict(os.environ,{'DB_APP_USERNAME':role,'DB_APP_PASSWORD':password}):
            await provision()
        runtime=create_async_engine(make_url(settings.database_url).set(username=role,password=password),poolclass=NullPool)
        try:
            async with runtime.connect() as c:
                values=(await c.execute(text("SELECT has_schema_privilege(current_user,'public','CREATE'), has_table_privilege(current_user,'jobs','INSERT'), has_table_privilege(current_user,'alembic_version','UPDATE')"))).one()
                self.assertEqual(tuple(values),(False,True,False))
                await c.execute(insert(db.app_settings).values(key=self.key,value={'runtime':True}))
                await c.rollback()
                with self.assertRaises(DBAPIError):await c.execute(text('CREATE TABLE capacity_forbidden_ddl (id integer)'))
        finally:
            await runtime.dispose()
            async with engine.begin() as c:
                await c.execute(text(f'DROP OWNED BY {role}'))
                await c.execute(text(f'ALTER DEFAULT PRIVILEGES FOR ROLE vahan IN SCHEMA public REVOKE SELECT,INSERT,UPDATE,DELETE ON TABLES FROM {role}'))
                await c.execute(text(f'ALTER DEFAULT PRIVILEGES FOR ROLE vahan IN SCHEMA public REVOKE USAGE,SELECT ON SEQUENCES FROM {role}'))
                await c.execute(text(f'DROP ROLE {role}'))

    async def test_temporary_export_is_deleted_when_send_fails(self):
        import tempfile
        from app.api.annual_reports import TemporaryWorkbookResponse
        descriptor,path=tempfile.mkstemp(prefix='capacity-export-',suffix='.xlsx')
        os.close(descriptor);Path(path).write_bytes(b'fixture')
        async def receive():return {'type':'http.request','body':b''}
        async def send(_message):raise RuntimeError('fixture connection closed')
        response=TemporaryWorkbookResponse(path)
        with self.assertRaisesRegex(RuntimeError,'fixture connection closed'):
            await response({'type':'http','method':'GET','headers':[],'extensions':{}},receive,send)
        self.assertFalse(Path(path).exists())

    async def test_monitoring_and_indexes_are_available(self):
        request=Request({'type':'http','headers':[]});request.state.authenticated_role='admin'
        stats=await database_status(request)
        self.assertIn('checkedOut',stats['pool']);self.assertGreater(stats['bytes'],0)
        async with engine.connect() as c:
            self.assertEqual(await c.scalar(text("SELECT count(*) FROM pg_index WHERE NOT indisvalid AND indrelid IN ('jobs'::regclass,'main_reports'::regclass)")),0)
            self.assertEqual(await c.scalar(text("SELECT count(*) FROM pg_indexes WHERE indexname IN ('ix_jobs_active','ix_queue_session_status_position','ix_main_reports_scope_year_order','ix_jobs_retry_of')")),4)


if __name__=='__main__':unittest.main(verbosity=2)

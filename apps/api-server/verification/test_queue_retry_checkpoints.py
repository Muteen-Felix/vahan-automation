"""Checkpoint/final recovery in an explicitly disposable PostgreSQL database."""
import asyncio,os,sys,unittest
from pathlib import Path
from uuid import UUID,uuid4
from unittest.mock import AsyncMock,patch
from sqlalchemy.engine import make_url

name=os.environ.get('VAHAN_QUEUE_TEST_DATABASE','')
if not name.startswith('vahan_queue_') or not name.endswith('_test'):
    raise RuntimeError('Use a disposable vahan_queue_*_test database.')
os.environ['DATABASE_URL']=make_url(os.environ['DATABASE_URL']).set(database=name).render_as_string(hide_password=False)
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from sqlalchemy import delete,func,insert,select,update
from starlette.requests import Request
from fastapi import HTTPException
from app.db import engine,schema as db
from app.models.job import Job,JobStatus
from app.repositories.postgres import job_document,release_runner,now
from app.repositories.batch_queue import BatchQueueRepository,RETRY_KEY
from app.api.batch_queue import QueueTaskInput,ClaimInput,claim_task
from app.repositories import ui_contract
from app.services import services

class RetryCheckpoints(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await engine.dispose()
        async with engine.begin() as c:
            await c.run_sync(db.metadata.drop_all);await c.run_sync(db.metadata.create_all)
            await c.execute(insert(db.users).values(username='queue-test',password_hash='fixture',role='admin',active=True,profile={},created_at=now()))
        for number in range(1,4):
            await services.runners.register(runner_id=f'playwright-{number}',name=f'Worker {number}',socket_id=f'fixture-{number}')
        self.repo=BatchQueueRepository();self.owner='queue-test';self.assignments=[]
    async def asyncTearDown(self):await engine.dispose()
    async def start(self,count):
        session=uuid4();tasks=[QueueTaskInput(name=f'Case {i}',filters={'states':['State'],'rtos':[f'Office {i}'],'fromYear':'2025','toYear':'2025','categoryGroups':['Two Wheeler'],'fuels':['PURE EV']}) for i in range(count)]
        await self.repo.start(session,self.owner,tasks,3)
        return session,tasks
    async def finish(self,item,status,error=None):
        async with engine.begin() as c:
            job=Job.model_validate(await c.scalar(select(db.jobs.c.payload).where(db.jobs.c.id==item['jobId'])))
            job.status=status;job.error=(error or f'Failure at {job.scenario_name}') if status==JobStatus.FAILED else None;job.touch()
            await c.execute(update(db.jobs).where(db.jobs.c.id==str(job.id)).values(status=status.value,payload=job_document(job),updated_at=now()))
            await release_runner(c,job.runner_id,job.id)
        return await self.repo.settle(UUID(item['task']['sessionId']) if 'sessionId' in item['task'] else self.session,self.owner,item['task']['position'])
    async def claim(self,worker):
        item=await self.repo.claim(self.session,self.owner,f'playwright-{worker}')
        if item['type']=='assigned':self.assignments.append((item['task']['position'],item['task']['attempts'],item.get('retry',{}).get('phase'),worker))
        return item
    async def test_group_barrier_final_scan_distribution_restart_and_no_data(self):
        self.session,tasks=await self.start(23)
        first=await asyncio.gather(*(self.claim(i) for i in (1,2,3)))
        first=sorted(first,key=lambda item:item['task']['position'])
        self.assertEqual([item['task']['position'] for item in first],[0,1,2])
        fast=int(first[0]['task']['runnerId'].split('-')[-1])
        await self.finish(first[0],JobStatus.COMPLETED)
        for position in range(3,10):
            item=await self.claim(fast);self.assertEqual(item['task']['position'],position)
            await self.finish(item,JobStatus.FAILED if position==6 else JobStatus.COMPLETED)
        waiting=await self.claim(fast);self.assertEqual(waiting['type'],'waiting');self.assertEqual(waiting['retry']['checkpointEnd'],10)
        await self.finish(first[1],JobStatus.FAILED);await self.finish(first[2],JobStatus.NO_DATA)
        retries=await asyncio.gather(*(self.claim(i) for i in (1,2,3)))
        idle=next(i+1 for i,item in enumerate(retries) if item['type']=='waiting')
        retry=[item for item in retries if item['type']=='assigned']
        self.assertEqual({item['task']['position'] for item in retry},{1,6})
        for item in retry:self.assertEqual(item['task']['attempts'],2);self.assertEqual(item['retry']['phase'],'CHECKPOINT')
        bad=next(item for item in retry if item['task']['position']==1);good=next(item for item in retry if item['task']['position']==6)
        settled=await self.finish(bad,JobStatus.FAILED);self.assertTrue(settled['recoveryPending'])
        self.assertEqual((await self.claim(idle))['type'],'waiting','case 11 cannot start until every checkpoint retry ends')
        await self.finish(good,JobStatus.COMPLETED)
        while True:
            snapshot=await self.repo.snapshot(self.session,self.owner)
            if snapshot['retry']['phase']=='FINAL':break
            issued=await asyncio.gather(*(self.claim(i) for i in (1,2,3)))
            for item in issued:
                if item['type']=='assigned':
                    position=item['task']['position']
                    await self.finish(item,JobStatus.FAILED if position in {11,21} else JobStatus.NO_DATA if position==22 else JobStatus.COMPLETED)
        self.assertEqual(snapshot['retry']['pendingRetries'],3)
        self.assertEqual([item['position'] for item in snapshot['tasks'] if item['status']=='PENDING'],[1,11,21])
        self.repo=BatchQueueRepository() # All stage state survives a new process/repository.
        await self.repo.set_status(self.session,self.owner,'PAUSED')
        self.assertEqual((await self.claim(1))['type'],'paused')
        self.assertEqual((await self.repo.snapshot(self.session,self.owner))['retry']['phase'],'FINAL')
        await self.repo.set_status(self.session,self.owner,'RUNNING')
        final=await asyncio.gather(*(self.claim(i) for i in (1,2,3)))
        self.assertEqual({item['task']['position'] for item in final},{1,11,21})
        self.assertEqual(len({item['task']['runnerId'] for item in final}),3,'the final failed set is shared across workers')
        for item in final:
            self.assertEqual(item['task']['attempts'],3)
            async with engine.connect() as c:
                job=Job.model_validate(await c.scalar(select(db.jobs.c.payload).where(db.jobs.c.id==item['jobId'])))
            self.assertEqual(job.filters,tasks[item['task']['position']].filters)
            self.assertIsNotNone(job.retry_of_job_id);self.assertIsNotNone(job.case_id)
            await self.finish(item,JobStatus.FAILED if item['task']['position']==21 else JobStatus.NO_DATA if item['task']['position']==11 else JobStatus.COMPLETED)
        snapshot=await self.repo.snapshot(self.session,self.owner)
        self.assertEqual(snapshot['retry']['phase'],'DONE');self.assertEqual(snapshot['retry']['failedRemaining'],1)
        self.assertEqual(snapshot['tasks'][2]['attempts'],1);self.assertEqual(snapshot['tasks'][22]['attempts'],1)
        self.assertEqual(snapshot['tasks'][21]['status'],'FAILED');self.assertIn('Failure',snapshot['tasks'][21]['error'])
        for _ in range(3):self.assertEqual((await self.claim(1))['type'],'done')
        async with engine.connect() as c:self.assertEqual(await c.scalar(select(func.count()).select_from(db.jobs)),30)
        last=self.assignments
        self.assertLess(max(i for i,row in enumerate(last) if row[0] in {1,6} and row[1]==2),next(i for i,row in enumerate(last) if row[0]==10))
        self.assertTrue(any(row[2]=='CHECKPOINT' and row[0]==21 for row in last),'the final partial group is checked too')
    async def test_cancelled_final_retry_does_not_lose_case_or_reset_failure_history(self):
        self.session,_=await self.start(1)
        for worker in (1,2):await self.finish(await self.claim(worker),JobStatus.FAILED)
        await self.repo.snapshot(self.session,self.owner)
        item=await self.claim(3);cancelled=await self.finish(item,JobStatus.CANCELLED)
        self.assertEqual(cancelled['status'],'PENDING');self.assertEqual(cancelled['failures'],2);self.assertIn('Failure',cancelled['error'])
        await self.repo.set_status(self.session,self.owner,'PAUSED');await self.repo.set_status(self.session,self.owner,'RUNNING',2)
        item=await self.claim(1);self.assertEqual(item['task']['attempts'],4)
        await self.finish(item,JobStatus.COMPLETED)
        self.assertTrue((await self.repo.snapshot(self.session,self.owner))['retry']['complete'])
    async def test_final_recovery_cannot_bypass_sql_dom_gate(self):
        self.session,_=await self.start(1)
        observed=[{**seed,'found':True,'count':1,'inputType':'text','name':seed['field'],'label':seed['field'],'optionsHash':'fixture'} for seed in ui_contract.SEEDS]
        valid=await ui_contract.evaluate({'status':'PASS','observedControls':observed},'playwright-1')
        gate=str(uuid4())
        async with engine.begin() as c:
            await c.execute(insert(db.ui_preflight_checks).values(id=gate,owner_username=self.owner,runner_ids=['playwright-1','playwright-2','playwright-3'],version_id=valid['versionId'],status='PASS',reports=[valid],created_at=now()))
        await ui_contract.bind_gate(self.session,gate)
        for worker in (1,2):await self.finish(await self.claim(worker),JobStatus.FAILED)
        async with engine.begin() as c:
            state=await c.scalar(select(db.app_settings.c.value).where(db.app_settings.c.key==ui_contract.ACTIVE_KEY))
            await c.execute(update(db.app_settings).where(db.app_settings.c.key==ui_contract.ACTIVE_KEY).values(value={**state,'blocked':True}))
        request=Request({'type':'http','headers':[]});request.state.authenticated_user=self.owner
        with self.assertRaises(HTTPException):await claim_task(self.session,ClaimInput(runnerId='playwright-1'),request)
        async with engine.connect() as c:self.assertEqual(await c.scalar(select(func.count()).select_from(db.jobs)),2)
        async with engine.begin() as c:await c.execute(update(db.app_settings).where(db.app_settings.c.key==ui_contract.ACTIVE_KEY).values(value={**state,'blocked':False}))
        with patch('app.api.batch_queue.sio.emit',AsyncMock()):item=await claim_task(self.session,ClaimInput(runnerId='playwright-1'),request)
        self.assertEqual(item['task']['attempts'],3)
    async def test_concurrent_workers_claim_each_case_once_across_many_checkpoints(self):
        self.session,_=await self.start(120)
        seen=set();counts={1:0,2:0,3:0}
        async def consume(worker):
            while True:
                item=await self.claim(worker)
                if item['type']=='done':return
                if item['type']=='waiting':await asyncio.sleep(.001);continue
                self.assertEqual(item['type'],'assigned')
                position=item['task']['position'];self.assertNotIn(position,seen);seen.add(position);counts[worker]+=1
                await asyncio.sleep(.01 if worker==3 else .001)
                await self.finish(item,JobStatus.NO_DATA if position%7==0 else JobStatus.COMPLETED)
        await asyncio.gather(*(consume(worker) for worker in (1,2,3)))
        snapshot=await self.repo.snapshot(self.session,self.owner)
        self.assertEqual(len(seen),120);self.assertTrue(snapshot['retry']['complete'])
        self.assertTrue(all(task['attempts']==1 for task in snapshot['tasks']))
        self.assertTrue(all(counts.values()))
        async with engine.connect() as c:self.assertEqual(await c.scalar(select(func.count()).select_from(db.jobs)),120)

    async def test_validation_stop_is_excluded_from_checkpoint_and_final_recovery(self):
        self.session,_=await self.start(2)
        blocked=await self.claim(1)
        stopped=await self.finish(blocked,JobStatus.FAILED,'CAPTCHA_REFRESH_LIMIT: operator review required')
        self.assertEqual(stopped['status'],'FAILED');self.assertEqual(stopped['failures'],1)
        self.assertTrue(stopped['requiresOperator']);self.assertFalse(stopped['recoveryPending'])
        normal=await self.claim(2);self.assertEqual(normal['task']['position'],1)
        await self.finish(normal,JobStatus.FAILED)
        checkpoint=await self.claim(3);self.assertEqual(checkpoint['task']['position'],1)
        self.assertEqual(checkpoint['task']['attempts'],2)
        await self.finish(checkpoint,JobStatus.FAILED)
        final=await self.claim(1);self.assertEqual(final['task']['position'],1)
        self.assertEqual(final['task']['attempts'],3)
        await self.finish(final,JobStatus.COMPLETED)
        self.repo=BatchQueueRepository()
        snapshot=await self.repo.snapshot(self.session,self.owner)
        self.assertTrue(snapshot['retry']['complete']);self.assertEqual(snapshot['retry']['failedRemaining'],1)
        self.assertEqual(snapshot['tasks'][0]['attempts'],1)
        self.assertEqual(snapshot['tasks'][0]['status'],'FAILED')
        self.assertFalse(await self.repo.needs_work(self.session,self.owner))
        for worker in (1,2,3):self.assertEqual((await self.claim(worker))['type'],'done')
        async with engine.connect() as c:self.assertEqual(await c.scalar(select(func.count()).select_from(db.jobs)),4)

    async def test_operator_only_queue_finishes_with_a_visible_error(self):
        self.session,_=await self.start(1)
        await self.finish(await self.claim(1),JobStatus.FAILED,'CAPTCHA_WAIT_TIMEOUT: operator review required')
        snapshot=await self.repo.snapshot(self.session,self.owner)
        self.assertEqual(snapshot['retry']['phase'],'DONE')
        self.assertEqual(snapshot['retry']['failedRemaining'],1)
        self.assertFalse(await self.repo.needs_work(self.session,self.owner))
        for worker in (1,2,3):self.assertEqual((await self.claim(worker))['type'],'done')

    async def test_old_pending_final_target_cannot_reopen_an_operator_stop(self):
        self.session,_=await self.start(1)
        await self.finish(await self.claim(1),JobStatus.FAILED,'CAPTCHA_REJECTION_LIMIT: operator review required')
        async with engine.begin() as c:
            policy=await c.scalar(select(db.app_settings.c.value).where(db.app_settings.c.key==RETRY_KEY+str(self.session)))
            await c.execute(update(db.app_settings).where(db.app_settings.c.key==RETRY_KEY+str(self.session)).values(
                value={**policy,'phase':'FINAL','finalPassStarted':True,'finalTargets':[0]}))
            await c.execute(update(db.batch_queue_tasks).where(db.batch_queue_tasks.c.session_id==str(self.session)).values(status='PENDING'))
        self.repo=BatchQueueRepository()
        self.assertEqual((await self.claim(1))['type'],'done')
        snapshot=await self.repo.snapshot(self.session,self.owner)
        self.assertEqual(snapshot['tasks'][0]['status'],'FAILED')
        self.assertEqual(snapshot['tasks'][0]['attempts'],1)
        self.assertEqual(snapshot['tasks'][0]['failures'],1)

    async def test_explicit_successful_retry_can_reconcile_a_stopped_case(self):
        self.session,tasks=await self.start(1)
        original=await self.claim(1)
        await self.finish(original,JobStatus.FAILED,'CAPTCHA_WAIT_TIMEOUT: operator review required')
        self.assertEqual((await self.claim(2))['type'],'done')
        # Simulate the durable successful outcome of an explicit operator retry,
        # not an automatic claim or a real CAPTCHA submission.
        retry=Job(runnerId='playwright-2',sessionId=self.session,ownerUsername=self.owner,
                  filters=tasks[0].filters,scenarioName=tasks[0].name,
                  retryOfJobId=UUID(original['jobId']),status=JobStatus.COMPLETED)
        await services.jobs.create(retry)
        snapshot=await self.repo.snapshot(self.session,self.owner)
        recovered=snapshot['tasks'][0]
        self.assertEqual(recovered['status'],'COMPLETED');self.assertEqual(recovered['attempts'],2)
        self.assertFalse(recovered['requiresOperator']);self.assertIsNone(recovered['error'])
        self.assertEqual(snapshot['retry']['failedRemaining'],0)
        self.assertEqual((await self.claim(3))['type'],'done')

    async def test_completed_historical_queue_is_not_reopened_by_read(self):
        self.session,_=await self.start(1)
        for worker in (1,2,3):await self.finish(await self.claim(worker),JobStatus.FAILED)
        async with engine.begin() as c:await c.execute(delete(db.app_settings).where(db.app_settings.c.key==RETRY_KEY+str(self.session)))
        snapshot=await self.repo.snapshot(self.session,self.owner)
        self.assertEqual(snapshot['tasks'][0]['status'],'FAILED');self.assertIsNone(snapshot['retry'])
        self.assertEqual((await self.claim(1))['type'],'done')

if __name__=='__main__':unittest.main(verbosity=2)

"""Daily update coverage against a guarded disposable PostgreSQL database."""
import unittest
from datetime import datetime,timezone
from uuid import uuid4
import test_report_results as fixture
from sqlalchemy import delete,insert,update
from app.db import engine,schema as db
from app.models.job import Job,JobStatus
from app.api.batch_queue import QueueTaskInput
from app.repositories.batch_queue import BatchQueueRepository
from app.repositories.annual_reports import dataset
from app.services import services
from app.api.update_status import summarize,update_status

class UpdateStatusTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await engine.dispose();self.owner='status-'+str(uuid4());self.session=uuid4();self.jobs=[]
        await services.users.bootstrap(self.owner,'fixture-password-long')
        self.filters=[{'states':['State A'],'rtos':[f'Office {i}'],'fromYear':'2023','toYear':'2023',
                      'yAxis':'Maker','xAxis':'Month Wise','period':'CALENDAR YEAR'} for i in (1,2)]
        self.scope=dataset(self.owner,self.filters[0])
        await BatchQueueRepository().start(self.session,self.owner,[QueueTaskInput(name=f'Office {i+1}',filters=f) for i,f in enumerate(self.filters)],2)
        async with engine.begin() as c:
            await c.execute(update(db.batch_queue_tasks).where(db.batch_queue_tasks.c.session_id==str(self.session)).values(updated_at=datetime(2026,10,6,8,tzinfo=timezone.utc)))
    async def asyncTearDown(self):
        async with engine.begin() as c:
            await c.execute(delete(db.report_update_history).where(db.report_update_history.c.owner_key==self.owner))
            await c.execute(delete(db.batch_queue_tasks).where(db.batch_queue_tasks.c.session_id==str(self.session)))
            await c.execute(delete(db.batch_queue_sessions).where(db.batch_queue_sessions.c.session_id==str(self.session)))
            for job in self.jobs:await c.execute(delete(db.jobs).where(db.jobs.c.id==str(job.id)))
        await engine.dispose()
    async def proof(self,index,at,status='added',warnings=None):
        f=self.filters[index];job=await services.jobs.create(Job(runnerId='status-fixture',ownerUsername=self.owner,filters=f,status=JobStatus.COMPLETED));self.jobs.append(job)
        async with engine.begin() as c:
            await c.execute(insert(db.report_update_history).values(source_key='job:'+str(job.id),owner_key=self.owner,
                scope_key=self.scope['id'],scope_label=self.scope['label'],filters=f,job_id=str(job.id),name=f'Office {index+1}',status=status,
                years=[2023],states=['State A'],rtos=f['rtos'],details={'newCells':1,'issueCount':len(warnings or []),'warnings':warnings or []},imported_at=at,observed_at=at))
    async def test_partial_latest_day_is_not_reported_as_complete_and_retries_deduplicate(self):
        before=datetime(2026,10,6,8,tzinfo=timezone.utc);latest=datetime(2026,10,7,8,tzinfo=timezone.utc)
        await self.proof(0,before);await self.proof(1,before)
        await self.proof(0,latest);await self.proof(0,latest,status='unchanged')
        result=await update_status(2023,2026,self.scope['id']);item=next(i for i in result['datasets'] if i['year']==2023)
        self.assertEqual(item['latest']['date'],'2026-10-07');self.assertEqual(item['latest']['updatedCases'],1)
        self.assertEqual(item['latest']['totalCases'],2);self.assertEqual(item['latest']['percent'],50)
        self.assertEqual(item['latest']['firstNotUpdated']['rto'],'Office 2')
        self.assertEqual(item['days'][1]['state'],'complete')
    async def test_no_data_counts_but_review_does_not_and_dates_use_vietnam_timezone(self):
        at=datetime(2026,10,6,18,tzinfo=timezone.utc)
        await self.proof(0,at,status='no-data');await self.proof(1,at,status='review',warnings=['Missing manufacturer'])
        result=await update_status(2023,2026,self.scope['id']);latest=result['datasets'][0]['latest']
        self.assertEqual(latest['date'],'2026-10-07');self.assertEqual(latest['updatedCases'],1)
        self.assertEqual(latest['reviewCases'],1);self.assertNotEqual(latest['state'],'complete')
    async def test_no_plan_is_unknown_even_when_all_imports_saved(self):
        at=datetime(2026,10,7,8,tzinfo=timezone.utc)
        result=summarize([{'filters':self.filters[0],'scope_key':self.scope['id'],'scope_label':'Fixture','years':[2024],
            'saved_day':at.date(),'imported_at':at,'name':'Office 1','valid':True}],[],2023,2026)
        latest=result['datasets'][0]['latest'];self.assertIsNone(latest['totalCases']);self.assertEqual(latest['state'],'unknown')
if __name__=='__main__':unittest.main(verbosity=2)

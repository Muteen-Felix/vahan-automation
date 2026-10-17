"""Executed only inside the newly built old version; labelled upgrade fixtures, never D3 evidence."""
import asyncio, hashlib, json
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from sqlalchemy import insert, text, update
from app.db import engine, schema as db
from app.models.filter_profile import ProfileWrite
from app.models.run_schedule import RunScheduleCreate
from app.models.job import Job, JobStatus
from app.repositories.filter_profiles import FilterProfileRepository
from app.repositories.run_schedules import RunScheduleRepository, PREFIX
from app.repositories.postgres import PostgresJobRepository
from app.repositories.annual_reports import import_rows

async def main():
    stamp=datetime.now(timezone.utc)
    definition={'version':1,'report':{'year':2025},'fields':{k:{'mode':'fixed','values':[value]} for k,value in {'delhiNcr':'ALL STATES','states':'T45B SYNTHETIC STATE','rtos':'T45B SYNTHETIC RTO - ZZ01','archivedFlags':'ACTIVE_COMPLIANT'}.items()}}
    profile=await FilterProfileRepository().save('admin',ProfileWrite(name='T45B SYNTHETIC UPGRADE PROFILE',definition=definition))
    filters={'fromYear':'2025','toYear':'2025','states':['T45B SYNTHETIC STATE'],'rtos':['T45B SYNTHETIC RTO - ZZ01'],'categoryGroups':['Two Wheeler'],'fuels':['ELECTRIC(BOV)']}
    job=await PostgresJobRepository().create(Job(ownerUsername='admin',runnerId='T45B-SYNTHETIC-RUNNER',filters=filters,status=JobStatus.COMPLETED,scenario_name='T45B SYNTHETIC COMPLETED JOB'))
    sid=str(job.session_id)
    async with engine.begin() as c:
        await c.execute(insert(db.batch_queue_sessions).values(session_id=sid,owner_username='admin',status='PAUSED',total=1,max_workers=3,created_at=stamp,updated_at=stamp))
        await c.execute(insert(db.batch_queue_tasks).values(session_id=sid,position=0,scenario_name='T45B SYNTHETIC COMPLETED CASE',filters=filters,status='COMPLETED',attempts=1,failures=0,runner_id='T45B-SYNTHETIC-RUNNER',job_id=str(job.id),updated_at=stamp))
        rows=[{'sheet':'Sheet1','row_number':0,'cells':['Maker','2025-Jan','2025-Feb']}]+[{'sheet':'Sheet1','row_number':i,'cells':[f'T45B SYNTHETIC MAKER {i}',i*10,i*20]} for i in range(1,4)]
        await import_rows(c,source_key='T45B-SYNTHETIC-WORKBOOK',name='T45B SYNTHETIC WORKBOOK - NOT VAHAN',rows=rows,filters=filters,owner='admin',job_id=str(job.id),observed_at=stamp)
        content=b'T45B SYNTHETIC STORED FILE - NOT VAHAN'
        await c.execute(insert(db.stored_files).values(id=str(uuid4()),owner_username='admin',job_id=str(job.id),kind='excel',name='T45B-SYNTHETIC.txt',mime_type='text/plain',size=len(content),sha256=hashlib.sha256(content).hexdigest(),content=content,metadata={'scope':'UPGRADE FIXTURE ONLY'},created_at=stamp))
    schedules=[]
    for repeat in ('once','monthly','daily'):
        value=await RunScheduleRepository().create('admin',RunScheduleCreate(profileId=profile['id'],startsAt=stamp+timedelta(days=3),workerCount=3,year=2025,repeat=repeat))
        if repeat=='daily':
            async with engine.begin() as c:
                await c.execute(update(db.app_settings).where(db.app_settings.c.key==PREFIX+value['id']).values(value={**value,'lastSessionId':sid,'total':1,'done':1,'withData':1,'status':'WAITING'}))
        elif repeat=='once':
            async with engine.begin() as c:
                await c.execute(update(db.app_settings).where(db.app_settings.c.key==PREFIX+value['id']).values(value={**value,'workerCount':9999}))
        schedules.append({'id':value['id'],'repeat':repeat})
    print(json.dumps({'scope':'SYNTHETIC PERSISTENT UPGRADE DATA, NOT REAL VAHAN, NOT D3','profileId':profile['id'],'jobId':str(job.id),'sessionId':sid,'reportRows':3,'schedules':schedules,'savedLegacyWorkerCount':9999}))
    await engine.dispose()

asyncio.run(main())

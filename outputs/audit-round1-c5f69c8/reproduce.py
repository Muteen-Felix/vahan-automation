"""Audit probes against an isolated *_test database; no production changes."""
import asyncio, copy, json, sys
from datetime import timedelta
from pathlib import Path
from uuid import uuid4
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'apps/api-server'))
from sqlalchemy import insert, update, select
from app.db import engine, schema as db
from app.repositories import ui_contract
from app.repositories.postgres import now, runner_document
from app.repositories.batch_queue import BatchQueueRepository
from app.services import services
from app.api.batch_queue import QueueTaskInput
from app.worker_pool import apply_pool
def observation():
    return {'status':'PASS','observedControls':[{**seed,'found':True,'count':1,'name':seed['field'],'label':seed['field'],'matchedBy':'selector','inputType':'text'} for seed in ui_contract.SEEDS]}
async def main():
    owner='probe-admin';await services.users.bootstrap(owner,'probe-test-password')
    for name in ['bad-worker','good-worker']:
        await services.runners.register(runner_id=name,name=name,socket_id=name)
    version=await ui_contract.evaluate(observation(),'good-worker')
    gate=str(uuid4())
    async with engine.begin() as c:
        await c.execute(insert(db.ui_preflight_checks).values(id=gate,owner_username=owner,runner_ids=['good-worker'],version_id=version['versionId'],status='PASS',reports=[version],created_at=now()))
    broken=observation();broken['observedControls'][0]['found']=False
    await ui_contract.evaluate(broken,'bad-worker')
    before=await ui_contract.current();assert before['blocked']
    await services.runners.mark_reconnecting('bad-worker')
    during=await ui_contract.current();assert during['blocked']
    await services.runners.remove_by_socket('bad-worker')
    after=await ui_contract.current();assert not after['blocked']
    assert 'bad-worker' in after['runnerErrors']
    assert await ui_contract.require_gate(owner,['good-worker'],gate,fresh=True)==gate
    await services.runners.register(runner_id='bad-worker',name='bad',socket_id='bad-worker-reconnected')
    reconnect=await ui_contract.current();assert reconnect['blocked']
    print(json.dumps({'probe':'health','blockedBeforeDisconnect':before['blocked'],'blockedDuringGrace':during['blocked'],'blockedAfterOffline':after['blocked'],'errorRetained':'bad-worker' in after['runnerErrors'],'healthyRunnerOldGateAllowed':True,'blockedOnReconnect':reconnect['blocked']}))
    await ui_contract.evaluate(observation(),'bad-worker')
    await apply_pool(1);q=BatchQueueRepository();session=uuid4()
    await q.start(session,owner,[QueueTaskInput(name='One report',filters={'states':['Fixture'],'rtos':['Fixture Office']})],1)
    first=await q.claim(session,owner,'bad-worker')
    recovered=await q.claim(session,owner,'bad-worker')
    assert recovered['recovered'] and recovered['jobId']==first['jobId']
    await services.runners.remove_by_socket('bad-worker-reconnected')
    async with engine.begin() as c:
        payload=await c.scalar(select(db.runners.c.payload).where(db.runners.c.id=='bad-worker'))
        from app.models.runner import Runner
        runner=Runner.model_validate(payload);runner.last_seen_at=now()-timedelta(seconds=60)
        await c.execute(update(db.runners).where(db.runners.c.id=='bad-worker').values(payload=runner_document(runner)))
    snapshot=await q.snapshot(session,owner)
    previous=await services.jobs.get(first['job'].id)
    retry=await q.claim(session,owner,'good-worker')
    assert previous.status.value=='FAILED'
    assert retry['type']=='assigned' and retry['jobId']!=first['jobId']
    assert retry['job'].retry_of_job_id==first['job'].id
    assert retry['job'].case_id==first['job'].case_id
    assert retry['job'].filters==first['job'].filters
    print(json.dumps({'probe':'reclaim','lostResponseSameJob':True,'oldJobStatus':previous.status.value,'oldJobError':previous.error,'taskAfterSettlement':snapshot['tasks'][0]['status'],'failures':snapshot['tasks'][0]['failures'],'newWorker':retry['job'].runner_id,'newJob':True,'sameCaseId':True,'sameFilters':True}))
    from app.models.job import JobStatus
    await services.jobs.update_status(retry['job'].id,JobStatus.NO_DATA)
    await services.runners.release_job('good-worker',str(retry['job'].id))
    await q.set_status(session,owner,'PAUSED')
    await services.runners.register(runner_id='bad-worker',name='bad',socket_id='bad-worker-reconnected')
    await services.runners.register(runner_id='third-worker',name='third',socket_id='third-worker')
    from app.models.filter_profile import ProfileWrite
    from app.models.run_schedule import RunScheduleCreate
    from app.repositories.filter_profiles import FilterProfileRepository
    from app.repositories.run_schedules import RunScheduleRepository
    from app.run_scheduler import prepare_run
    profile=await FilterProfileRepository().save(owner,ProfileWrite.model_validate({'name':'Probe profile','definition':{'report':{'year':2026},'fields':{'delhiNcr':{'values':['ALL STATES']},'archivedFlags':{'values':['ACTIVE']},'states':{'values':['Fixture']},'rtos':{'values':['Fixture Office']}}}}))
    schedules=RunScheduleRepository()
    saved=await schedules.create(owner,RunScheduleCreate(profileId=profile['id'],startsAt=now()+timedelta(hours=1),workerCount=1,year=2026))
    saved=await schedules.patch(saved['id'],{'nextRunAt':(now()-timedelta(minutes=1)).isoformat()})
    value=await schedules.begin_run(saved['id'])
    value=await schedules.patch(saved['id'],{'tasks':[{'name':'Probe task','filters':{'states':['Fixture'],'rtos':['Fixture Office']}}]})
    selected=[];leases=[]
    async def checked(event,payload,**kwargs):
        worker={'bad-worker-reconnected':'bad-worker','good-worker':'good-worker','third-worker':'third-worker'}[kwargs['to']]
        selected.append(worker)
        async with engine.connect() as c:
            leases.append(len(list(await c.scalars(select(db.runner_planning_leases.c.runner_id).where(db.runner_planning_leases.c.expires_at>now())))))
        check=observation();check.update(checkId=payload['requestId'],checkedAt=now().isoformat(),trigger='preflight')
        check['contractValidation']=await ui_contract.evaluate(check,worker)
        return await services.ui_health_logs.append(check)
    with patch('app.api.ui_health.sio.call',side_effect=checked):
        await prepare_run(value)
    assert len(selected)==3 and max(leases)==1
    current=await schedules.get(saved['id']);assert current['status']=='RUNNING'
    snapshot=await q.snapshot(uuid4() if not current['sessionId'] else __import__('uuid').UUID(current['sessionId']),owner)
    assert snapshot['maxWorkers']==1
    print(json.dumps({'probe':'preflight','scheduleWorkerCount':1,'selectedWorkers':selected,'peakPlanningLeases':max(leases),'queueMaxWorkers':snapshot['maxWorkers'],'runStatus':current['status']}))
    await engine.dispose()
asyncio.run(main())

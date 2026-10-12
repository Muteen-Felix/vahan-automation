import asyncio, os, sys, json, time
from pathlib import Path
from unittest.mock import patch
root=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(root/'apps/api-server'),str(root/'apps/api-server/verification')]
import test_run_schedules as fixture
from app.db import engine
from app.run_scheduler import repository
async def run():
    case=fixture.RunScheduleTest('test_headless_checkpoints_final_sweep_and_resume_recover_all_failures')
    await case.asyncSetUp();original=fixture.scheduler_tick;number=0
    async def traced():
        nonlocal number
        await original();number+=1
        rows=await repository.list()
        for row in rows:
            if row['owner']=='schedule-test':
                print(json.dumps({'tick':number,'status':row['status'],'message':row.get('message'),'operation':row.get('operation'),'done':row.get('done'),'failed':row.get('failed'),'retry':row.get('retryProgress')}),flush=True)
    try:
        with patch.object(fixture,'scheduler_tick',traced):
            await case.test_headless_checkpoints_final_sweep_and_resume_recover_all_failures()
        print('PASS headless diagnostic, unchanged assertions',flush=True)
    except BaseException:
        print('FAIL headless diagnostic',flush=True);raise
    finally:await case.asyncTearDown()
asyncio.run(run())

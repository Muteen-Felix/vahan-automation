"""SQL contract updates and preflight gate; guarded disposable DB only."""
import unittest,asyncio,copy
from uuid import uuid4
from unittest.mock import patch
from sqlalchemy import delete,insert,select,func
from starlette.requests import Request
import test_report_results as fixture
from app.db import engine,schema as db
from app.repositories import ui_contract
from app.repositories.postgres import now
from app.api.ui_health import preflight,PreflightInput
from app.services import services
from fastapi import HTTPException


def observation():
    controls=[]
    for seed in ui_contract.SEEDS:
        controls.append({**seed,'found':True,'count':1,'tag':'button' if seed['tag']=='action' else seed['tag'],
            'name':seed['field'],'label':seed['field'],'matchedBy':'selector','inputType':'text' if seed['tag']=='input' else None,'optionsHash':'a'})
    return {'status':'PASS','observedControls':controls,'checkedAt':now().isoformat()}

class ContractTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await engine.dispose();self.owner='contract-'+str(uuid4())
        await services.users.bootstrap(self.owner,'fixture-password-long')
        async with engine.begin() as c:
            await c.execute(delete(db.ui_preflight_checks));await c.execute(delete(db.ui_contract_versions))
            await c.execute(delete(db.app_settings).where(db.app_settings.c.key==ui_contract.ACTIVE_KEY))
        self.runner='contract-runner-'+str(uuid4());await services.runners.register(runner_id=self.runner,name='Fixture',socket_id=self.runner)
    async def asyncTearDown(self):await engine.dispose()
    async def test_verified_selector_change_versions_sql_and_blocks_incompatible_change(self):
        first=await ui_contract.evaluate(observation(),self.runner);self.assertTrue(first['allowed'])
        changed=observation();state=next(c for c in changed['observedControls'] if c['field']=='states');state.update(selector='#newState',matchedBy='name')
        repaired=await ui_contract.evaluate(changed,self.runner);self.assertEqual(repaired['revision'],2);self.assertTrue(repaired['repairs'])
        broken=copy.deepcopy(changed);next(c for c in broken['observedControls'] if c['field']=='makers')['found']=False
        failure=await ui_contract.evaluate(broken,self.runner);self.assertFalse(failure['allowed'])
        current=await ui_contract.current();self.assertEqual(current['versionId'],repaired['versionId']);self.assertTrue(current['blocked'])
        async with engine.connect() as c:self.assertEqual(await c.scalar(select(func.count()).select_from(db.ui_contract_versions)),2)
    async def test_data_change_updates_sql_without_invalidating_selector_revision(self):
        first=await ui_contract.evaluate(observation(),self.runner)
        changed=observation();changed['observedControls'][0]['optionsHash']='b'
        result=await ui_contract.evaluate(changed,self.runner)
        self.assertEqual(result['versionId'],first['versionId']);self.assertEqual(result['status'],'DATA_CHANGED');self.assertTrue(result['allowed'])
        async with engine.connect() as c:
            version=await c.scalar(select(db.ui_contract_versions.c.controls).where(db.ui_contract_versions.c.id==first['versionId']))
        self.assertEqual(version[0]['optionsHash'],'a','historical version is immutable')
        self.assertEqual((await ui_contract.current())['controls'][0]['optionsHash'],'b')

    async def test_class_change_creates_version_without_overwriting_previous_dom(self):
        first=await ui_contract.evaluate(observation(),self.runner)
        changed=observation();changed['observedControls'][0]['className']='new-control'
        result=await ui_contract.evaluate(changed,self.runner)
        self.assertEqual(result['revision'],2)
        async with engine.connect() as c:
            original=await c.scalar(select(db.ui_contract_versions.c.controls).where(db.ui_contract_versions.c.id==first['versionId']))
        self.assertIsNone(original[0]['className'])

    async def test_other_worker_success_cannot_clear_failed_worker(self):
        await ui_contract.evaluate(observation(),self.runner)
        broken=observation();broken['observedControls'][0]['found']=False
        await ui_contract.evaluate(broken,self.runner)
        await ui_contract.evaluate(observation(),'another-worker')
        state=await ui_contract.current();self.assertTrue(state['blocked'])
        self.assertIn(self.runner,state['runnerErrors'])
        await ui_contract.evaluate(observation(),self.runner)
        self.assertFalse((await ui_contract.current())['blocked'])

    async def test_unverified_semantic_rename_is_blocked(self):
        await ui_contract.evaluate(observation(),self.runner)
        changed=observation();changed['observedControls'][0].update(selector='#impostor',matchedBy='name',name='other',label='other')
        self.assertFalse((await ui_contract.evaluate(changed,self.runner))['allowed'])

    async def test_disabled_worker_error_is_retained_without_blocking_selected_pool(self):
        from sqlalchemy.dialects.postgresql import insert as pg_insert
        async with engine.begin() as c:
            await c.execute(pg_insert(db.app_settings).values(key='docker-worker-pool',
                value={'desiredCount':1,'phase':'ready'}).on_conflict_do_update(
                index_elements=['key'],set_={'value':{'desiredCount':1,'phase':'ready'}}))
        try:
            broken=observation();broken['observedControls'][0]['found']=False
            await ui_contract.evaluate(broken,'playwright-2')
            await ui_contract.evaluate(observation(),'playwright-1')
            state=await ui_contract.current()
            self.assertFalse(state['blocked'])
            self.assertIn('playwright-2',state['runnerErrors'],'keep disabled-worker diagnostic')
            await ui_contract.evaluate(broken,'playwright-1')
            self.assertTrue((await ui_contract.current())['blocked'],'selected worker still blocks')
        finally:
            async with engine.begin() as c:
                await c.execute(delete(db.app_settings).where(db.app_settings.c.key=='docker-worker-pool'))
    async def test_api_rejects_queue_start_without_sql_preflight(self):
        from app.api.batch_queue import start_queue,StartQueueInput
        request=Request({'type':'http','headers':[]});request.state.authenticated_user=self.owner
        session=uuid4()
        command=StartQueueInput(sessionId=session,maxWorkers=1,tasks=[{'name':'Office','filters':{'states':['State A'],'rtos':['Office A'],'fromYear':'2026','toYear':'2026'}}])
        with self.assertRaises(HTTPException):await start_queue(command,request)
        async with engine.connect() as c:
            self.assertIsNone(await c.scalar(select(db.batch_queue_sessions.c.session_id).where(db.batch_queue_sessions.c.session_id==str(session))))
    async def test_preflight_requires_sql_evidence_and_gate_is_owner_bound(self):
        request=Request({'type':'http','headers':[]});request.state.authenticated_user=self.owner
        async def checked(event,payload,**kwargs):
            check=observation();check.update(checkId=payload['requestId'],trigger='preflight')
            validation=await ui_contract.evaluate(check,self.runner);check['contractValidation']=validation
            stored=await services.ui_health_logs.append(check)
            return {**stored,'validation':validation}
        with patch('app.api.ui_health.sio.call',side_effect=checked):result=await preflight(PreflightInput(runnerIds=[self.runner]),request)
        self.assertTrue(result['allowed']);await ui_contract.require_gate(self.owner,[self.runner],result['preflightId'],fresh=True)
        with self.assertRaises(ValueError):await ui_contract.require_gate('other',[self.runner],result['preflightId'],fresh=True)
        with patch('app.api.ui_health.sio.call',return_value={'ok':True,'validation':{'allowed':True}}):
            with self.assertRaises(HTTPException):await preflight(PreflightInput(runnerIds=[self.runner]),request)
        with self.assertRaises(ValueError):
            await ui_contract.require_gate(self.owner,[self.runner],result['preflightId'],fresh=True)

    async def test_sql_preflight_retries_once_and_persists_missing_worker(self):
        request=Request({'type':'http','headers':[]});request.state.authenticated_user=self.owner
        attempts=0
        async def checked(event,payload,**kwargs):
            nonlocal attempts
            attempts+=1
            if attempts==1:raise TimeoutError('fixture timeout')
            check=observation();check.update(checkId=payload['requestId'],trigger='preflight')
            check['contractValidation']=await ui_contract.evaluate(check,self.runner)
            return await services.ui_health_logs.append(check)
        with patch('app.api.ui_health.sio.call',side_effect=checked):
            result=await preflight(PreflightInput(runnerIds=[self.runner]),request)
        self.assertEqual(attempts,2);self.assertTrue(result['allowed'])
        self.assertEqual(result['reports'][0]['attempts'],2)
        with self.assertRaises(HTTPException) as error:
            await preflight(PreflightInput(runnerIds=['missing-worker']),request)
        async with engine.connect() as c:
            row=(await c.execute(select(db.ui_preflight_checks).where(db.ui_preflight_checks.c.id==error.exception.detail['diagnostics']['preflightId']))).mappings().one()
        self.assertEqual(row['status'],'BLOCKED')
        self.assertEqual(row['reports'][0]['reports'][0]['code'],'WORKER_NOT_REGISTERED')

    async def test_preview_gate_uses_owner_and_blocks_options_before_maker_loading(self):
        from app.api.filter_profiles import compile_profile_plan,load_options,OptionsInput,search_makers,MakerSearchInput
        from app.models.filter_profile import ProfileDefinition
        from contextlib import asynccontextmanager
        definition=ProfileDefinition.model_validate({'report':{'year':2026},'fields':{
            'states':{'mode':'iterate'},'rtos':{'mode':'iterate'},
            'archivedFlags':{'values':['ACTIVE_COMPLIANT']},'delhiNcr':{'values':['ALL STATES']}},'rules':[]})
        profile={'id':str(uuid4()),'revision':1,'name':'Fixture','definition':definition.model_dump(mode='json',by_alias=True)}
        @asynccontextmanager
        async def reservation(*args):
            yield 'fixture-socket','fixture-token'
        async def progress(message):pass
        with patch('app.repositories.ui_contract.require_gate') as gate,patch('app.api.filter_profiles.reserve_options_runner',reservation),patch('app.api.filter_profiles.renew_lease'),patch('app.api.filter_profiles.FilterPlanner.compile',return_value={'scenarios':[]}):
            plan=await compile_profile_plan(profile,self.runner,self.owner,2026,progress)
            self.assertEqual(plan['profileName'],'Fixture')
            gate.assert_awaited_once_with(self.owner,[self.runner],fresh=True)
        request=Request({'type':'http','headers':[]});request.state.authenticated_user=self.owner
        with patch('app.repositories.ui_contract.require_gate') as gate,patch('app.api.filter_profiles.reserve_options_runner',reservation),patch('app.api.filter_profiles.command',return_value=['Maker A']):
            values=await search_makers(MakerSearchInput(runnerId=self.runner,year=2026,search='Maker'),request)
            self.assertEqual(values,['Maker A'])
            gate.assert_awaited_once_with(self.owner,[self.runner],fresh=True)
        with patch('app.api.filter_profiles.reserve_options_runner',side_effect=AssertionError('must not load options')):
            with self.assertRaises(HTTPException):
                await load_options(OptionsInput(runnerId=self.runner,year=2026),request)
            with self.assertRaises(HTTPException):
                await search_makers(MakerSearchInput(runnerId=self.runner,year=2026,search='Maker'),request)

    async def test_failed_dom_evidence_is_saved_before_ui_notification(self):
        from app.api.ui_health import receive_ui_health_log
        from app.models.ui_health import UiHealthLogRequest
        request=Request({'type':'http','headers':[(b'x-vahan-runner-id',self.runner.encode())]})
        request.state.authenticated_runner=True
        check=observation();check['checkId']=str(uuid4())
        next(row for row in check['observedControls'] if row['field']=='makers')['found']=False
        async def published(event,payload,**kwargs):
            if event=='ui-health:blocked':
                async with engine.connect() as c:
                    saved=await c.scalar(select(db.ui_health_checks.c.payload).where(db.ui_health_checks.c.id==check['checkId']))
                self.assertIsNotNone(saved)
        with patch('app.api.ui_health.sio.emit',side_effect=published):
            response=await receive_ui_health_log(UiHealthLogRequest(runnerId=self.runner,healthCheck=check),request)
        self.assertFalse(response.validation['allowed'])
        state=await ui_contract.current();self.assertEqual(state['lastCheck']['reports'][0]['target'],'makers')
if __name__=='__main__':unittest.main(verbosity=2)

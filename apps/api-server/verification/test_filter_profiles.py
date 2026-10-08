"""Profiles and constrained combinations; SQL checks use an isolated *_test database."""
import asyncio
import json
import unittest
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from unittest.mock import AsyncMock, patch

import test_report_results as fixture
from pydantic import ValidationError
from sqlalchemy import select, update
from app.db import engine, schema as db
from app.filter_planner import FilterPlanner
from app.models.filter_profile import FIELD_ORDER, ProfileDefinition, ProfileWrite, case_key
from app.models.job import Job
from app.api.batch_queue import QueueTaskInput
from app.repositories.filter_profiles import FilterProfileRepository, reserve_options_runner, PreflightUnavailable
from app.repositories.batch_queue import BatchQueueRepository
from app.security import issue_access_token
from app.services import services


def definition(**patches):
    fields = {field: {'mode': 'fixed', 'values': []} for field in FIELD_ORDER}
    fields.update(delhiNcr={'mode': 'fixed', 'values': ['ALL STATES']},
        states={'mode': 'iterate'}, rtos={'mode': 'iterate'},
        archivedFlags={'mode':'fixed','values':['ACTIVE_COMPLIANT']},
        categoryGroups={'mode':'fixed','values':['Two Wheeler']},
        subCategories={'mode':'iterate'}, classes={'mode':'iterate'},
        evTypes={'mode':'iterate'}, fuels={'mode':'iterate'})
    return ProfileDefinition.model_validate({'fields': fields, **patches})


async def lookup(field, context, wanted):
    if field=='rtos': return {'State A':['A1','A2'],'State B':['B1']}[context['states'][0]]
    if field=='classes': return {'Sub 1':['Class 1'],'Sub 2':['Class 2']}[context['subCategories'][0]]
    if field=='fuels': return {'EV 1':['Fuel 1'],'EV 2':['Fuel 2']}[context['evTypes'][0]]
    return {'delhiNcr':['ALL STATES'],'states':['State A','State B'],
        'categoryGroups':['Two Wheeler'], 'subCategories':['Sub 1','Sub 2'],
        'evTypes':['EV 1','EV 2'],'archivedFlags':['ACTIVE_COMPLIANT']}[field]


class ProfileTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await engine.dispose()
        self.owner='profiles-'+str(uuid4());self.other='other-'+str(uuid4())
        await services.users.bootstrap(self.owner,'fixture-only-password')
        await services.users.bootstrap(self.other,'fixture-only-password')
        self.runner='profile-runner-'+str(uuid4())
        await services.runners.register(runner_id=self.runner,name='Profile fixture',socket_id=self.runner)
        self.repo=FilterProfileRepository()

    async def asyncTearDown(self): await engine.dispose()

    async def test_valid_dependent_combinations_and_unique_office_scopes(self):
        plan=await FilterPlanner(definition(),2024,lookup,AsyncMock()).compile()
        self.assertEqual(len(plan['scenarios']),12)
        self.assertEqual(len({case_key(case['filters']) for case in plan['scenarios']}),12)
        for case in plan['scenarios']:
            filters=case['filters'];self.assertEqual(filters['fromYear'],'2024')
            self.assertEqual(filters['classes'][0],filters['subCategories'][0].replace('Sub','Class'))
            self.assertEqual(filters['fuels'][0],filters['evTypes'][0].replace('EV','Fuel'))
        queue=BatchQueueRepository();session=uuid4()
        await queue.start(session,self.owner,[QueueTaskInput(name=case['name'],filters=case['filters']) for case in plan['scenarios']],5)
        self.assertEqual(len((await queue.snapshot(session,self.owner))['tasks']),12)

    async def test_saved_report_year_overrides_caller_and_round_trips_sql(self):
        spec=definition(report={'year':2023,'period':'CALENDAR YEAR','yAxis':'Maker','xAxis':'Month Wise'})
        saved=await self.repo.save(self.owner,ProfileWrite(name='Historical profile',definition=spec))
        restored=ProfileDefinition.model_validate((await self.repo.get(self.owner,saved['id']))['definition'])
        plan=await FilterPlanner(restored,2026,lookup,AsyncMock()).compile()
        self.assertEqual(plan['year'],2023)
        self.assertTrue(all(case['filters']['fromYear']=='2023' and case['filters']['toYear']=='2023' for case in plan['scenarios']))
        with self.assertRaises(ValidationError): definition(report={'year':datetime.now().year+1})
        with self.assertRaises(ValidationError): definition(report={'year':2023,'yAxis':'State'})

    async def test_include_exclude_and_conditional_rule(self):
        spec=definition(rules=[{'whenField':'subCategories','whenValues':['Sub 1'],
            'targetField':'evTypes','targetValues':['EV 2'],'action':'exclude'}])
        spec.fields['states'].include=['State A'];spec.fields['rtos'].exclude=['A2']
        plan=await FilterPlanner(spec,2024,lookup,AsyncMock()).compile()
        self.assertEqual(len(plan['scenarios']),3)
        self.assertTrue(all(case['filters']['rtos']==['A1'] for case in plan['scenarios']))

    async def test_fixed_multi_values_remain_combined_and_case_limit_is_explicit(self):
        spec=definition();spec.fields['classes'].mode='fixed';spec.fields['classes'].values=[]
        spec.fields['evTypes'].mode='fixed';spec.fields['evTypes'].values=[]
        spec.fields['fuels'].mode='fixed';spec.fields['fuels'].values=['Fuel 1','Fuel 2']
        async def source(field,context,wanted):
            if field=='fuels':return ['Fuel 1','Fuel 2']
            return await lookup(field,context,wanted)
        plan=await FilterPlanner(spec,2024,source,AsyncMock()).compile()
        self.assertEqual(len(plan['scenarios']),6)
        self.assertTrue(all(case['filters']['fuels']==['Fuel 1','Fuel 2'] for case in plan['scenarios']))
        with self.assertRaisesRegex(ValueError,'More than 2'):
            await FilterPlanner(definition(maxCases=2),2024,lookup,AsyncMock()).compile()

    async def test_sql_owner_revision_and_same_query_deduplication(self):
        saved=await self.repo.save(self.owner,ProfileWrite(name=' Historical EV ',definition=definition()))
        self.assertEqual(saved['name'],'Historical EV')
        self.assertEqual((await self.repo.list(self.owner))[-1]['definition'],saved['definition'])
        with self.assertRaises(LookupError):await self.repo.get(self.other,saved['id'])
        changed=await self.repo.save(self.owner,ProfileWrite(name='New name',definition=definition(),revision=1),saved['id'])
        self.assertEqual(changed['revision'],2)
        with self.assertRaisesRegex(ValueError,'edited elsewhere'):
            await self.repo.save(self.owner,ProfileWrite(name='Stale',definition=definition(),revision=1),saved['id'])
        self.assertEqual(case_key({'states':['STATE A'],'rtos':['A1'],'fuels':['Fuel 2','Fuel 1'],'classes':[]}),
                         case_key({'rtos':['a1'],'fuels':['FUEL 1','FUEL 2'],'states':[' state  a '],'autoApply':True}))
        await self.repo.delete(self.owner,saved['id'],2)
        with self.assertRaises(LookupError):await self.repo.get(self.owner,saved['id'])

    async def test_reservation_blocks_claims_and_expires_safely(self):
        session=uuid4();queue=BatchQueueRepository()
        tasks=[QueueTaskInput(name='Fixture',filters={'states':['State A'],'rtos':['A1']})]
        await queue.start(session,self.owner,tasks,1)
        async with reserve_options_runner(self.runner,self.owner):
            self.assertEqual((await queue.claim(session,self.owner,self.runner))['type'],'waiting')
            self.assertIsNone(await services.jobs.assign(Job(runnerId=self.runner,ownerUsername=self.owner,filters=tasks[0].filters)))
            self.assertEqual(next(r for r in await services.runners.list() if r.id==self.runner).status,'BUSY')
            with self.assertRaises(PreflightUnavailable) as blocked:
                async with reserve_options_runner(self.runner,self.other):pass
            self.assertEqual(blocked.exception.code, 'WORKER_BUSY')
            async with engine.begin() as connection:
                await connection.execute(update(db.runner_planning_leases).where(db.runner_planning_leases.c.runner_id==self.runner)
                    .values(expires_at=datetime.now(timezone.utc)-timedelta(seconds=1)))
            self.assertEqual((await queue.claim(session,self.owner,self.runner))['type'],'assigned')

    async def test_invalid_dimensions_rules_and_single_selects_are_rejected(self):
        spec=definition().model_dump(mode='json',by_alias=True)
        spec['fields']['notASupportedField']={'mode':'iterate'}
        with self.assertRaises(ValidationError):ProfileDefinition.model_validate(spec)
        spec=definition().model_dump(mode='json',by_alias=True)
        spec['fields']['fitness']['values']=['YES','NO']
        with self.assertRaises(ValidationError):ProfileDefinition.model_validate(spec)
        spec=definition().model_dump(mode='json',by_alias=True)
        spec['rules']=[{'whenField':'fuels','whenValues':['Fuel 1'],'targetField':'classes','targetValues':['Class 2'],'action':'require'}]
        plan=await FilterPlanner(ProfileDefinition.model_validate(spec),2024,lookup,AsyncMock()).compile()
        self.assertEqual(len(plan['scenarios']),9)

    async def test_http_preview_releases_its_worker_before_the_response_finishes(self):
        from test_ui_contract import observation
        from app.repositories import ui_contract
        from sqlalchemy import delete
        async with engine.begin() as c:
            await c.execute(delete(db.app_settings).where(db.app_settings.c.key==ui_contract.ACTIVE_KEY))
        checked=await ui_contract.evaluate(observation(),self.runner)
        async with engine.begin() as c:
            from sqlalchemy import insert
            from app.repositories.postgres import now
            await c.execute(insert(db.ui_preflight_checks).values(id=str(uuid4()),owner_username=self.owner,runner_ids=[self.runner],version_id=checked['versionId'],status='PASS',reports=[],created_at=now()))
        saved=await self.repo.save(self.owner,ProfileWrite(name='HTTP profile',definition=definition(report={'year':2023})))
        raw_session=await services.users.create_session(self.owner)
        token=issue_access_token(self.owner,raw_session)
        async def options(_event,request,**kwargs):
            self.assertTrue(request.get('requestId'))
            if request['type']=='GET_FILTER_CONTEXT':
                context=request['filters']
                self.assertEqual(context['fromYear'],'2023')
                self.assertEqual(context['toYear'],'2023')
                native={'delhiNcr':['ALL STATES'],'states':['State A','State B'],
                    'categoryGroups':['Two Wheeler'],'subCategories':['Sub 1','Sub 2'],
                    'evTypes':['EV 1','EV 2'],'archivedFlags':['ACTIVE_COMPLIANT'],
                    'classes':['Class 1'] if context.get('subCategories')==['Sub 1'] else ['Class 2'],
                    'fuels':['Fuel 1'] if context.get('evTypes')==['EV 1'] else ['Fuel 2']}
            elif request['type']=='GET_STATE_OPTIONS':native=['State A','State B']
            else:native={'State A':['A1','A2'],'State B':['B1']}[request['stateLabels']]
            return {'ok':True,'options':native}
        with patch('app.api.filter_profiles.sio.call',side_effect=options):
            status,content=await fixture.asgi_request('POST',f"/api/filter-profiles/{saved['id']}/preview",
                {'runnerId':self.runner,'year':2024},headers={'authorization':f'Bearer {token}'},binary=True)
        self.assertEqual(status,200)
        events=[json.loads(line) for line in content.decode().splitlines()]
        self.assertEqual(events[-1]['type'],'ready')
        self.assertEqual(events[-1]['plan']['year'],2023)
        self.assertEqual(len(events[-1]['plan']['scenarios']),12)
        async with engine.connect() as connection:
            self.assertIsNone(await connection.scalar(select(db.runner_planning_leases.c.runner_id)
                .where(db.runner_planning_leases.c.runner_id==self.runner)))
        await services.users.revoke(raw_session)

if __name__=='__main__':unittest.main(verbosity=2)

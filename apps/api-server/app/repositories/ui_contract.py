"""Verified DOM versions, immutable observations and preflight evidence in SQL."""
import hashlib,json
from uuid import uuid4
from datetime import timedelta
from sqlalchemy import select,insert,text,func,or_,cast,update
from sqlalchemy.dialects.postgresql import insert as pg_insert,JSONB
from app.db import engine,schema as db
from app.repositories.postgres import now

TARGET='/analytics/vahanpublicreport'
ACTIVE_KEY='vahan_ui_contract_active'
SELECT_IDS={'archivedFlags':'archivedFlags','period':'reportType','financialYears':'financialYearSelect','reportYear':'reportYear','reportMonth':'reportMonth','states':'stateName','rtos':'rtoCode','emissions':'vehicleEmission','categoryGroups':'vehicleCategoryGroup','subCategories':'vehicleSubCategory','classes':'vehicleClass','fuels':'vehicleFuel','evTypes':'evType','statuses':'vehicleStatus','ownerTypes':'vehicleOwnerType','vehicleType':'vehicleType','fitness':'fitnessCheck','delhiNcr':'delhiNcr','yAxis':'yAxis','xAxis':'xAxis','makers':'vehicleMaker'}
MULTIPLE={'archivedFlags','financialYears','states','rtos','emissions','categoryGroups','subCategories','classes','fuels','evTypes','statuses','ownerTypes','makers'}
SEEDS=[{'field':field,'selector':'#'+identifier,'tag':'select','multiple':field in MULTIPLE} for field,identifier in SELECT_IDS.items()]+[{'field':field,'selector':'#'+field,'tag':'input'} for field in ('fromYear','toYear','fromDate','toDate')]+[{'field':'apply','selector':'#applyTrigger','tag':'button'}]

async def current(connection=None):
    if connection is None:
        async with engine.connect() as c:return await current(c)
    state=await connection.scalar(select(db.app_settings.c.value).where(db.app_settings.c.key==ACTIVE_KEY)) or {}
    version=await connection.scalar(select(db.ui_contract_versions.c.controls).where(db.ui_contract_versions.c.id==state.get('versionId','')))
    # Data hashes are the latest observation; version rows remain immutable.
    controls=[{**item,'optionsHash':state.get('optionHashes',{}).get(item['field'],item.get('optionsHash'))} for item in (version or SEEDS)]
    return {**state,'versionId':state.get('versionId'),'revision':state.get('revision',0),
        'blocked':state.get('blocked',False),'controls':controls,'lastError':state.get('lastError')}

async def evaluate(observation,runner_id):
    """An incompatible observation is stored; it never replaces the active version."""
    async with engine.begin() as c:
        await c.execute(text("SELECT pg_advisory_xact_lock(hashtext('vahan-ui-contract'))"))
        previous=await current(c);expected={item['field']:item for item in previous['controls']}
        rows=observation.get('observedControls')
        rows=rows if isinstance(rows,list) else []
        found={item.get('field'):item for item in rows if isinstance(item,dict)}
        errors=[];repairs=[];changes=[];controls=[];selectors=set()
        if observation.get('status')=='CHECK_ERROR':errors.append({'code':'CHECK_ERROR','title':observation.get('error','Page check failed')})
        if len(found)!=len(rows):errors.append({'code':'UI_CONTRACT_MISMATCH','title':'Duplicate or malformed DOM evidence'})
        for seed in SEEDS:
            field=seed['field'];old=expected.get(field,seed);actual=found.get(field,{})
            selector=actual.get('selector','');reason=None
            if not actual.get('found') or actual.get('count')!=1:reason='Control missing or ambiguous'
            elif actual.get('tag')!=seed['tag']:reason='Control type changed'
            elif seed['tag']=='input' and actual.get('inputType') not in (('text','number') if field.endswith('Year') else ('text','date')):reason='Input behavior changed'
            elif seed['tag']=='select' and actual.get('multiple')!=seed['multiple']:reason='Single/multiple selection behavior changed'
            elif not isinstance(selector,str) or not selector or len(selector)>250:reason='Invalid resolved selector'
            elif selector in selectors:reason='Two fields resolve to the same control'
            elif selector!=old['selector'] and actual.get('matchedBy') not in ('name','label'):reason='Selector change has no verified semantic match'
            elif selector!=old['selector'] and not (
                actual.get('matchedBy')=='name' and old.get('name') and actual.get('name')==old['name']
                or actual.get('matchedBy')=='label' and old.get('label') and ' '.join(str(actual.get('label') or '').split()).lower()==' '.join(old['label'].split()).lower()
            ):reason='Resolved control does not retain its verified name or label'
            elif old.get('name') and actual.get('name')!=old['name'] and old.get('label') and actual.get('label')!=old['label']:reason='Both semantic name and label changed'
            if reason:
                errors.append({'code':'UI_CONTRACT_MISMATCH','title':reason,'target':field,'selector':old['selector'],'expected':old,'actual':actual});continue
            selectors.add(selector)
            controls.append({**seed,**{key:actual.get(key) for key in ('selector','id','name','label','tag','multiple','inputType','className','role')}})
            if selector!=old['selector']:repairs.append({'field':field,'before':old['selector'],'after':selector})
            if (old.get('optionsHash') and actual.get('optionsHash')!=old['optionsHash']) or any(key in old and old.get(key)!=actual.get(key) for key in ('className','role')):changes.append(field)
            controls[-1]['optionsHash']=actual.get('optionsHash')
        allowed=not errors
        version_id=previous['versionId'];revision=previous['revision']
        if allowed:
            # Option values are data, not a change of the crawler selector contract.
            fingerprint=hashlib.sha256(json.dumps([{k:v for k,v in item.items() if k!='optionsHash'} for item in controls],sort_keys=True).encode()).hexdigest()
            row=(await c.execute(select(db.ui_contract_versions).where(db.ui_contract_versions.c.fingerprint==fingerprint))).mappings().first()
            if row:version_id,revision=row['id'],row['revision']
            else:
                revision=(await c.scalar(select(func.max(db.ui_contract_versions.c.revision))) or 0)+1;version_id=str(uuid4())
                await c.execute(insert(db.ui_contract_versions).values(id=version_id,revision=revision,fingerprint=fingerprint,controls=controls,created_at=now()))
        status='CHECK_ERROR' if observation.get('status')=='CHECK_ERROR' else 'UI_DRIFT' if errors else 'DATA_CHANGED' if repairs or changes else 'PASS'
        details={'allowed':allowed,'status':status,'versionId':version_id,'revision':revision,'repairs':repairs,'dataChanges':changes,'reports':errors,'errorCount':len(errors),'runnerId':runner_id,
            'checkedAt':observation.get('checkedAt'),'checkId':observation.get('checkId')}
        runner_errors=dict(previous.get('runnerErrors',{}))
        if allowed:runner_errors.pop(runner_id,None)
        else:runner_errors[runner_id]=details
        connected_ids=set(await c.scalars(select(db.runners.c.id).where(db.runners.c.connected.is_(True))))
        runner_errors={key:value for key,value in runner_errors.items() if key in connected_ids}
        active_errors=runner_errors
        blocked=bool(active_errors)
        details['blocked']=blocked
        value={'versionId':version_id,'revision':revision,'blocked':blocked,'runnerErrors':runner_errors,
            'lastError':next(iter(active_errors.values()))['reports'][0]['title'] if blocked else None,
            'lastCheck':details,'optionHashes':{item['field']:item.get('optionsHash') for item in controls} if allowed else previous.get('optionHashes',{})}
        await c.execute(pg_insert(db.app_settings).values(key=ACTIVE_KEY,value=value).on_conflict_do_update(index_elements=['key'],set_={'value':value}))
        return details

LEGACY_PREFLIGHT_AVAILABILITY_MESSAGES={
    'Choose an online, idle worker to load filter options.',
    'This worker is preparing another filter preview. Try another idle worker.',
    'Worker is busy.',
}

def _legacy_availability_only(reports):
    if not isinstance(reports,list) or not reports:
        return False
    found_availability=False
    for report in reports:
        if not isinstance(report,dict):
            return False
        if report.get('allowed') is True:
            continue
        issues=report.get('reports')
        if not isinstance(issues,list) or not issues:
            return False
        if all(isinstance(issue,dict) and issue.get('code')=='PREFLIGHT_FAILED'
                and issue.get('title') in LEGACY_PREFLIGHT_AVAILABILITY_MESSAGES for issue in issues):
            found_availability=True
            continue
        return False
    return found_availability

async def reclassify_legacy_availability_preflights():
    """Keep historical worker-busy reports from masquerading as website drift."""
    async with engine.begin() as c:
        rows=(await c.execute(select(db.ui_preflight_checks.c.id,db.ui_preflight_checks.c.reports)
            .where(db.ui_preflight_checks.c.status=='BLOCKED')
            .order_by(db.ui_preflight_checks.c.created_at.desc()).limit(200))).mappings().all()
        ids=[row['id'] for row in rows if _legacy_availability_only(row['reports'])]
        if ids:
            await c.execute(update(db.ui_preflight_checks).where(db.ui_preflight_checks.c.id.in_(ids))
                .values(status='WAITING'))
        return len(ids)

async def require_gate(owner,runner_ids,gate_id=None,fresh=False,session_id=None,bound=False):
    await reclassify_legacy_availability_preflights()
    async with engine.connect() as c:
        state=await c.scalar(select(db.app_settings.c.value).where(db.app_settings.c.key==ACTIVE_KEY)) or {}
        if state.get('blocked') or not state.get('versionId'):raise ValueError('UI_HEALTH_BLOCKED: UI contract requires a successful check. Open UI Health and copy the diagnostic error for dev.')
        if session_id:
            binding=await c.scalar(select(db.app_settings.c.value).where(db.app_settings.c.key=='ui_gate:'+str(session_id)))
            gate_id=gate_id or (binding or {}).get('id')
            if bound and not binding:raise ValueError('UI_PREFLIGHT_REQUIRED: saved queue needs a new preflight before resuming.')
        query=select(db.ui_preflight_checks).where(db.ui_preflight_checks.c.owner_username==owner,db.ui_preflight_checks.c.status=='PASS')
        if gate_id:query=query.where(db.ui_preflight_checks.c.id==str(gate_id))
        rows=(await c.execute(query.order_by(db.ui_preflight_checks.c.created_at.desc()).limit(20))).mappings().all()
        for row in rows:
            if row['version_id']==state['versionId'] and set(runner_ids)<=set(row['runner_ids']) and (not fresh or row['created_at']>=now()-timedelta(minutes=5)):
                superseded=await c.scalar(select(db.ui_preflight_checks.c.id).where(
                    db.ui_preflight_checks.c.owner_username==owner,
                    db.ui_preflight_checks.c.status=='BLOCKED',
                    db.ui_preflight_checks.c.created_at>row['created_at'],
                    or_(*(cast(db.ui_preflight_checks.c.runner_ids,JSONB).contains([runner]) for runner in runner_ids))
                ).limit(1))
                if superseded:continue
                return str(row['id'])
    raise ValueError('UI_PREFLIGHT_REQUIRED: check all selected workers before loading Maker data or starting this run.')

async def bind_gate(session_id,gate_id):
    async with engine.begin() as c:
        await c.execute(pg_insert(db.app_settings).values(key='ui_gate:'+str(session_id),value={'id':str(gate_id)}).on_conflict_do_update(index_elements=['key'],set_={'value':{'id':str(gate_id)}}))

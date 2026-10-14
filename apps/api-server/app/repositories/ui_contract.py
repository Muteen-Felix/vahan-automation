"""Verified DOM versions, immutable observations and preflight evidence in SQL."""
import hashlib,json
from uuid import uuid4
from datetime import timedelta
from sqlalchemy import select,insert,text,func,or_,cast,update
from sqlalchemy.dialects.postgresql import insert as pg_insert,JSONB
from app.db import engine,schema as db
from app.repositories.postgres import now,audit_in
from app.models.runner import Runner

TARGET='/analytics/vahanpublicreport'
ACTIVE_KEY='vahan_ui_contract_active'
GENERATION_KEY='ui_gate_generation'
LOCK_SQL="SELECT pg_advisory_xact_lock(hashtext('vahan-ui-contract'))"
# State keys that evaluate() must carry over when it rewrites the active value.
ORDER_KEYS=('runnerLastSeq','runnerLastCheckId')
# A runner must have been unseen for this long (API clock) before its error may be retired.
RETIRE_SILENCE=timedelta(minutes=15)

class GateOpError(Exception):
    """A rejected gate operation; nothing was changed."""
    def __init__(self,status_code,code,message):
        super().__init__(message);self.status_code=status_code;self.code=code;self.message=message
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
    # Losing transport does not prove that an incompatible DOM was repaired.
    # Only a successful observation from the same runner clears its evidence.
    active_errors=state.get('runnerErrors',{})
    blocked=bool(active_errors) if state.get('runnerErrors') else state.get('blocked',False)
    return {**state,'versionId':state.get('versionId'),'revision':state.get('revision',0),
        'blocked':blocked,'blockedRunnerIds':sorted(active_errors),'controls':controls,
        'lastError':next(iter(active_errors.values()))['reports'][0]['title'] if active_errors else state.get('lastError') if blocked else None}

async def gate_generation(connection=None):
    """Current gate generation; a PASS preflight is only valid at the generation it was made in."""
    if connection is None:
        async with engine.connect() as c:return await gate_generation(c)
    value=await connection.scalar(select(db.app_settings.c.value).where(db.app_settings.c.key==GENERATION_KEY))
    try:return int((value or {}).get('n',0))
    except (TypeError,ValueError,AttributeError):return 0

async def next_check_seq():
    """Server-issued, strictly increasing order of health checks (never the runner's clock)."""
    async with engine.begin() as c:
        return int(await c.scalar(text("SELECT nextval('ui_health_check_seq')")))

def _order_decision(previous,runner_id,observation,allowed):
    """Decide by the server-issued ``checkSeq`` whether an observation may change gate state.

    Returns ``apply`` | ``stale`` | ``idempotent`` | ``anomaly``. Observations without a
    ``checkSeq`` (runners that predate it, or logs written before the migration) are applied
    in arrival order exactly as before: they carry no ordering protection (PLAN OPEN-5)."""
    seq=observation.get('checkSeq')
    if isinstance(seq,bool) or not isinstance(seq,int):return 'apply'
    last=(previous.get('runnerLastSeq') or {}).get(runner_id)
    if last is None or seq>last:return 'apply'
    if seq<last:return 'stale'
    same=observation.get('checkId') and observation.get('checkId')==(previous.get('runnerLastCheckId') or {}).get(runner_id)
    if same:return 'idempotent'
    # Same sequence, different check: violates the issuing rule. Never let it clear an error.
    return 'apply' if not allowed else 'anomaly'

async def evaluate(observation,runner_id):
    """An incompatible observation is stored; it never replaces the active version."""
    async with engine.begin() as c:
        await c.execute(text(LOCK_SQL))
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
        order=_order_decision(previous,runner_id,observation,allowed)
        if order!='apply':
            # Late/duplicate evidence: record nothing in gate state. A stale or anomalous PASS can
            # never clear a newer error; an idempotent repeat reports what it already did.
            ignored=order!='idempotent'
            return {'allowed':allowed and not ignored,'status':'STALE_OBSERVATION' if ignored else ('PASS' if allowed else 'CHECK_ERROR'),
                'versionId':previous['versionId'],'revision':previous['revision'],'repairs':[],'dataChanges':[],
                'reports':[{'code':'STALE_OBSERVATION' if order=='stale' else 'ORDER_ANOMALY','title':'This check was superseded by a newer check of the same worker and was not applied.'}] if ignored else [],
                'errorCount':1 if ignored else 0,'runnerId':runner_id,'checkedAt':observation.get('checkedAt'),
                'checkId':observation.get('checkId'),'blocked':previous['blocked'],'ignored':ignored,'order':order}
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
        active_errors=runner_errors
        blocked=bool(active_errors)
        details['blocked']=blocked
        value={'versionId':version_id,'revision':revision,'blocked':blocked,'runnerErrors':runner_errors,
            'lastError':next(iter(active_errors.values()))['reports'][0]['title'] if blocked else None,
            'lastCheck':details,'optionHashes':{item['field']:item.get('optionsHash') for item in controls} if allowed else previous.get('optionHashes',{})}
        # Order bookkeeping survives every rewrite of the active value; observations without a
        # checkSeq leave it untouched.
        for key in ORDER_KEYS:
            if previous.get(key):value[key]=dict(previous[key])
        seq=observation.get('checkSeq')
        if isinstance(seq,int) and not isinstance(seq,bool):
            value.setdefault('runnerLastSeq',{})[runner_id]=seq
            value.setdefault('runnerLastCheckId',{})[runner_id]=observation.get('checkId')
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
        state=await current(c)
        if state.get('blocked') or not state.get('versionId'):raise ValueError('UI_HEALTH_BLOCKED: UI contract requires a successful check. Open UI Health and copy the diagnostic error for dev.')
        if session_id:
            binding=await c.scalar(select(db.app_settings.c.value).where(db.app_settings.c.key=='ui_gate:'+str(session_id)))
            gate_id=gate_id or (binding or {}).get('id')
            if bound and not binding:raise ValueError('UI_PREFLIGHT_REQUIRED: saved queue needs a new preflight before resuming.')
        # A PASS made before a retire/invalidate (older gate generation) is never accepted again,
        # whether it is used directly, by id or through a session binding.
        generation=await gate_generation(c)
        query=select(db.ui_preflight_checks).where(db.ui_preflight_checks.c.owner_username==owner,db.ui_preflight_checks.c.status=='PASS',
            db.ui_preflight_checks.c.gate_generation==generation)
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

async def _bump_generation(connection):
    """Caller holds the contract advisory lock (same transaction)."""
    before=await gate_generation(connection);after=before+1
    await connection.execute(pg_insert(db.app_settings).values(key=GENERATION_KEY,value={'n':after})
        .on_conflict_do_update(index_elements=['key'],set_={'value':{'n':after}}))
    return before,after

def _fault(hook,step):
    if hook is not None:hook(step)

def _runner_silence(row):
    """Time since the API last saw the runner, read through the model (the JSON key is
    ``last_seen_at``; ``Runner`` also accepts the ``lastSeenAt`` alias)."""
    try:
        seen=Runner.model_validate(row['payload']).last_seen_at
        return now()-seen
    except Exception:
        return None

async def retire_runner_error(actor,runner_id,reason,*,silence=RETIRE_SILENCE,fault=None):
    """Retire the stored error of a runner that will never report again.

    One transaction under the same advisory lock as evaluate(): the error removal, the gate
    generation bump (which invalidates every older PASS preflight) and the audit event commit
    together or not at all. Nothing is deleted by hand; every precondition is checked here."""
    reason=(reason or '').strip()
    if len(reason)<10:raise GateOpError(400,'REASON_REQUIRED','A reason of at least 10 characters is required.')
    async with engine.begin() as c:
        await c.execute(text(LOCK_SQL));_fault(fault,'after_lock')
        raw=await c.scalar(select(db.app_settings.c.value).where(db.app_settings.c.key==ACTIVE_KEY)) or {}
        errors=dict(raw.get('runnerErrors') or {})
        if runner_id not in errors:raise GateOpError(404,'NO_ERROR_FOR_RUNNER','This worker has no stored error.')
        error=errors[runner_id]
        row=(await c.execute(select(db.runners).where(db.runners.c.id==runner_id).with_for_update())).mappings().first()
        if row is None:raise GateOpError(409,'RUNNER_UNKNOWN','The worker is not known; its silence cannot be established.')
        if row['connected']:raise GateOpError(409,'RUNNER_CONNECTED','The worker is connected; it must pass its own check.')
        if row['current_job_id']:raise GateOpError(409,'RUNNER_BUSY','The worker still owns a job.')
        idle=_runner_silence(row)
        if idle is None:raise GateOpError(409,'RUNNER_STATE_UNREADABLE','The worker record is unreadable; not retiring.')
        if idle<silence:raise GateOpError(409,'RUNNER_RECENTLY_SEEN','The worker was seen recently; wait before retiring its error.')
        lease=await c.scalar(select(db.runner_planning_leases.c.runner_id).where(
            db.runner_planning_leases.c.runner_id==runner_id,db.runner_planning_leases.c.expires_at>now()))
        if lease:raise GateOpError(409,'RUNNER_LEASED','The worker is reserved by another operation.')
        # Another online worker must have passed a newer check under the active contract version.
        error_at=await c.scalar(select(db.ui_health_checks.c.created_at).where(db.ui_health_checks.c.id==str(error.get('checkId') or '')))
        if error_at is None:raise GateOpError(409,'ERROR_EVIDENCE_MISSING','The stored error has no check record to compare against.')
        replacements=(await c.execute(text(
            "SELECT h.id FROM ui_health_checks h JOIN runners r "
            "ON r.id = h.payload->'healthCheck'->'contractValidation'->>'runnerId' "
            "WHERE r.connected IS TRUE AND r.id <> :runner AND h.created_at > :since "
            "AND (h.payload->'healthCheck'->'contractValidation'->>'allowed') = 'true' "
            "AND h.payload->'healthCheck'->'contractValidation'->>'versionId' = :version "
            "ORDER BY h.created_at DESC LIMIT 3"),{'runner':runner_id,'since':error_at,'version':raw.get('versionId') or ''})).scalars().all()
        if not replacements:raise GateOpError(409,'NO_REPLACEMENT_PASS','No other online worker has passed a newer check.')
        _fault(fault,'after_checks')
        remaining={key:value for key,value in errors.items() if key!=runner_id}
        value={**raw,'runnerErrors':remaining,'blocked':bool(remaining),
            'lastError':next(iter(remaining.values()))['reports'][0]['title'] if remaining else None}
        for key in ORDER_KEYS:
            if isinstance(value.get(key),dict):value[key]={k:v for k,v in value[key].items() if k!=runner_id}
        await c.execute(pg_insert(db.app_settings).values(key=ACTIVE_KEY,value=value)
            .on_conflict_do_update(index_elements=['key'],set_={'value':value}));_fault(fault,'after_state')
        before,after=await _bump_generation(c);_fault(fault,'after_generation')
        await c.execute(update(db.ui_preflight_checks).where(db.ui_preflight_checks.c.status=='PASS').values(status='SUPERSEDED'))
        _fault(fault,'after_supersede')
        result={'runnerId':runner_id,'previousErrorCode':((error.get('reports') or [{}])[0]).get('code'),'previousCheckId':error.get('checkId'),
            'replacementCheckIds':list(replacements),'reason':reason,'generationBefore':before,'generationAfter':after,
            'blockedBefore':bool(errors),'blockedAfter':bool(remaining)}
        await audit_in(c,actor,'ui_health.runner_error_retired',result);_fault(fault,'after_audit')
        return result

async def invalidate_gates(actor,reason,*,fault=None):
    """Make every existing PASS preflight (including session-bound gates) unusable. Used before a
    rollback so no job runs on evidence created for a different set of workers."""
    reason=(reason or '').strip()
    if len(reason)<10:raise GateOpError(400,'REASON_REQUIRED','A reason of at least 10 characters is required.')
    async with engine.begin() as c:
        await c.execute(text(LOCK_SQL));_fault(fault,'after_lock')
        before,after=await _bump_generation(c);_fault(fault,'after_generation')
        await c.execute(update(db.ui_preflight_checks).where(db.ui_preflight_checks.c.status=='PASS').values(status='SUPERSEDED'))
        _fault(fault,'after_supersede')
        result={'reason':reason,'generationBefore':before,'generationAfter':after}
        await audit_in(c,actor,'ui_health.gates_invalidated',result);_fault(fault,'after_audit')
        return result

async def bind_gate(session_id,gate_id):
    async with engine.begin() as c:
        await c.execute(pg_insert(db.app_settings).values(key='ui_gate:'+str(session_id),value={'id':str(gate_id)}).on_conflict_do_update(index_elements=['key'],set_={'value':{'id':str(gate_id)}}))

"""Daily freshness coverage, proved by committed SQL imports, across known plans."""
from collections import defaultdict
from datetime import date, datetime
from zoneinfo import ZoneInfo
from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import Date, cast, func, literal, or_, select
from sqlalchemy.dialects.postgresql import JSONB
from app.db import engine, schema as db
from app.api.report_coverage import filter_key
from app.repositories.annual_reports import context_year, dataset

router=APIRouter(prefix='/annual-reports',tags=['annual-reports'])
ZONE=ZoneInfo('Asia/Ho_Chi_Minh')


def day(value):
    return value.astimezone(ZONE).date().isoformat() if isinstance(value,datetime) else str(value)


def summarize(imports, tasks, from_year, to_year, selected=''):
    groups={}
    def group(scope,year,label):
        return groups.setdefault((scope,year),{'datasetId':scope,'label':label,'year':year,'planned':{},'days':defaultdict(lambda:{'saved':{},'review':set(),'active':set(),'failed':set(),'paused':set()}),'latest':None})
    for task in tasks:
        year=context_year(task['filters'])
        if year is None or not from_year<=year<=to_year:continue
        scope=dataset(None,task['filters'])
        if selected and selected!=scope['id']:continue
        item=group(scope['id'],year,scope['label'])
        key=filter_key(task['filters'])
        # Tasks arrive newest-plan first, retaining the source case order.
        if key not in item['planned']:
            item['planned'][key]={'name':task['scenario_name'],'state':', '.join(task['filters'].get('states',[])),
                                 'rto':', '.join(task['filters'].get('rtos',[]))}
        activity=item['days'][day(task['updated_at'])]
        if task['status'] in ('PENDING','PROCESSING'):
            activity['active' if task['session_status']=='RUNNING' else 'paused'].add(key)
        elif task['status']=='FAILED':activity['failed'].add(key)
    for record in imports:
        key=filter_key(record['filters']) if record['filters'] else None
        for year in record['years']:
            if not from_year<=year<=to_year or (selected and record['scope_key']!=selected):continue
            item=group(record['scope_key'],year,record['scope_label'])
            entry=item['days'][day(record['saved_day'])]
            if record['valid'] and key:
                previous=entry['saved'].get(key)
                if not previous or previous['imported_at']<record['imported_at']:entry['saved'][key]=record
            else:entry['review'].add(key or record['name'])
    datasets=[]
    for item in groups.values():
        expected=item['planned'];daily=[]
        for saved_day,activity in sorted(item['days'].items(),reverse=True):
            accepted={key:value for key,value in activity['saved'].items() if not expected or key in expected}
            fresh=set(accepted)
            total=len(expected) if expected else None
            missing=[value for key,value in expected.items() if key not in fresh]
            active=activity['active']-fresh;failed=activity['failed']-fresh;paused=activity['paused']-fresh
            latest=max(accepted.values(),key=lambda row:row['imported_at'],default=None)
            state=('complete' if total is not None and len(fresh)==total else 'updating' if active else
                   'paused' if paused else 'partial' if total is not None else 'unknown')
            daily.append({'date':saved_day,'updatedCases':len(fresh),'totalCases':total,
                'remainingCases':len(missing) if total is not None else None,
                'percent':round(len(fresh)*100/total,1) if total else None,'state':state,
                'activeCases':len(active),'failedCases':len(failed),'reviewCases':len(activity['review']),
                'lastSavedAt':latest['imported_at'] if latest else None,
                'lastSavedCase':latest['name'] if latest else None,
                'firstNotUpdated':missing[0] if missing else None})
        datasets.append({'datasetId':item['datasetId'],'label':item['label'],'year':item['year'],
                         'latest':daily[0] if daily else None,'days':daily})
    return {'fromYear':from_year,'toYear':to_year,'timezone':'Asia/Ho_Chi_Minh',
            'datasets':sorted(datasets,key=lambda item:(-item['year'],item['label'])),
            'coverageBasis':'Recorded case plans; a saved timestamp alone does not prove a full dataset refresh.'}


@router.get('/update-status')
async def update_status(from_year:int=Query(2023,alias='fromYear',ge=1900,le=9999),
                        to_year:int=Query(datetime.now(ZONE).year,alias='toYear',ge=1900,le=9999),
                        dataset_id:str=Query('',alias='dataset',max_length=64)):
    if to_year<from_year or to_year-from_year>20:
        raise HTTPException(400,'Choose an ordered year range of at most 21 years.')
    ledger,jobs,tasks,sessions=db.report_update_history,db.jobs,db.batch_queue_tasks,db.batch_queue_sessions
    empty=literal([],type_=JSONB)
    valid=(ledger.c.status.in_(['added','updated','unchanged','no-data'])
           & (func.coalesce(ledger.c.details['issueCount'].as_integer(),0)==0)
           & (func.coalesce(ledger.c.details['warnings'],empty)==empty)
           & ((ledger.c.status=='no-data') | (func.coalesce(ledger.c.details['newCells'].as_integer(),0)>0)
              | (func.coalesce(ledger.c.details['duplicates'].as_integer(),0)>0)
              | (func.coalesce(ledger.c.details['replacedCells'].as_integer(),0)>0)))
    saved_day=cast(func.timezone('Asia/Ho_Chi_Minh',ledger.c.imported_at),Date)
    source_filters=func.coalesce(jobs.c.filters,ledger.c.filters)
    conditions=[or_(*(cast(ledger.c.years,JSONB).contains([year]) for year in range(from_year,to_year+1)))]
    if dataset_id:conditions.append(ledger.c.scope_key==dataset_id)
    async with engine.connect() as connection:
        imports=(await connection.execute(select(ledger.c.scope_key,ledger.c.scope_label,ledger.c.years,
            source_filters.label('filters'),saved_day.label('saved_day'),func.coalesce(func.max(ledger.c.imported_at).filter(valid),func.max(ledger.c.imported_at)).label('imported_at'),
            func.max(ledger.c.name).label('name'),func.bool_or(valid).label('valid'))
            .select_from(ledger.outerjoin(jobs,ledger.c.job_id==jobs.c.id)).where(*conditions)
            .group_by(ledger.c.scope_key,ledger.c.scope_label,ledger.c.years,source_filters,saved_day))).mappings().all()
        ranked=select(tasks.c.filters,tasks.c.scenario_name,tasks.c.status,tasks.c.updated_at,
            sessions.c.status.label('session_status'),sessions.c.created_at.label('session_created_at'),tasks.c.position,
            func.row_number().over(partition_by=tasks.c.filters,
                order_by=(sessions.c.created_at.desc(),tasks.c.updated_at.desc())).label('rank'))
        ranked=(ranked.select_from(tasks.join(sessions))
            .where(tasks.c.filters['fromYear'].as_string().in_([str(year) for year in range(from_year,to_year+1)])).subquery())
        planned=(await connection.execute(select(ranked).where(ranked.c.rank==1)
            .order_by(ranked.c.session_created_at.desc(),ranked.c.position))).mappings().all()
    return summarize(imports,planned,from_year,to_year,dataset_id)

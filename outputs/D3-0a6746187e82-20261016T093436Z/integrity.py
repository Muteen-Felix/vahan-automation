import harness as h
import json,collections
def capture(session,name,expected=None,plan=None):
    code="""import asyncio,json,collections
from sqlalchemy import select,func
from app.db import engine,schema as db
from app.models.filter_profile import case_key
SESSION=__SESSION__
async def main():
 async with engine.connect() as c:
  tasks=[dict(r) for r in (await c.execute(select(db.batch_queue_tasks).where(db.batch_queue_tasks.c.session_id==SESSION).order_by(db.batch_queue_tasks.c.position))).mappings()]
  jobs=[dict(r) for r in (await c.execute(select(db.jobs.c.id,db.jobs.c.status,db.jobs.c.filters,db.jobs.c.payload).where(db.jobs.c.session_id==SESSION))).mappings()]
  duplicates=[list(r) for r in (await c.execute(select(db.main_reports.c.scope_key,db.main_reports.c.year,db.main_reports.c.state,db.main_reports.c.rto,db.main_reports.c.rto_code,db.main_reports.c.maker,func.count()).group_by(db.main_reports.c.scope_key,db.main_reports.c.year,db.main_reports.c.state,db.main_reports.c.rto,db.main_reports.c.rto_code,db.main_reports.c.maker).having(func.count()>1))).all()]
  byfilter=collections.Counter(case_key(r['filters']) for r in tasks)
  successes=collections.Counter(case_key(r['filters']) for r in jobs if r['status'] in ['COMPLETED','NO_DATA'])
  out={'sessionId':SESSION,'taskCount':len(tasks),'positions':[r['position'] for r in tasks],'uniqueFilters':len(byfilter),'filterKeys':list(byfilter),'taskStatusCounts':dict(collections.Counter(r['status'] for r in tasks)),'jobStatusCounts':dict(collections.Counter(r['status'] for r in jobs)),'sumAttempts':sum(r['attempts'] for r in tasks),'jobCount':len(jobs),'retriedTasks':[{'position':r['position'],'attempts':r['attempts'],'failures':r['failures'],'status':r['status'],'error':r['error']} for r in tasks if r['attempts']>1],'duplicateSuccessfulLogicalCases':{k:v for k,v in successes.items() if v>1},'duplicateMainRows':duplicates,'tasks':[{'position':r['position'],'status':r['status'],'attempts':r['attempts'],'failures':r['failures'],'jobId':r['job_id'],'caseKey':case_key(r['filters'])} for r in tasks]}
  print(json.dumps(out,default=str))
 await engine.dispose()
asyncio.run(main())
""".replace('__SESSION__',repr(session))
    r=h.compose('exec','-T','api','python','-c',code)
    assert r['returncode']==0,h.clean(r['stderr'])
    data=json.loads(r['stdout']);data.update(at=h.now(),sha=h.SHA)
    h.save(name,data)
    if expected is not None:
        assert data['taskCount']==data['uniqueFilters']==expected
        assert data['positions']==list(range(expected))
        assert data['sumAttempts']==data['jobCount']
        assert not data['duplicateSuccessfulLogicalCases'] and not data['duplicateMainRows']
        assert not any(s in data['taskStatusCounts'] for s in ['PENDING','PROCESSING'])
        if plan:
            import hashlib
            # Reproduce the final module's canonical_filters for the expected native preview.
            def clean(value):
                if isinstance(value,list):return sorted(set(' '.join(str(item).split()).casefold() for item in value))
                return ' '.join(value.split()).casefold() if isinstance(value,str) else value
            def key(filters):
                canonical=json.dumps({k:clean(v) for k,v in filters.items() if k not in ['autoApply','autoExport'] and clean(v) not in (None,'',[])},sort_keys=True,separators=(',',':'))
                return hashlib.sha256(canonical.encode()).hexdigest()
            wanted={key(s['filters']) for s in plan}
            actual=set(data['filterKeys'])
            assert actual==wanted,'Stored queue cases differ from the native preview'
            data.update(exactNativePreviewCasesMatch=True,expectedNativePreviewCases=len(wanted))
            h.save(name,data)
    return data
if __name__=='__main__':
    import sys
    capture(sys.argv[1],sys.argv[2],int(sys.argv[3]) if len(sys.argv)>3 else None)
    print('Integrity snapshot saved')

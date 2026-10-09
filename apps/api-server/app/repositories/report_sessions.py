"""Read run summaries without transferring historical JSON blobs or artifact lists."""
from sqlalchemy import text
from app.db import engine


CTES = """
WITH selected_sessions AS (
    SELECT r.* FROM report_sessions r
    WHERE (CAST(:owner AS text) IS NULL OR r.owner_username = :owner)
      AND (CAST(:session_id AS text) IS NULL OR r.id = :session_id)
      AND (CAST(:session_id AS text) IS NOT NULL OR (r.deleted_at IS NOT NULL) = :deleted)
    ORDER BY r.created_at DESC, r.id DESC OFFSET :session_offset LIMIT :session_limit
), attempts AS (
    SELECT j.id, j.session_id, j.case_id, j.retry_of_job_id, j.source, j.scenario_name,
           j.status, j.created_at, j.updated_at, s.deleted_at
    FROM jobs j JOIN selected_sessions s ON s.id = j.session_id
), legacy AS (
    SELECT a.id, first_value(a.id) OVER (
        PARTITION BY a.session_id, a.source, a.scenario_name, j.filters ORDER BY a.created_at, a.id
    ) AS root FROM attempts a JOIN jobs j ON j.id=a.id
    WHERE a.case_id IS NULL AND a.retry_of_job_id IS NULL
), keyed AS (
    SELECT a.*, COALESCE(l.root, a.case_id, a.id) AS logical_case
    FROM attempts a LEFT JOIN legacy l ON l.id = COALESCE(a.case_id, a.id)
), ranked AS (
    SELECT k.*,
        row_number() OVER (PARTITION BY session_id, logical_case ORDER BY created_at DESC, id DESC) AS rank,
        min(created_at) OVER (PARTITION BY session_id, logical_case) AS original_created,
        min(created_at) OVER (PARTITION BY session_id) AS started_at,
        max(updated_at) OVER (PARTITION BY session_id) AS session_updated
    FROM keyed k
), latest AS (SELECT * FROM ranked WHERE rank = 1), files AS (
    SELECT DISTINCT ON (f.job_id, f.kind) f.id, f.job_id, f.kind, f.name, f.size
    FROM stored_files f JOIN latest l ON l.id = f.job_id
    WHERE f.kind IN ('excel','no-data') AND f.kind = CASE l.status WHEN 'COMPLETED' THEN 'excel' WHEN 'NO_DATA' THEN 'no-data' END
    ORDER BY f.job_id, f.kind, f.created_at DESC, f.id DESC
)
"""

SUMMARY = CTES + """
SELECT l.session_id, min(l.started_at) AS started_at, max(l.session_updated) AS updated_at,
    max(l.deleted_at) AS deleted_at, count(*) AS job_count,
    count(*) FILTER (WHERE l.status='COMPLETED') AS completed_count,
    count(*) FILTER (WHERE l.status='NO_DATA') AS no_data_count,
    count(*) FILTER (WHERE l.status='FAILED') AS failed_count,
    count(*) FILTER (WHERE l.status='CANCELLED') AS cancelled_count,
    count(*) FILTER (WHERE l.status NOT IN ('COMPLETED','NO_DATA','FAILED','CANCELLED')) AS active_count,
    count(f.id) AS file_count, COALESCE(sum(f.size),0) AS total_file_size,
    array_agg(DISTINCT l.source ORDER BY l.source) AS sources
FROM latest l LEFT JOIN files f ON f.job_id=l.id
GROUP BY l.session_id ORDER BY min(l.started_at) DESC, l.session_id DESC
"""

DETAIL = CTES + """
SELECT l.id, l.scenario_name, j.filters, l.status, l.source, l.original_created,
       l.updated_at, j.payload->>'error' AS error,
       f.id AS file_id, f.kind, f.name, f.size
FROM latest l JOIN jobs j ON j.id=l.id LEFT JOIN files f ON f.job_id=l.id
ORDER BY l.original_created, l.id OFFSET :offset LIMIT :limit
"""


def summary_document(row):
    names = {'job_count':'jobCount','completed_count':'completedCount','no_data_count':'noDataCount',
             'failed_count':'failedCount','cancelled_count':'cancelledCount','active_count':'activeCount',
             'file_count':'fileCount','total_file_size':'totalFileSize'}
    return {'sessionId':row['session_id'],'sessionFolder':row['session_id'],
            'startedAt':row['started_at'].isoformat(),'updatedAt':row['updated_at'].isoformat(),
            'deletedAt':row['deleted_at'].isoformat() if row['deleted_at'] else None,
            'sources':row['sources'],'jobs':[], **{target:int(row[key]) for key,target in names.items()}}


async def _fetch_summaries(params):
    async with engine.connect() as connection:
        return [summary_document(row) for row in (await connection.execute(text(SUMMARY),params)).mappings()]


async def read_sessions(owner=None, *, deleted=False, session_id=None, offset=0, limit=100,
                        job_offset=0, job_limit=100):
    params = {'owner':owner, 'deleted':deleted, 'session_id':str(session_id) if session_id else None,
              'session_offset':0 if session_id else offset, 'session_limit':1 if session_id else limit,
              'offset':job_offset, 'limit':job_limit}
    if not session_id:
        from app.db.read_cache import summary_read
        return await summary_read(('history',owner,deleted,offset,limit),lambda:_fetch_summaries(params))
    async with engine.connect() as connection:
        connection = await connection.execution_options(isolation_level='REPEATABLE READ')
        results = [summary_document(row) for row in (await connection.execute(text(SUMMARY),params)).mappings()]
        if not results:return results
        result = results[0]
        for row in (await connection.execute(text(DETAIL),params)).mappings():
            filters = row['filters']
            has_file = row['file_id'] is not None
            result['jobs'].append({'jobId':row['id'], 'scenarioName':row['scenario_name'] or 'VAHAN report',
                'state':next(iter(filters.get('states',[])), ''), 'rto':next(iter(filters.get('rtos',[])), ''),
                'source':row['source'], 'status':row['status'], 'error':row['error'], 'filters':filters,
                'fileName':row['name'], 'fileType':('excel' if row['kind']=='excel' else 'text') if has_file else None,
                'fileSize':row['size'] or 0, 'filePath':f"postgresql:{row['file_id']}" if has_file else None,
                'createdAt':row['original_created'].isoformat(), 'updatedAt':row['updated_at'].isoformat(),
                'downloadUrl':f"/api/jobs/{row['id']}/{row['kind']}" if has_file else None})
        result.update(offset=job_offset,limit=job_limit,hasMore=job_offset+len(result['jobs'])<result['jobCount'])
        return results

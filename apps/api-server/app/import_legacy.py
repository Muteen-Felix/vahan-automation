"""Copy legacy runtime data into PostgreSQL. Sources are never removed.

Run inside the API container with a read-only mount at /legacy.
Re-running is safe: path + SHA-256 identifies each immutable source version.
"""
import argparse, asyncio, hashlib, json, mimetypes, re
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, NAMESPACE_URL, uuid5
from sqlalchemy import select
from app.config import settings
from app.db import engine, schema as db
from app.models.job import Job, JobStatus
from app.services import services
from app.repositories.postgres import PostgresStateStore, job_document, now, save_job
from app.repositories.file_store import extract_file, insert_file

def identifier(value):
    return uuid5(NAMESPACE_URL, 'vahan-legacy:' + value)

async def run(root, owner, dry_run=False):
    paths = sorted(p for p in root.rglob('*') if p.is_file() and not p.is_symlink())
    if dry_run:
        print(json.dumps({'files': len(paths), 'bytes': sum(p.stat().st_size for p in paths)})); return
    if not await services.users.get(owner):
        raise ValueError('Import owner must be an existing SQL user.')
    snapshots = []
    snapshot_path = root / 'migration-snapshot.json'
    if snapshot_path.exists():
        snapshots = json.loads(snapshot_path.read_text())
    historical = {(str(s['sessionId']), j.get('fileName')): j for s in snapshots for j in s['jobs'] if j.get('fileName')}
    mapping = await PostgresStateStore().get('legacy-import-index', {})
    counters = {'imported': 0, 'skipped': 0, 'rows': 0, 'extractionFailed': 0}
    for path in paths:
        relative = path.relative_to(root).as_posix()
        content = await asyncio.to_thread(path.read_bytes)
        digest = hashlib.sha256(content).hexdigest()
        key = relative + ':' + digest
        if key in mapping:
            counters['skipped'] += 1; continue
        job = None
        metadata = {'legacyPath': relative, 'sourceSha256': digest}
        parts = path.relative_to(root).parts
        if len(parts) >= 3 and parts[0] == 'excel-reports' and path.suffix.lower() in {'.xlsx', '.txt'}:
            marker = root / parts[0] / parts[1] / '.vahan-session-id'
            session = UUID(marker.read_text().strip()) if marker.is_file() else identifier(parts[1])
            original = historical.get((str(session), path.name))
            state = path.parent.name
            match = re.search(r' of (.*?)\s*,\s*', path.stem)
            job = Job(id=UUID(original['jobId']) if original else identifier(key), sessionId=session,
                runnerId='legacy-import', ownerUsername=owner,
                filters=original['filters'] if original else {'states': [state], 'rtos': [match[1].strip() if match else path.stem]},
                scenarioName=original.get('scenarioName') if original else path.stem,
                status=JobStatus.COMPLETED if path.suffix.lower() == '.xlsx' else JobStatus.NO_DATA,
                createdAt=original['createdAt'] if original else datetime.fromtimestamp(path.stat().st_mtime, timezone.utc),
                updatedAt=original['updatedAt'] if original else now())
            existing_job = await services.jobs.get(job.id)
            if existing_job:
                # A changed source retains a separate immutable version.
                job.id = identifier(key)
        rows, info = [], {}
        try:
            rows, info = await asyncio.to_thread(extract_file, content, path.name)
            info['extractionStatus'] = 'complete'
        except Exception as error:
            info = {'extractionStatus': 'failed', 'extractionError': str(error)}
            counters['extractionFailed'] += 1
        kind = ('excel' if job.status == JobStatus.COMPLETED else 'no-data') if job else 'legacy'
        async with engine.begin() as connection:
            if job:
                await services.jobs._insert(connection, job)
            if kind in {'excel', 'no-data'}:
                from app.repositories.annual_reports import import_rows
                file_id = 'legacy:' + hashlib.sha256(key.encode()).hexdigest()
                await import_rows(connection, source_key=file_id, name=path.name, rows=rows,
                    filters=job.filters.model_dump(mode='json', by_alias=True), owner=owner,
                    observed_at=job.created_at, job_id=str(job.id), no_data=kind == 'no-data',
                    strict=True, checksum=digest)
                job.main_report_saved_at = now()
                job.result_observed_at = job.created_at
                job.main_report_checksum = digest if kind == 'excel' else None
                job.result_checksum = digest if kind == 'no-data' else None
                job.result_message = 'No record found' if kind == 'no-data' else 'Data saved to main table'
                job.main_report_summary = await connection.scalar(select(db.report_update_history.c.details)
                    .where(db.report_update_history.c.source_key == file_id))
                await save_job(connection, job, 'legacy-main-report')
            else:
                file_id = await insert_file(connection, name=path.name, content=content, kind=kind,
                    mime_type=mimetypes.guess_type(path.name)[0] or 'application/octet-stream',
                    job=job, owner=owner, metadata={**metadata, **info})
            # Main values and the operator import index commit together.
            mapping[key] = file_id
            from sqlalchemy.dialects.postgresql import insert as pg_insert
            await connection.execute(pg_insert(db.app_settings).values(key='legacy-import-index', value=mapping)
                .on_conflict_do_update(index_elements=[db.app_settings.c.key], set_={'value': mapping}))
        counters['imported'] += 1; counters['rows'] += len(rows)
    # Preserve failed, cancelled and interrupted historical jobs as well as completed files.
    for session in snapshots:
        for original in session['jobs']:
            if await services.jobs.get(UUID(original['jobId'])):
                continue
            status = JobStatus(original['status'])
            error = original.get('error')
            if status not in {JobStatus.COMPLETED, JobStatus.NO_DATA, JobStatus.FAILED, JobStatus.CANCELLED}:
                status, error = JobStatus.FAILED, 'Interrupted during migration; retry explicitly.'
            if status == JobStatus.COMPLETED:
                status, error = JobStatus.FAILED, 'Legacy Excel file is missing from the source runtime.'
            await services.jobs.create(Job(id=original['jobId'], sessionId=session['sessionId'], runnerId='legacy-import',
                ownerUsername=owner, filters=original['filters'], scenarioName=original.get('scenarioName'),
                status=status, error=error, createdAt=original['createdAt'], updatedAt=original['updatedAt']))
    print(json.dumps(counters))

async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path)
    parser.add_argument('--owner', default=settings.ui_auth_username)
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    if not args.root.is_dir():
        parser.error('Runtime directory does not exist.')
    try:
        await run(args.root, args.owner, args.dry_run)
    finally:
        await engine.dispose()

if __name__ == '__main__':
    asyncio.run(main())

import hashlib
import json
from datetime import timezone
from sqlalchemy import select
from app.db import engine, schema as db
from app.models.job import Job, JobStatus, UpdateKind
from app.repositories.postgres import now, release_runner, save_job


async def commit_report_result(job_id, runner_id, command):
    """Confirmed no-data history and terminal job status commit together."""
    document = command.model_dump(mode='json', by_alias=True)
    checksum = hashlib.sha256(json.dumps(document, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    async with engine.begin() as connection:
        payload = await connection.scalar(select(db.jobs.c.payload).where(
            db.jobs.c.id == str(job_id)).with_for_update())
        if not payload:
            raise ValueError('Job not found.')
        job = Job.model_validate(payload)
        if job.runner_id != runner_id:
            raise PermissionError('This runner is not assigned to the job.')
        if command.result == 'DATA':
            if job.status == JobStatus.COMPLETED and job.main_report_checksum:
                return job  # Compatibility ACK for older workers; never saves DOM copies.
            raise ValueError('Full workbook must be saved to the main table before completing a data result.')
        if job.result_checksum:
            if job.result_checksum != checksum or job.status != JobStatus.NO_DATA:
                raise ValueError('A different result has already been saved for this job.')
            return job
        if job.main_report_checksum or job.status != JobStatus.WAITING_RESULT:
            raise ValueError('Job is not waiting for a report result.')
        if job.update_kind == UpdateKind.GLOBAL:
            raise ValueError('A global Maker baseline cannot be saved from a no-data result.')
        if job.update_kind == UpdateKind.DISCOVER:
            from app.repositories.maker_updates import commit_discovery
            job.main_report_summary = await commit_discovery(connection, job, [],
                command.observed_at.astimezone(timezone.utc), no_data=True)
        elif job.update_kind == UpdateKind.REFRESH:
            from app.repositories.maker_updates import clear_no_data_refresh
            job.main_report_summary = await clear_no_data_refresh(connection, job)
        else:
            from app.repositories.annual_reports import import_rows
            source_key = 'job:' + str(job.id)
            await import_rows(connection, source_key=source_key, job_id=str(job.id),
                name=job.scenario_name or 'No record found', rows=[],
                filters=job.filters.model_dump(mode='json', by_alias=True), owner=job.owner_username,
                observed_at=command.observed_at.astimezone(timezone.utc), no_data=True, checksum=checksum)
            job.main_report_summary = await connection.scalar(select(db.report_update_history.c.details)
                .where(db.report_update_history.c.source_key == source_key))
        job.status, job.result_checksum, job.main_report_saved_at = JobStatus.NO_DATA, checksum, now()
        job.result_message, job.result_observed_at = command.message, command.observed_at
        job.report_table_count = job.report_row_count = 0
        job.excel_file_name = job.excel_file_size = job.no_data_file_name = None
        job.error = None
        job.touch()
        await save_job(connection, job, 'main-report-no-data')
        await release_runner(connection, job.runner_id, job.id)
    return job


async def get_report_result(job_id, offset=0, limit=100):
    async with engine.connect() as connection:
        payload = await connection.scalar(select(db.jobs.c.payload).where(db.jobs.c.id == str(job_id)))
    if not payload:
        return None
    job = Job.model_validate(payload)
    if not job.main_report_saved_at:
        return None
    return {'job_id': str(job.id), 'result': 'NO_RECORD' if job.status == JobStatus.NO_DATA else 'DATA',
        'message': job.result_message, 'states': job.filters.states, 'rtos': job.filters.rtos,
        'filters': job.filters.model_dump(mode='json', by_alias=True), 'observed_at': job.result_observed_at,
        'saved_at': job.main_report_saved_at, 'sha256': job.main_report_checksum or job.result_checksum,
        'summary': job.main_report_summary, 'scope': 'main-table', 'rows': [], 'tables': [],
        'offset': offset, 'limit': limit}

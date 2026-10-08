"""Notify authorized dashboard clients only after the report transaction commits."""
import logging
from sqlalchemy import select
from app.db import engine, schema as db
from app.repositories.annual_reports import saved_report_summary
from app.realtime.server import sio
from app.scheduler_wakeup import wake_scheduler

logger = logging.getLogger(__name__)


async def notify_report_saved(job):
    # The report transaction is already committed. Let the scheduler settle this
    # queue item and refill the freed worker immediately.
    if job.session_id:
        wake_scheduler()
    try:
        await sio.emit('job:status', job.model_dump(mode='json', by_alias=True),
                       room=f'job:{job.id}', namespace='/ui')
    except Exception:
        logger.exception('Job notification failed after SQL commit.')
    try:
        async with engine.connect() as connection:
            saved = (await connection.execute(select(db.report_update_history)
                .where(db.report_update_history.c.job_id == str(job.id))
                .order_by(db.report_update_history.c.imported_at.desc()).limit(1))).mappings().first()
        if saved:
            # No private job payload or account credentials are broadcast.
            await sio.emit('reports:updated', saved_report_summary(saved),
                           room='reports:shared', namespace='/ui')
    except Exception:
        # Realtime transport failure cannot turn an already committed filter into a failed save.
        logger.exception('Shared report notification failed after SQL commit.')

from fastapi import APIRouter, Request
from sqlalchemy import select, func
from app.access import require_admin
from app.config import settings
from app.db import engine, schema as db

router=APIRouter(prefix='/security',tags=['security operations'])


@router.get('/status')
async def status(request: Request):
    require_admin(request)
    async with engine.connect() as connection:
        pending=await connection.scalar(select(func.count()).select_from(db.soc_outbox)
                                       .where(db.soc_outbox.c.delivered.is_(False)))
        last=await connection.scalar(select(func.max(db.soc_outbox.c.delivered_at))
                                    .where(db.soc_outbox.c.delivered.is_(True)))
    return {'tenantId':settings.tenant_id,'isolation':'dedicated-stack',
            'adminMfaRequired':settings.require_admin_mfa,'cookieSecure':settings.cookie_secure,
            'collectorConfigured':bool(settings.soc_url),'pendingEvents':pending,
            'lastDeliveredEventAt':last,'uniqueWorkerCredentials':bool(settings.runner_tokens)}

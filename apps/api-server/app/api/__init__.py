from fastapi import APIRouter

from app.api.auth import router as auth_router
from app.api.excel import router as excel_router
from app.api.health import router as health_router
from app.api.jobs import router as jobs_router
from app.api.runners import router as runners_router
from app.api.ui_health import router as ui_health_router

api_router = APIRouter(prefix="/api")
api_router.include_router(health_router)
api_router.include_router(auth_router)
api_router.include_router(excel_router)
api_router.include_router(jobs_router)
api_router.include_router(runners_router)
api_router.include_router(ui_health_router)

from fastapi import APIRouter

from app.api.update_status import router as update_status_router
from app.api.auth import router as auth_router
from app.api.excel import router as excel_router
from app.api.health import router as health_router
from app.api.jobs import router as jobs_router
from app.api.runners import router as runners_router
from app.api.ui_health import router as ui_health_router
from app.api.data import router as data_router
from app.api.annual_reports import router as annual_reports_router
from app.api.report_coverage import router as report_coverage_router
from app.api.maker_updates import router as maker_updates_router
from app.api.batch_queue import router as batch_queue_router
from app.api.worker_pool import router as worker_pool_router
from app.api.filter_profiles import router as filter_profiles_router
from app.api.run_schedules import router as run_schedules_router

api_router = APIRouter(prefix="/api")
api_router.include_router(health_router)
api_router.include_router(auth_router)
api_router.include_router(excel_router)
api_router.include_router(jobs_router)
api_router.include_router(runners_router)
api_router.include_router(ui_health_router)
api_router.include_router(data_router)
api_router.include_router(annual_reports_router)
api_router.include_router(update_status_router)
api_router.include_router(report_coverage_router)
api_router.include_router(maker_updates_router)
api_router.include_router(batch_queue_router)
api_router.include_router(worker_pool_router)
api_router.include_router(filter_profiles_router)
api_router.include_router(run_schedules_router)

from dataclasses import dataclass

from app.config import settings
from app.repositories import (
    InMemoryJobRepository,
    InMemoryRunnerRegistry,
    UiHealthLogStore,
    InMemoryUiHealthScheduleRepository,
)
from app.repositories.captcha_image_store import CaptchaImageStore


@dataclass(slots=True)
class Services:
    jobs: InMemoryJobRepository
    runners: InMemoryRunnerRegistry
    ui_health: InMemoryUiHealthScheduleRepository
    ui_health_logs: UiHealthLogStore
    captcha_images: CaptchaImageStore


services = Services(
    jobs=InMemoryJobRepository(),
    runners=InMemoryRunnerRegistry(),
    ui_health=InMemoryUiHealthScheduleRepository(),
    ui_health_logs=UiHealthLogStore(settings.ui_health_log_dir),
    captcha_images=CaptchaImageStore(
        settings.captcha_image_dir,
        path_template=settings.captcha_image_path_template,
    ),
)

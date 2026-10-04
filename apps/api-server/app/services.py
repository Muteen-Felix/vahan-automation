from dataclasses import dataclass

from app.repositories.postgres import PostgresJobRepository, PostgresRunnerRegistry, PostgresScheduleRepository, PostgresUsers
from app.repositories.file_store import PostgresFileStore, PostgresCaptchaStore
from app.repositories.postgres_health import PostgresHealthLogStore


@dataclass(slots=True)
class Services:
    jobs: PostgresJobRepository
    runners: PostgresRunnerRegistry
    ui_health: PostgresScheduleRepository
    ui_health_logs: PostgresHealthLogStore
    captcha_images: PostgresCaptchaStore
    files: PostgresFileStore
    users: PostgresUsers


services = Services(
    jobs=PostgresJobRepository(), runners=PostgresRunnerRegistry(),
    ui_health=PostgresScheduleRepository(), ui_health_logs=PostgresHealthLogStore(),
    captcha_images=PostgresCaptchaStore(), files=PostgresFileStore(), users=PostgresUsers(),
)

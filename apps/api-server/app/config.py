from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


DEFAULT_UI_HEALTH_LOG_DIR = Path(__file__).resolve().parents[1] / "runtime" / "ui-health-logs"
DEFAULT_EXCEL_REPORT_DIR = Path(__file__).resolve().parents[1] / "runtime" / "excel-reports"
DEFAULT_CAPTCHA_IMAGE_DIR = Path(__file__).resolve().parents[1] / "runtime" / "images1"
DEFAULT_CAPTCHA_IMAGE_PATH_TEMPLATE = "{job_id}/ảnh1"
DEFAULT_WEB_CORS_ORIGINS = (
    "http://localhost:5173",
    "http://127.0.0.1:5173",
)


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    value = int(os.getenv(name, str(default)))
    if not minimum <= value <= maximum:
        raise ValueError(f'{name} must be between {minimum} and {maximum}.')
    return value


def _local_ui_auth_values() -> dict[str, str]:
    """Read only the dashboard credentials from the ignored API .env file."""
    env_path = Path(__file__).resolve().parents[1] / ".env"
    allowed_keys = {
        "VAHAN_UI_AUTH_USERNAME",
        "VAHAN_UI_AUTH_PASSWORD",
        "VAHAN_UI_AUTH_TOKEN_SECRET",
    }
    values: dict[str, str] = {}
    try:
        lines = env_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return values

    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        key, separator, value = line.partition("=")
        if not separator or key.strip() not in allowed_keys:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key.strip()] = value
    return values


@dataclass(frozen=True, slots=True)
class Settings:
    app_name: str = "VAHAN RPA API"
    host: str = "127.0.0.1"
    port: int = 8000
    debug: bool = False
    cors_origins: tuple[str, ...] = DEFAULT_WEB_CORS_ORIGINS
    socketio_cors_origins: str | tuple[str, ...] = DEFAULT_WEB_CORS_ORIGINS
    runner_token: str = "change-me"
    ui_auth_username: str = ""
    ui_auth_password: str = ""
    ui_auth_token_secret: str = ""
    runner_disconnect_grace_seconds: float = 30.0
    ui_health_log_dir: str = str(DEFAULT_UI_HEALTH_LOG_DIR)
    excel_report_dir: str = str(DEFAULT_EXCEL_REPORT_DIR)
    captcha_image_dir: str = str(DEFAULT_CAPTCHA_IMAGE_DIR)
    captcha_image_path_template: str = DEFAULT_CAPTCHA_IMAGE_PATH_TEMPLATE
    max_excel_upload_bytes: int = 50 * 1024 * 1024  # 50 MB
    database_url: str = "postgresql+asyncpg://vahan@127.0.0.1:5432/vahan"
    db_pool_size: int = 10
    db_max_overflow: int = 5
    db_pool_timeout_seconds: int = 5
    db_statement_timeout_ms: int = 60000
    db_lock_timeout_ms: int = 5000
    db_idle_transaction_timeout_ms: int = 30000
    bulk_operation_concurrency: int = 2
    browser_state_key: str = ""
    runner_health_checks: bool = False
    tenant_id: str = "legacy"
    production: bool = False
    runner_tokens: str = ""
    cookie_secure: bool = False
    require_admin_mfa: bool = False
    mfa_key: str = ""
    soc_url: str = ""
    soc_ingest_key: str = ""
    trusted_proxy_host: str = ""
    max_export_rows: int = 100_000
    parser_timeout_seconds: int = 120

    @property
    def session_cookie_name(self) -> str:
        return f"vahan_session_{self.tenant_id}"

    @property
    def ui_auth_configured(self) -> bool:
        return (
            len(self.ui_auth_token_secret) >= 32
        )

    @classmethod
    def from_env(cls) -> "Settings":
        local_auth = _local_ui_auth_values()

        def auth_value(name: str, default: str = "") -> str:
            environment_value = os.getenv(name)
            return environment_value if environment_value is not None else local_auth.get(name, default)

        web_origins = tuple(
            origin.strip()
            for origin in os.getenv(
                "VAHAN_API_CORS_ORIGINS",
                ",".join(DEFAULT_WEB_CORS_ORIGINS),
            ).split(",")
            if origin.strip()
        )
        origins = web_origins
        socketio_origins_value = os.getenv("VAHAN_API_SOCKETIO_CORS_ORIGINS", ",".join(web_origins)).strip()
        socketio_origins: str | tuple[str, ...] = (
            "*"
            if socketio_origins_value == "*"
            else tuple(
                origin.strip()
                for origin in socketio_origins_value.split(",")
                if origin.strip()
            )
        )
        return cls(
            tenant_id=os.getenv('VAHAN_TENANT_ID', 'legacy'),
            production=_as_bool(os.getenv('VAHAN_PRODUCTION')),
            runner_tokens=os.getenv('VAHAN_RUNNER_TOKENS', ''),
            cookie_secure=_as_bool(os.getenv('VAHAN_COOKIE_SECURE')),
            require_admin_mfa=_as_bool(os.getenv('VAHAN_REQUIRE_ADMIN_MFA')),
            mfa_key=os.getenv('VAHAN_MFA_ENCRYPTION_KEY', ''),
            soc_url=os.getenv('VAHAN_SOC_URL', ''),
            soc_ingest_key=os.getenv('VAHAN_SOC_INGEST_KEY', ''),
            trusted_proxy_host=os.getenv('VAHAN_TRUSTED_PROXY_HOST', ''),
            max_export_rows=_env_int('VAHAN_MAX_EXPORT_ROWS', 100000, 1, 1048573),
            parser_timeout_seconds=_env_int('VAHAN_PARSER_TIMEOUT_SECONDS', 120, 10, 300),
            database_url=os.getenv("DATABASE_URL", "postgresql+asyncpg://vahan@127.0.0.1:5432/vahan"),
            db_pool_size=_env_int('VAHAN_DB_POOL_SIZE', 10, 1, 50),
            db_max_overflow=_env_int('VAHAN_DB_MAX_OVERFLOW', 5, 0, 20),
            db_pool_timeout_seconds=_env_int('VAHAN_DB_POOL_TIMEOUT_SECONDS', 5, 1, 60),
            db_statement_timeout_ms=_env_int('VAHAN_DB_STATEMENT_TIMEOUT_MS', 60000, 1000, 600000),
            db_lock_timeout_ms=_env_int('VAHAN_DB_LOCK_TIMEOUT_MS', 5000, 100, 60000),
            db_idle_transaction_timeout_ms=_env_int('VAHAN_DB_IDLE_TRANSACTION_TIMEOUT_MS', 30000, 1000, 600000),
            bulk_operation_concurrency=_env_int('VAHAN_BULK_OPERATION_CONCURRENCY', 2, 1, 4),
            browser_state_key=os.getenv("VAHAN_BROWSER_STATE_KEY", ""),
            runner_health_checks=_as_bool(os.getenv('VAHAN_API_RUNNER_HEALTH_CHECKS')),
            host=os.getenv("VAHAN_API_HOST", "127.0.0.1"),
            port=int(os.getenv("VAHAN_API_PORT", "8000")),
            debug=_as_bool(os.getenv("VAHAN_API_DEBUG")),
            cors_origins=origins,
            socketio_cors_origins=socketio_origins,
            runner_token=os.getenv("VAHAN_API_RUNNER_TOKEN", "change-me"),
            ui_auth_username=auth_value("VAHAN_UI_AUTH_USERNAME").strip(),
            ui_auth_password=auth_value("VAHAN_UI_AUTH_PASSWORD"),
            ui_auth_token_secret=auth_value("VAHAN_UI_AUTH_TOKEN_SECRET"),
            runner_disconnect_grace_seconds=float(os.getenv("VAHAN_API_RUNNER_DISCONNECT_GRACE_SECONDS", "30")),
            ui_health_log_dir=os.getenv("VAHAN_UI_HEALTH_LOG_DIR", str(DEFAULT_UI_HEALTH_LOG_DIR)),
            excel_report_dir=os.getenv("VAHAN_EXCEL_REPORT_DIR", str(DEFAULT_EXCEL_REPORT_DIR)),
            captcha_image_dir=os.getenv("VAHAN_CAPTCHA_IMAGE_DIR", str(DEFAULT_CAPTCHA_IMAGE_DIR)),
            captcha_image_path_template=os.getenv(
                "VAHAN_CAPTCHA_IMAGE_PATH_TEMPLATE",
                DEFAULT_CAPTCHA_IMAGE_PATH_TEMPLATE,
            ),
        )


settings = Settings.from_env()

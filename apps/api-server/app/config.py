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
    socketio_cors_origins: str | tuple[str, ...] = "*"
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
    browser_state_key: str = ""
    worker_controller_url: str = ""

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
        socketio_origins_value = os.getenv("VAHAN_API_SOCKETIO_CORS_ORIGINS", "*").strip()
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
            database_url=os.getenv("DATABASE_URL", "postgresql+asyncpg://vahan@127.0.0.1:5432/vahan"),
            browser_state_key=os.getenv("VAHAN_BROWSER_STATE_KEY", ""),
            worker_controller_url=os.getenv('VAHAN_WORKER_CONTROLLER_URL', ''),
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

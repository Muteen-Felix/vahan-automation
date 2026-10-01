import socketio

from app.config import settings

sio = socketio.AsyncServer(
    async_mode="asgi",
    # An unpacked Chrome extension has a generated chrome-extension:// origin.
    # The API listens on loopback for this MVP and runner authentication is
    # still enforced independently by the /runner namespace token.
    cors_allowed_origins=settings.socketio_cors_origins,
    logger=settings.debug,
    engineio_logger=settings.debug,
)

# Import modules for their event-handler registrations.
from app.realtime import runner_events, ui_events  # noqa: E402, F401

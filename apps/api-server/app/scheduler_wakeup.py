"""Coalesce work-completion signals for the scheduled-run leader."""
import asyncio


_event_loop = None
_wake_event = None


def _event_for_current_loop():
    global _event_loop, _wake_event
    loop = asyncio.get_running_loop()
    if loop is not _event_loop:
        _event_loop = loop
        _wake_event = asyncio.Event()
    return _wake_event


def wake_scheduler():
    """Request an immediate scheduler pass without creating duplicate tasks."""
    _event_for_current_loop().set()


async def wait_for_scheduler_wakeup(timeout_seconds: float = 5):
    """Wake on a persisted state change, with a periodic reconciliation fallback."""
    event = _event_for_current_loop()
    try:
        await asyncio.wait_for(event.wait(), timeout=timeout_seconds)
    except asyncio.TimeoutError:
        pass
    finally:
        event.clear()

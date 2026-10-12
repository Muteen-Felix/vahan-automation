"""Shared, database-backed limits for automatic CAPTCHA OCR starts."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert

from app.db import engine, schema as db

OCR_START_LIMIT = 20
OCR_WINDOW = timedelta(minutes=10)
OCR_WINDOW_KEY = "security:ocr-start-window:v1"


@dataclass(frozen=True, slots=True)
class OcrStartDecision:
    allowed: bool
    duplicate: bool = False
    retry_after_seconds: int = 0
    remaining: int = 0


def _request_key(job_id: UUID, captcha_id: str) -> str:
    return sha256(f"{job_id}:{captcha_id}".encode("utf-8")).hexdigest()


async def reserve_ocr_start(job_id: UUID, captcha_id: str) -> OcrStartDecision:
    """Atomically reserve one OCR start across all API and runner instances."""
    key = _request_key(job_id, captcha_id)
    async with engine.begin() as connection:
        await connection.execute(insert(db.app_settings).values(
            key=OCR_WINDOW_KEY, value={"starts": []}
        ).on_conflict_do_nothing(index_elements=[db.app_settings.c.key]))
        row = (await connection.execute(select(db.app_settings.c.value)
            .where(db.app_settings.c.key == OCR_WINDOW_KEY).with_for_update())).scalar_one()
        current = await connection.scalar(select(func.clock_timestamp()))
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        cutoff = current - OCR_WINDOW
        starts = [entry for entry in row.get("starts", [])
            if datetime.fromisoformat(entry["startedAt"]).astimezone(timezone.utc) > cutoff]
        if any(entry["key"] == key for entry in starts):
            await connection.execute(update(db.app_settings).where(
                db.app_settings.c.key == OCR_WINDOW_KEY).values(value={"starts": starts}))
            return OcrStartDecision(allowed=False, duplicate=True, remaining=OCR_START_LIMIT-len(starts))
        if len(starts) >= OCR_START_LIMIT:
            await connection.execute(update(db.app_settings).where(
                db.app_settings.c.key == OCR_WINDOW_KEY).values(value={"starts": starts}))
            earliest = min(datetime.fromisoformat(entry["startedAt"]).astimezone(timezone.utc)
                for entry in starts)
            retry_after = max(1, int((earliest + OCR_WINDOW - current).total_seconds() + 0.999))
            return OcrStartDecision(allowed=False, retry_after_seconds=retry_after)
        starts.append({"key": key, "startedAt": current.isoformat()})
        await connection.execute(update(db.app_settings).where(
            db.app_settings.c.key == OCR_WINDOW_KEY).values(value={"starts": starts}))
        return OcrStartDecision(allowed=True, remaining=OCR_START_LIMIT-len(starts))

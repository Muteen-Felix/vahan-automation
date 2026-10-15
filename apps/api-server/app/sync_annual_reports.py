"""Idempotently import workbook rows already stored in SQL; keep original files intact."""
import asyncio
from app.db import engine
from app.repositories.annual_reports import backfill


async def main():
    try:
        print(f'Processed {await backfill()} existing workbook sources.')
    finally:
        await engine.dispose()


if __name__ == '__main__':
    asyncio.run(main())

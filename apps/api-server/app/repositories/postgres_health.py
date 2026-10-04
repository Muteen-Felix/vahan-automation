from collections import defaultdict
from sqlalchemy import select, delete
from sqlalchemy.dialects.postgresql import insert as pg_insert
from app.db import engine
from app.db import schema as db
from app.repositories.postgres import now
from app.repositories.ui_health_log_store import row_from_health_check, to_csv, _row_error_count

class PostgresHealthLogStore:
    async def append(self, health_check, page_url=""):
        row = row_from_health_check(health_check, page_url)
        async with engine.begin() as connection:
            await connection.execute(pg_insert(db.ui_health_checks).values(id=row["log_id"],
                check_date=row["check_date"], payload={"healthCheck": health_check, "pageUrl": page_url},
                csv_row=row, created_at=now()).on_conflict_do_nothing())
        rows = await self._rows(row["check_date"])
        date = row["check_date"]
        return dict(ok=True, logId=row["log_id"], fileName=f"report-{date}-to-{date}.csv",
            rowCount=len(rows), fromDate=date, toDate=date, part=1)

    async def _rows(self, date=None):
        query = select(db.ui_health_checks.c.csv_row).order_by(db.ui_health_checks.c.created_at.desc())
        if date:
            query = query.where(db.ui_health_checks.c.check_date == date)
        async with engine.connect() as connection:
            return [{k: str(v) for k, v in row.items()} for row in (await connection.execute(query)).scalars()]

    async def list_reports(self, selected_date=None):
        grouped = defaultdict(list)
        for row in await self._rows():
            grouped[row["check_date"]].append(row)
        dates, reports = [], []
        selected_date = selected_date or (max(grouped) if grouped else None)
        for date in sorted(grouped, reverse=True):
            rows = grouped[date]
            summary = dict(date=date, total=len(rows), latestCheckedAt=max(r["checked_at"] for r in rows),
                **{"pass": 0, "dataChanged": 0, "uiDrift": 0, "checkError": 0, "dataChangedErrors": 0, "uiDriftErrors": 0})
            for row in rows:
                key = {"PASS": "pass", "DATA_CHANGED": "dataChanged", "UI_DRIFT": "uiDrift", "CHECK_ERROR": "checkError"}.get(row["status"])
                if key:
                    summary[key] += 1
                if key in {"dataChanged", "uiDrift"}:
                    summary[f"{key}Errors"] += _row_error_count(row)
            dates.append(summary)
            name = f"report-{date}-to-{date}.csv"
            reports.append(dict(fileName=name, fromDate=date, toDate=date, part=1, rowCount=len(rows),
                sizeBytes=len(to_csv(rows).encode()), updatedAt=summary["latestCheckedAt"],
                containsSelectedDate=date == selected_date, downloadUrl=f"/api/ui-health/reports/{name}/download"))
        return dict(selectedDate=selected_date, availableDates=dates, reports=reports, rows=grouped.get(selected_date, []))

    async def resolve_report(self, name):
        import re
        match = re.fullmatch(r"report-(\d{4}-\d{2}-\d{2})-to-\1\.csv", name)
        if not match:
            return None
        rows = await self._rows(match[1])
        return to_csv(rows).encode() if rows else None

    async def clear(self):
        from app.repositories.postgres import require_test_database
        require_test_database()
        async with engine.begin() as connection:
            await connection.execute(delete(db.ui_health_checks))

from __future__ import annotations

import asyncio
import csv
import json
import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


LOG_SCHEMA_VERSION = "v3"
MAX_DAYS_PER_FILE = 10
MAX_BYTES_PER_FILE = 512 * 1024
STATE_FILE_NAME = ".ui-health-state.json"

COLUMNS = (
    "log_id",
    "schema_version",
    "checked_at",
    "check_date",
    "status",
    "failure_type",
    "trigger",
    "started_at",
    "duration_ms",
    "page_url",
    "page_path",
    "contract_version",
    "signature",
    "form_action",
    "checked_controls",
    "error_code",
    "error_count",
    "error_title",
    "error",
    "step",
    "target",
    "selector",
    "expected",
    "actual",
    "diagnostic_details",
    "action",
)

_REPORT_FILE_RE = re.compile(
    r"^report-(?P<from>\d{4}-\d{2}-\d{2})-to-(?P<to>\d{4}-\d{2}-\d{2})"
    r"(?:-part-(?P<part>\d+))?\.csv$"
)


def _text(value: Any) -> str:
    return "" if value is None else str(value)


def _date_only(value: Any) -> str:
    match = re.match(r"^\d{4}-\d{2}-\d{2}", _text(value))
    if match:
        candidate = match.group(0)
        try:
            date.fromisoformat(candidate)
            return candidate
        except ValueError:
            pass
    return datetime.now(timezone.utc).date().isoformat()


def _day_number(value: str) -> int:
    return date.fromisoformat(value).toordinal()


def _add_days(value: str, days: int) -> str:
    return date.fromordinal(_day_number(value) + days).isoformat()


def _duration_ms(started_at: Any, checked_at: Any) -> int | str:
    try:
        start = datetime.fromisoformat(_text(started_at).replace("Z", "+00:00"))
        end = datetime.fromisoformat(_text(checked_at).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return ""
    try:
        milliseconds = int((end - start).total_seconds() * 1_000)
    except TypeError:
        return ""
    return milliseconds if milliseconds >= 0 else ""


def _json_text(value: Any, fallback: str = "{}") -> str:
    try:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError):
        return fallback


def _path_from_url(value: str) -> str:
    return urlparse(value).path


def _normalize_control(control: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": _text(control.get("name")),
        "selector": _text(control.get("selector")),
        "tag": _text(control.get("tag")),
        "id": _text(control.get("id")),
        "name_attr": _text(control.get("nameAttr", control.get("name_attr"))),
        "multiple": bool(control.get("multiple")),
    }


def _checked_controls(contract: dict[str, Any]) -> list[dict[str, Any]]:
    controls = contract.get("controls")
    if not isinstance(controls, list):
        return []
    return [_normalize_control(control) for control in controls if isinstance(control, dict)]


def _health_reports(
    health_check: dict[str, Any],
    primary_report: dict[str, Any],
) -> list[dict[str, Any]]:
    reports = health_check.get("reports")
    if isinstance(reports, list):
        normalized = [item for item in reports if isinstance(item, dict)]
        if normalized:
            return normalized
    return [primary_report] if primary_report else []


def _error_count(
    status: str,
    health_check: dict[str, Any],
    reports: list[dict[str, Any]],
) -> int:
    if status == "PASS":
        return 0
    try:
        declared = int(health_check.get("errorCount") or 0)
    except (TypeError, ValueError):
        declared = 0
    return max(1, declared, len(reports))


def _row_error_count(row: dict[str, str]) -> int:
    try:
        declared = int(row.get("error_count") or 0)
    except (TypeError, ValueError):
        declared = 0
    if declared > 0:
        return declared
    return 0 if row.get("status") == "PASS" else 1


def _diagnostic_details(
    status: str,
    health_check: dict[str, Any],
    report: dict[str, Any],
    contract: dict[str, Any],
    page_path: str,
) -> dict[str, Any]:
    diagnostics = report.get("diagnostics")
    diagnostics = dict(diagnostics) if isinstance(diagnostics, dict) else {}
    reports = _health_reports(health_check, report)
    if reports:
        diagnostics["errorCount"] = _error_count(status, health_check, reports)
        diagnostics["errors"] = reports
        return diagnostics
    if status == "PASS":
        controls = _checked_controls(contract)
        return {
            "result": "UI contract matched",
            "contract_path": page_path,
            "checked_control_count": len(controls),
            "checked_control_names": [control["name"] for control in controls if control["name"]],
        }
    if status == "CHECK_ERROR":
        return {
            "source": "background-health-check",
            "expected_page_url": "https://analytics.parivahan.gov.in/analytics/vahanpublicreport",
            "actual_page_url": _text(health_check.get("pageUrl")),
            "trigger": _text(health_check.get("trigger")),
            "error": _text(health_check.get("error")),
        }
    return {}


def row_from_health_check(health_check: dict[str, Any], page_url: str = "") -> dict[str, Any]:
    report = health_check.get("report")
    report = report if isinstance(report, dict) else {}
    checked_at = _text(health_check.get("checkedAt")) or datetime.now(timezone.utc).isoformat()
    status = _text(health_check.get("status")).strip().upper() or "CHECK_ERROR"
    contract = health_check.get("contract")
    contract = contract if isinstance(contract, dict) else {}
    reports = _health_reports(health_check, report)
    error_count = _error_count(status, health_check, reports)
    logged_page_url = _text(page_url or health_check.get("pageUrl"))
    diagnostics = report.get("diagnostics") if isinstance(report.get("diagnostics"), dict) else {}
    page_path = _text(
        contract.get("path")
        or diagnostics.get("path")
        or _path_from_url(logged_page_url)
    )
    controls = _checked_controls(contract)
    failure_type = "NONE" if status == "PASS" else "UI_DRIFT" if status == "UI_DRIFT" else status
    error_code = _text(report.get("code"))
    error_title = _text(report.get("title"))
    error = _text(health_check.get("error") or report.get("message") or report.get("title"))

    if error_count > 1 and error:
        error = f"Detected {error_count} UI errors. First error: {error}"

    if status == "CHECK_ERROR" and not error_code:
        error_code = "CHECK_ERROR"
    if status == "CHECK_ERROR" and not error_title:
        error_title = "UI check did not complete"
    if status == "PASS":
        error_code = ""
        error_title = ""
        error = ""

    return {
        "log_id": _text(
            health_check.get("checkId")
            or f"{checked_at}|{status}|{_text(health_check.get('trigger')) or 'unknown'}"
        ),
        "schema_version": LOG_SCHEMA_VERSION,
        "checked_at": checked_at,
        "check_date": _date_only(checked_at),
        "status": status,
        "failure_type": failure_type,
        "trigger": _text(health_check.get("trigger")),
        "started_at": _text(health_check.get("startedAt")),
        "duration_ms": _duration_ms(health_check.get("startedAt"), checked_at),
        "page_url": logged_page_url,
        "page_path": page_path,
        "contract_version": _text(contract.get("contractVersion")),
        "signature": _text(contract.get("signature")),
        "form_action": _text(contract.get("formAction")),
        "checked_controls": _json_text(controls, "[]"),
        "error_code": error_code,
        "error_count": error_count,
        "error_title": error_title,
        "error": error,
        "step": _text(report.get("step")),
        "target": _text(report.get("target")),
        "selector": _text(diagnostics.get("selector") or diagnostics.get("hiddenSelectId")),
        "expected": _text(report.get("expected")),
        "actual": _text(report.get("actual")),
        "diagnostic_details": _json_text(
            _diagnostic_details(status, health_check, report, contract, page_path)
        ),
        "action": _text(report.get("action")),
    }


def csv_cell(value: Any) -> str:
    return _text(value)


def to_csv(rows: list[dict[str, Any]]) -> str:
    from io import StringIO

    output = StringIO(newline="")
    writer = csv.DictWriter(
        output,
        fieldnames=COLUMNS,
        extrasaction="ignore",
        lineterminator="\r\n",
        quoting=csv.QUOTE_ALL,
    )
    writer.writeheader()
    writer.writerows({column: csv_cell(row.get(column)) for column in COLUMNS} for row in rows)
    return "\ufeff" + output.getvalue()


def file_name(chunk: dict[str, Any]) -> str:
    part_suffix = f"-part-{chunk['part']}" if int(chunk.get("part", 1)) > 1 else ""
    return f"report-{chunk['fromDate']}-to-{chunk['toDate']}{part_suffix}.csv"


def _empty_state() -> dict[str, Any]:
    return {
        "schemaVersion": LOG_SCHEMA_VERSION,
        "maxDaysPerFile": MAX_DAYS_PER_FILE,
        "maxBytesPerFile": MAX_BYTES_PER_FILE,
        "chunk": None,
        "lastAttemptedAt": None,
        "lastStoredAt": None,
        "lastFileName": None,
        "lastError": None,
    }


def _normalize_state(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict) or not isinstance(raw.get("chunk"), dict):
        return _empty_state()
    raw_chunk = raw["chunk"]
    rows = raw_chunk.get("rows")
    rows = [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []
    if not rows:
        return _empty_state()
    try:
        part = max(1, int(raw_chunk.get("part", 1)))
        from_date = _date_only(raw_chunk.get("fromDate"))
        to_date = _date_only(raw_chunk.get("toDate") or from_date)
        window_end_date = _date_only(
            raw_chunk.get("windowEndDate") or _add_days(from_date, MAX_DAYS_PER_FILE - 1)
        )
    except (TypeError, ValueError):
        return _empty_state()
    return {
        "schemaVersion": LOG_SCHEMA_VERSION,
        "maxDaysPerFile": MAX_DAYS_PER_FILE,
        "maxBytesPerFile": MAX_BYTES_PER_FILE,
        "chunk": {
            "fromDate": from_date,
            "toDate": to_date,
            "windowEndDate": window_end_date,
            "part": part,
            "rows": rows,
        },
        "lastAttemptedAt": raw.get("lastAttemptedAt"),
        "lastStoredAt": raw.get("lastStoredAt"),
        "lastFileName": raw.get("lastFileName"),
        "lastError": raw.get("lastError"),
    }


def _create_chunk(row: dict[str, Any], part: int = 1) -> dict[str, Any]:
    return {
        "fromDate": row["check_date"],
        "toDate": row["check_date"],
        "windowEndDate": _add_days(row["check_date"], MAX_DAYS_PER_FILE - 1),
        "part": part,
        "rows": [row],
    }


def _should_start_new_chunk(current: dict[str, Any] | None, row: dict[str, Any]) -> bool:
    if not current:
        return True
    try:
        row_day = _day_number(row["check_date"])
        from_day = _day_number(current["fromDate"])
        to_day = _day_number(current.get("windowEndDate") or current["toDate"])
    except (KeyError, TypeError, ValueError):
        return True
    if row_day < from_day or row_day > to_day:
        return True
    candidate = to_csv([*current.get("rows", []), row])
    return bool(current.get("rows")) and len(candidate.encode("utf-8")) > MAX_BYTES_PER_FILE


def _next_chunk(current: dict[str, Any] | None, row: dict[str, Any]) -> dict[str, Any]:
    if not _should_start_new_chunk(current, row):
        current_rows = list(current.get("rows", []))
        to_date = max(current["toDate"], row["check_date"])
        return {**current, "toDate": to_date, "rows": [*current_rows, row]}

    same_date_window = bool(current)
    if current:
        window_end = current.get("windowEndDate", current["toDate"])
        same_date_window = current["fromDate"] <= row["check_date"] <= window_end
    next_part = int(current.get("part", 1)) + 1 if same_date_window else 1
    return _create_chunk(row, next_part)


class UiHealthLogStore:
    def __init__(self, directory: str | Path) -> None:
        self.directory = Path(directory).expanduser()
        self._lock = asyncio.Lock()

    @property
    def state_path(self) -> Path:
        return self.directory / STATE_FILE_NAME

    def _read_state(self) -> dict[str, Any]:
        try:
            raw = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            return _empty_state()
        return _normalize_state(raw)

    def _write_state(self, state: dict[str, Any]) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        temporary = self.state_path.with_name(f".{self.state_path.name}.tmp")
        temporary.write_text(
            json.dumps(state, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(self.state_path)

    def _write_csv(self, path: Path, rows: list[dict[str, Any]]) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.tmp")
        temporary.write_bytes(to_csv(rows).encode("utf-8"))
        temporary.replace(path)

    def _read_csv_rows(self, path: Path) -> list[dict[str, str]]:
        with path.open("r", encoding="utf-8-sig", newline="") as stream:
            return [
                {column: str(row.get(column) or "") for column in COLUMNS}
                for row in csv.DictReader(stream)
            ]

    def _find_existing_log(self, log_id: str) -> dict[str, Any] | None:
        if not self.directory.exists() or not log_id:
            return None
        for path in self.directory.glob("report-*.csv"):
            if not _REPORT_FILE_RE.match(path.name):
                continue
            try:
                rows = self._read_csv_rows(path)
                if not any(row.get("log_id") == log_id for row in rows):
                    continue
                match = _REPORT_FILE_RE.match(path.name)
                if match is None:
                    continue
                return {
                    "ok": True,
                    "logId": log_id,
                    "fileName": path.name,
                    "rowCount": len(rows),
                    "fromDate": match.group("from"),
                    "toDate": match.group("to"),
                    "part": int(match.group("part") or 1),
                }
            except (OSError, csv.Error, UnicodeError):
                continue
        return None

    async def append(self, health_check: dict[str, Any], page_url: str = "") -> dict[str, Any]:
        async with self._lock:
            row = row_from_health_check(health_check, page_url)
            existing = self._find_existing_log(row["log_id"])
            if existing is not None:
                return existing
            state = self._read_state()
            current = state.get("chunk")
            chunk = _next_chunk(current, row)
            name = file_name(chunk)
            previous_name = file_name(current) if current else None
            same_chunk = bool(
                current
                and current.get("fromDate") == chunk.get("fromDate")
                and int(current.get("part", 1)) == int(chunk.get("part", 1))
            )
            pending = {
                **state,
                "chunk": chunk,
                "lastAttemptedAt": datetime.now(timezone.utc).isoformat(),
                "lastError": None,
            }
            try:
                self._write_csv(self.directory / name, chunk["rows"])
                if same_chunk and previous_name and previous_name != name:
                    (self.directory / previous_name).unlink(missing_ok=True)
                pending["lastStoredAt"] = datetime.now(timezone.utc).isoformat()
                pending["lastFileName"] = name
                self._write_state(pending)
            except OSError as error:
                pending["lastError"] = str(error)[:300]
                self._write_state(pending)
                raise
            return {
                "ok": True,
                "logId": row["log_id"],
                "fileName": name,
                "rowCount": len(chunk["rows"]),
                "fromDate": chunk["fromDate"],
                "toDate": chunk["toDate"],
                "part": int(chunk["part"]),
            }

    def _report_metadata(
        self,
        path: Path,
        rows: list[dict[str, str]],
        selected_date: str | None,
    ) -> dict[str, Any]:
        match = _REPORT_FILE_RE.match(path.name)
        if not match:
            raise ValueError(f"Invalid report filename: {path.name}")
        from_date = match.group("from")
        to_date = match.group("to")
        part = int(match.group("part") or 1)
        return {
            "fileName": path.name,
            "fromDate": from_date,
            "toDate": to_date,
            "part": part,
            "rowCount": len(rows),
            "sizeBytes": path.stat().st_size,
            "updatedAt": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(),
            "containsSelectedDate": bool(
                selected_date and any(row.get("check_date") == selected_date for row in rows)
            ),
            "downloadUrl": f"/api/ui-health/reports/{path.name}/download",
        }

    def _read_reports(
        self,
        selected_date: str | None,
    ) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
        if not self.directory.exists():
            return [], []
        reports: list[dict[str, Any]] = []
        all_rows: list[dict[str, str]] = []
        for path in self.directory.glob("report-*.csv"):
            if not _REPORT_FILE_RE.match(path.name):
                continue
            try:
                rows = self._read_csv_rows(path)
                reports.append(self._report_metadata(path, rows, selected_date))
                all_rows.extend(rows)
            except (OSError, csv.Error, UnicodeError):
                continue
        reports.sort(key=lambda item: (item["fromDate"], item["part"]), reverse=True)
        all_rows.sort(key=lambda row: row.get("checked_at", ""), reverse=True)
        return reports, all_rows

    async def list_reports(self, selected_date: str | None = None) -> dict[str, Any]:
        async with self._lock:
            reports, all_rows = self._read_reports(selected_date)
            by_date: dict[str, dict[str, Any]] = {}
            for row in all_rows:
                row_date = row.get("check_date", "")
                if not row_date:
                    continue
                summary = by_date.setdefault(
                    row_date,
                    {
                        "date": row_date,
                        "total": 0,
                        "pass": 0,
                        "dataChanged": 0,
                        "dataChangedErrors": 0,
                        "uiDrift": 0,
                        "uiDriftErrors": 0,
                        "checkError": 0,
                        "latestCheckedAt": "",
                    },
                )
                summary["total"] += 1
                status_key = {
                    "PASS": "pass",
                    "DATA_CHANGED": "dataChanged",
                    "UI_DRIFT": "uiDrift",
                    "CHECK_ERROR": "checkError",
                }.get(row.get("status"))
                if status_key:
                    summary[status_key] += 1
                if row.get("status") == "DATA_CHANGED":
                    summary["dataChangedErrors"] += _row_error_count(row)
                elif row.get("status") == "UI_DRIFT":
                    summary["uiDriftErrors"] += _row_error_count(row)
                summary["latestCheckedAt"] = max(
                    summary["latestCheckedAt"], row.get("checked_at", "")
                )

            available_dates = sorted(by_date.values(), key=lambda item: item["date"], reverse=True)
            actual_date = selected_date or (available_dates[0]["date"] if available_dates else None)
            selected_rows = [
                row for row in all_rows if row.get("check_date") == actual_date
            ]
            for report in reports:
                report["containsSelectedDate"] = bool(
                    actual_date
                    and report["fromDate"] <= actual_date <= report["toDate"]
                )
            return {
                "selectedDate": actual_date,
                "availableDates": available_dates,
                "reports": reports,
                "rows": selected_rows,
            }

    async def resolve_report(self, name: str) -> Path | None:
        async with self._lock:
            if Path(name).name != name or not _REPORT_FILE_RE.match(name):
                return None
            path = self.directory / name
            return path if path.is_file() else None

    async def clear(self) -> None:
        async with self._lock:
            if not self.directory.exists():
                return
            for path in self.directory.glob("report-*.csv"):
                path.unlink(missing_ok=True)
            self.state_path.unlink(missing_ok=True)

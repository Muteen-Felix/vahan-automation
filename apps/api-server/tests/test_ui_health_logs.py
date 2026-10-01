import json

from app.repositories.ui_health_log_store import COLUMNS, UiHealthLogStore


def health_check(checked_at: str, status: str = "PASS") -> dict:
    result = {
        "status": status,
        "trigger": "alarm",
        "startedAt": "2026-01-01T07:59:58.800Z",
        "checkedAt": checked_at,
        "contract": {
            "contractVersion": "v1",
            "signature": "healthy-signature",
            "path": "/analytics/vahanpublicreport",
            "formAction": "/analytics/vahanpublicreport",
            "controls": [
                {
                    "name": "fuel",
                    "selector": "#vehicleFuel",
                    "tag": "select",
                    "id": "vehicleFuel",
                    "nameAttr": "vehicleFuel",
                    "multiple": True,
                },
            ],
        },
    }
    if status == "CHECK_ERROR":
        result["error"] = "Timed out while loading the page."
    if status == "UI_DRIFT":
        result["report"] = {
            "code": "UI_DRIFT_REQUIRED_CONTROL",
            "step": "scheduled-health-check",
            "title": "Control bắt buộc bị thiếu hoặc bị trùng",
            "target": "Fuel (#vehicleFuel)",
            "expected": "DOM phải có đúng 1 control",
            "actual": "DOM đang có 0 control",
            "diagnostics": {"selector": "#vehicleFuel", "count": 0},
            "action": "Dev cần kiểm tra và cập nhật UI contract.",
        }
    return result


async def test_backend_csv_keeps_extension_schema_and_rolls_over_by_day(tmp_path) -> None:
    store = UiHealthLogStore(tmp_path / "logs")
    page_url = "https://analytics.parivahan.gov.in/analytics/vahanpublicreport?lang=en"

    await store.append(health_check("2026-01-01T08:00:00.000Z"), page_url)
    await store.append(health_check("2026-01-10T08:00:00.000Z"), page_url)
    await store.append(health_check("2026-01-11T08:00:00.000Z"), page_url)
    await store.append(health_check("2026-01-12T08:00:00.000Z", "CHECK_ERROR"), page_url)

    names = sorted(path.name for path in (tmp_path / "logs").glob("report-*.csv"))
    assert names == [
        "report-2026-01-01-to-2026-01-10.csv",
        "report-2026-01-11-to-2026-01-12.csv",
    ]

    report = await store.list_reports("2026-01-12")
    assert report["selectedDate"] == "2026-01-12"
    assert report["rows"][0]["status"] == "CHECK_ERROR"
    assert report["rows"][0]["error_code"] == "CHECK_ERROR"
    assert report["rows"][0]["error"] == "Timed out while loading the page."
    assert len(report["availableDates"]) == 4
    assert report["availableDates"][0]["date"] == "2026-01-12"
    assert report["availableDates"][0]["checkError"] == 1
    assert report["availableDates"][0]["uiDriftErrors"] == 0
    assert report["reports"][0]["containsSelectedDate"] is True

    csv_content = (tmp_path / "logs" / names[1]).read_text(encoding="utf-8-sig")
    assert csv_content.splitlines()[0].split(",") == [f'"{column}"' for column in COLUMNS]
    assert len(COLUMNS) == 26


async def test_backend_csv_rolls_over_when_file_reaches_size_limit(tmp_path) -> None:
    store = UiHealthLogStore(tmp_path / "logs")
    large_check = health_check("2026-02-01T08:00:00.000Z", "UI_DRIFT")
    large_check["report"]["diagnostics"]["details"] = "x" * 550_000

    first = await store.append(large_check)
    second_check = health_check("2026-02-02T08:00:00.000Z")
    second = await store.append(second_check)

    assert first["fileName"] == "report-2026-02-01-to-2026-02-01.csv"
    assert second["fileName"] == "report-2026-02-02-to-2026-02-02-part-2.csv"
    assert second["rowCount"] == 1


async def test_backend_csv_deduplicates_retried_log_id(tmp_path) -> None:
    store = UiHealthLogStore(tmp_path / "logs")
    check = health_check("2026-03-01T08:00:00.000Z")
    check["checkId"] = "retry-safe-id"

    first = await store.append(check)
    second = await store.append(check)
    report = await store.list_reports("2026-03-01")

    assert second == first
    assert report["availableDates"][0]["total"] == 1
    assert len(report["rows"]) == 1


async def test_backend_csv_keeps_id_change_diagnostic_for_developer_analysis(tmp_path) -> None:
    store = UiHealthLogStore(tmp_path / "logs")
    check = health_check("2026-03-02T08:00:00.000Z", "UI_DRIFT")
    check["checkId"] = "fuel-id-renamed"
    check["report"] = {
        **check["report"],
        "actual": "DOM đang có 0 control",
        "diagnostics": {
            "name": "fuel",
            "selector": "#vehicleFuel",
            "count": 0,
            "mutation": "id changed from vehicleFuel to vehicleFuelRenamed",
        },
    }

    await store.append(
        check,
        "https://analytics.parivahan.gov.in/analytics/vahanpublicreport?lang=en",
    )
    report = await store.list_reports("2026-03-02")
    row = report["rows"][0]

    assert row["status"] == "UI_DRIFT"
    assert row["failure_type"] == "UI_DRIFT"
    assert row["error_code"] == "UI_DRIFT_REQUIRED_CONTROL"
    assert row["selector"] == "#vehicleFuel"
    assert row["expected"] == "DOM phải có đúng 1 control"
    assert row["actual"] == "DOM đang có 0 control"
    assert '"mutation":"id changed from vehicleFuel to vehicleFuelRenamed"' in row["diagnostic_details"]


async def test_backend_csv_preserves_multiple_ui_drift_reports(tmp_path) -> None:
    store = UiHealthLogStore(tmp_path / "logs")
    check = health_check("2026-03-03T08:00:00.000Z", "UI_DRIFT")
    reports = [
        {
            **check["report"],
            "target": target,
            "diagnostics": {"selector": selector, "count": 0},
        }
        for selector, target in (
            ("#vehicleCategoryGroup", "Category Group"),
            ("#vehicleFuel", "Fuel"),
            ("#yAxis", "Y-Axis"),
            ("#xAxis", "X-Axis"),
            ("#externalCaptcha", "CAPTCHA"),
            ("#applyTrigger", "Apply"),
            ("#archivedFlags", "Archived Flag"),
            ("#reportType", "Report Type"),
            ("#financialYearSelect", "Financial Year"),
            ("#reportYear", "Report Year"),
        )
    ]
    check["checkId"] = "multi-ui-drift"
    check["report"] = reports[0]
    check["reports"] = reports
    check["errorCount"] = len(reports)

    await store.append(check, "https://analytics.parivahan.gov.in/analytics/vahanpublicreport?lang=en")
    report = await store.list_reports("2026-03-03")
    row = report["rows"][0]
    details = json.loads(row["diagnostic_details"])

    assert row["status"] == "UI_DRIFT"
    assert row["error_code"] == "UI_DRIFT_REQUIRED_CONTROL"
    assert row["error_count"] == "10"
    assert row["error"].startswith("Phát hiện 10 lỗi UI.")
    assert details["errorCount"] == 10
    assert len(details["errors"]) == 10
    assert report["availableDates"][0]["uiDrift"] == 1
    assert report["availableDates"][0]["uiDriftErrors"] == 10
    assert [item["diagnostics"]["selector"] for item in details["errors"]] == [
        "#vehicleCategoryGroup",
        "#vehicleFuel",
        "#yAxis",
        "#xAxis",
        "#externalCaptcha",
        "#applyTrigger",
        "#archivedFlags",
        "#reportType",
        "#financialYearSelect",
        "#reportYear",
    ]

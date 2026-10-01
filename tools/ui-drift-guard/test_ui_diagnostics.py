"""Unit checks for precise UI-drift notifications."""

from __future__ import annotations

from ui_contract import UIDriftError, format_ui_drift


def run() -> None:
    cases = [
        (
            "missing fuel",
            UIDriftError(
                "UI_DRIFT_REQUIRED_CONTROL",
                "fuel missing",
                step="preflight",
                details={"control": "fuel", "selector": "#vehicleFuel", "count": 0},
            ),
            "Fuel (#vehicleFuel)",
            "DOM đang có 0 control",
        ),
        (
            "renamed category option",
            UIDriftError(
                "UI_DRIFT_REQUIRED_OPTION",
                "Two Wheeler missing",
                step="option-contract",
                details={"control": "category", "expected_option": "Two Wheeler"},
            ),
            "Category Group (#vehicleCategoryGroup)",
            "option này đã bị xóa, đổi tên hoặc chưa được tải",
        ),
        (
            "fuel wrapper moved",
            UIDriftError(
                "UI_DRIFT_MULTISELECT_WRAPPER",
                "wrapper mismatch",
                step="filter",
                details={"hidden_select_id": "vehicleFuel", "wrapper_count": 0},
            ),
            "Fuel (#vehicleFuel)",
            "Tìm thấy 0 wrapper",
        ),
        (
            "category selection not synced",
            UIDriftError(
                "UI_DRIFT_SELECTION_NOT_SYNCED",
                "selection mismatch",
                step="Category Group",
                details={
                    "label": "Category Group",
                    "option": "Two Wheeler",
                    "selected": [],
                },
            ),
            "Category Group > option 'Two Wheeler'",
            "Select gốc đang có: không có dữ liệu",
        ),
        (
            "axis hidden field mismatch",
            UIDriftError(
                "UI_DRIFT_AXIS_NOT_SYNCED",
                "axis mismatch",
                step="axis",
                details={"expected": "vehicleFuel", "actual": "vehicleCategoryGroup"},
            ),
            "Y-Axis/X-Axis và hidden fields",
            "Expected=vehicleFuel; Actual=vehicleCategoryGroup",
        ),
    ]

    for name, error, expected_target, expected_actual in cases:
        report = format_ui_drift(error)
        assert report["target"] == expected_target, (name, report)
        assert expected_target in report["message"], (name, report)
        assert expected_actual in report["actual"], (name, report)
        if error.code == "UI_DRIFT_REQUIRED_OPTION":
            assert "Two Wheeler" in report["expected"], (name, report)
        for field in ("code", "step", "title", "expected", "actual", "action", "message"):
            assert report[field], (name, field, report)
        print(f"DIAGNOSTIC {name} PASS target={report['target']}")


if __name__ == "__main__":
    run()

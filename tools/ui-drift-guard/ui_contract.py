"""Runtime contract checks for the VAHAN report page.

The report page is an external system, so selector failures must be treated as
UI drift rather than as ordinary retries.  This module keeps the checks small,
deterministic, and independent from the business flow.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from playwright.sync_api import Locator, Page


UI_CONTRACT_VERSION = "v1"
REPORT_PATH_FRAGMENT = "/analytics/vahanpublicreport"


class UIDriftError(RuntimeError):
    """Raised when the page no longer matches a supported UI contract."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        step: str = "preflight",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.step = step
        self.details = details or {}


REQUIRED_CONTROLS = {
    "form": "#vahanPublicForm",
    "category": "#vehicleCategoryGroup",
    "fuel": "#vehicleFuel",
    "yaxis": "#yAxis",
    "xaxis": "#xAxis",
    "captcha": "#externalCaptcha",
    "apply": "#applyTrigger",
}


def normalize_text(value: str | None) -> str:
    """Normalize labels while preserving meaningful punctuation."""

    return " ".join((value or "").split()).strip().casefold()


_UI_CONTROL_LABELS = {
    "form": "form VAHAN Public Report (#vahanPublicForm)",
    "category": "Category Group (#vehicleCategoryGroup)",
    "vehicleCategoryGroup": "Category Group (#vehicleCategoryGroup)",
    "fuel": "Fuel (#vehicleFuel)",
    "vehicleFuel": "Fuel (#vehicleFuel)",
    "yaxis": "Y-Axis (#yAxis)",
    "yAxis": "Y-Axis (#yAxis)",
    "xaxis": "X-Axis (#xAxis)",
    "xAxis": "X-Axis (#xAxis)",
    "captcha": "ô CAPTCHA (#externalCaptcha)",
    "apply": "nút Apply (#applyTrigger)",
    "externalCaptcha": "ô CAPTCHA (#externalCaptcha)",
    "applyTrigger": "nút Apply (#applyTrigger)",
}


def _display_diagnostic_value(value: Any, *, max_length: int = 180) -> str:
    """Convert diagnostic metadata to short, safe user-facing text."""

    if value is None or value == "":
        return "không có dữ liệu"
    if isinstance(value, (list, tuple, set)):
        value = ", ".join(str(item) for item in value)
    text = str(value)
    if not text:
        return "không có dữ liệu"
    if len(text) > max_length:
        return f"{text[: max_length - 1]}…"
    return text


def _diagnostic_target(details: dict[str, Any], step: str) -> str:
    """Resolve a stable, human-readable location from error metadata."""

    key = details.get("control") or details.get("name")
    if key in _UI_CONTROL_LABELS:
        return _UI_CONTROL_LABELS[key]

    hidden_select_id = details.get("hidden_select_id")
    if hidden_select_id:
        clean_id = str(hidden_select_id).removeprefix("#")
        return _UI_CONTROL_LABELS.get(clean_id, f"control #{clean_id}")

    label = details.get("label")
    if label:
        return _display_diagnostic_value(label)

    selector = details.get("selector")
    if selector:
        return f"control {selector}"

    return step or "preflight"


def format_ui_drift(error: UIDriftError) -> dict[str, str]:
    """Create a precise user/developer notification for a UI drift error.

    The returned metadata deliberately contains only structural diagnostics. It
    never includes page HTML, CAPTCHA values, or credentials.
    """

    code = error.code
    details = error.details or {}
    target = _diagnostic_target(details, error.step)
    count = details.get("count")

    if code == "UI_DRIFT_REQUIRED_CONTROL":
        title = "Control bắt buộc bị thiếu hoặc bị trùng"
        expected = "DOM phải có đúng 1 control"
        actual = f"DOM đang có {count if count is not None else 'không xác định'} control"
    elif code == "UI_DRIFT_CONTROL_TYPE":
        title = "Loại control đã thay đổi"
        expected = _display_diagnostic_value(details.get("expected"), max_length=100)
        actual = _display_diagnostic_value(
            details.get("actual") or "control không còn là multi-select (thiếu thuộc tính multiple)"
        )
    elif code == "UI_DRIFT_REQUIRED_OPTION":
        option = _display_diagnostic_value(
            details.get("expected_option") or details.get("option")
        )
        title = "Thiếu lựa chọn bắt buộc"
        expected = f"option '{option}' phải tồn tại"
        actual = details.get(
            "actual",
            "option này đã bị xóa, đổi tên hoặc chưa được tải",
        )
    elif code == "UI_DRIFT_EMPTY_OPTIONS":
        title = "Danh sách lựa chọn đang rỗng"
        expected = "Có ít nhất 1 option để tiếp tục"
        actual = f"DOM đang có {details.get('option_count', 0)} option"
    elif code == "UI_DRIFT_MULTISELECT_WRAPPER":
        title = "Wrapper multiselect đã thay đổi vị trí hoặc số lượng"
        expected = "Có đúng 1 wrapper trong cùng form-group với select gốc"
        actual = f"Tìm thấy {details.get('wrapper_count', 'không xác định')} wrapper"
    elif code == "UI_DRIFT_WRONG_PAGE":
        target = "trang VAHAN Public Report"
        title = "Đang ở sai trang"
        expected = f"URL phải chứa {REPORT_PATH_FRAGMENT}"
        actual = _display_diagnostic_value(details.get("url"))
    elif code == "UI_DRIFT_CHANGED_DURING_RUN":
        target = "cấu trúc UI trong lúc flow đang chạy"
        title = "UI thay đổi giữa hai bước kiểm tra"
        expected = f"signature={_display_diagnostic_value(details.get('expected_signature'))}"
        actual = f"signature={_display_diagnostic_value(details.get('actual_signature'))}"
    elif code == "UI_DRIFT_OPTION_NOT_UNIQUE":
        target = f"{_display_diagnostic_value(details.get('label'))} > option '{_display_diagnostic_value(details.get('target'))}'"
        title = "Option không còn duy nhất"
        expected = "Tìm thấy đúng 1 option khớp"
        actual = f"Tìm thấy {count if count is not None else 'không xác định'} kết quả"
    elif code == "UI_DRIFT_ALL_OPTION_NOT_FOUND":
        target = f"{_display_diagnostic_value(details.get('label'))} > checkbox All"
        title = "Checkbox All đã thay đổi hoặc bị mất"
        expected = "Có đúng 1 checkbox All"
        actual = f"Tìm thấy {count if count is not None else 'không xác định'} checkbox"
    elif code == "UI_DRIFT_SEARCH_INPUT":
        target = f"ô tìm kiếm của {_display_diagnostic_value(details.get('label'))}"
        title = "Ô tìm kiếm multiselect không đúng"
        expected = "Có đúng 1 ô tìm kiếm"
        actual = f"Tìm thấy {count if count is not None else 'không xác định'} ô"
    elif code == "UI_DRIFT_OPTION_CONTROL":
        target = f"option '{_display_diagnostic_value(details.get('option'))}' trong {_display_diagnostic_value(details.get('label'))}"
        title = "Control của option đã thay đổi"
        expected = "Có đúng 1 checkbox cho option"
        actual = f"Tìm thấy {details.get('checkbox_count', 'không xác định')} checkbox"
    elif code == "UI_DRIFT_SELECTION_NOT_SYNCED":
        target = f"{_display_diagnostic_value(details.get('label'))} > option '{_display_diagnostic_value(details.get('option'))}'"
        title = "Widget và select gốc không đồng bộ"
        expected = "Checkbox và option gốc cùng được chọn"
        actual = f"Select gốc đang có: {_display_diagnostic_value(details.get('selected'))}"
    elif code == "UI_DRIFT_SELECT_ALL_NOT_SYNCED":
        target = f"{_display_diagnostic_value(details.get('label'))} > checkbox All"
        title = "Lựa chọn All không đồng bộ"
        expected = f"Đã chọn đủ {details.get('option_count', 'tất cả')} option"
        actual = f"Đã chọn {details.get('selected_count', 'không xác định')} option"
    elif code == "UI_DRIFT_AXIS_NOT_SYNCED":
        target = "Y-Axis/X-Axis và hidden fields"
        title = "Giá trị trục báo cáo không đồng bộ"
        expected = "Hidden fields khớp giá trị đang hiển thị"
        if details.get("expected") is not None or details.get("actual") is not None:
            actual = (
                f"Expected={_display_diagnostic_value(details.get('expected'))}; "
                f"Actual={_display_diagnostic_value(details.get('actual'))}"
            )
        else:
            actual = (
                f"yAxis={_display_diagnostic_value(details.get('yAxis_hidden'))}; "
                f"xAxis={_display_diagnostic_value(details.get('xAxis_hidden'))}"
            )
    elif code in {"UI_DRIFT_CONTRACT_TIMEOUT", "UI_DRIFT_DYNAMIC_CONTROL_TIMEOUT"}:
        title = "UI contract không sẵn sàng đúng hạn"
        expected = "Các control cần thiết xuất hiện trong thời gian cho phép"
        actual = f"Timeout tại bước {_display_diagnostic_value(error.step)}"
    elif code == "UI_DRIFT_STALE_FLOW_STATE":
        target = "trạng thái flow đã lưu"
        title = "Flow cũ không còn đủ thông tin contract"
        expected = "Có signature UI contract hợp lệ"
        actual = "Không có signature"
    else:
        title = "Cấu trúc UI không khớp contract"
        expected = "Trang khớp UI contract đã được kiểm thử"
        actual = f"Mã lỗi {code}"

    message = (
        f"Phát hiện thay đổi tại {target}: {title}. "
        "Tool đã dừng để tránh thao tác sai dữ liệu."
    )
    action = (
        "Dev cần kiểm tra đúng vùng này, cập nhật selector/adapter và chạy lại kiểm thử UI được phê duyệt; "
        "người dùng không cần nhập lại dữ liệu cho đến khi tool được cập nhật."
    )
    return {
        "code": code,
        "step": error.step,
        "title": title,
        "target": target,
        "expected": expected,
        "actual": actual,
        "action": action,
        "message": message,
    }


def _count(locator: Locator) -> int:
    return locator.count()


def _require_one(page: Page, selector: str, name: str, step: str) -> Locator:
    locator = page.locator(selector)
    count = _count(locator)
    if count != 1:
        raise UIDriftError(
            "UI_DRIFT_REQUIRED_CONTROL",
            f"Không tìm thấy duy nhất control bắt buộc '{name}' ({selector}), count={count}.",
            step=step,
            details={"control": name, "selector": selector, "count": count},
        )
    return locator


def _option_labels(locator: Locator) -> list[str]:
    options = locator.locator("option")
    labels: list[str] = []
    for index in range(options.count()):
        option = options.nth(index)
        labels.append(
            normalize_text(option.get_attribute("label") or option.inner_text())
        )
    return labels


def get_dropdown_container(page: Page, hidden_select_id: str, *, step: str = "filter") -> Locator:
    """Resolve a multiselect wrapper inside the same field group as its select.

    The previous implementation used ``following::div[1]`` across the whole
    document.  That works only while the vendor keeps the generated widget in
    the same DOM order.  Scoping to the field group prevents a newly inserted
    dropdown elsewhere on the page from being selected accidentally.
    """

    hidden = _require_one(page, f"#{hidden_select_id}", hidden_select_id, step)
    group = hidden.locator(
        "xpath=ancestor::div[contains(concat(' ', normalize-space(@class), ' '), ' form-group ')][1]"
    )
    candidates = group.locator("div.multiselect-dropdown")
    count = candidates.count()

    if count != 1:
        # Keep a narrowly scoped parent fallback for minor wrapper changes.  It
        # is still constrained to the select's immediate parent, never the
        # whole document.
        parent_candidates = hidden.locator("xpath=..").locator("div.multiselect-dropdown")
        if parent_candidates.count() == 1:
            candidates = parent_candidates
            count = 1

    if count != 1:
        raise UIDriftError(
            "UI_DRIFT_MULTISELECT_WRAPPER",
            f"Không xác định được widget multiselect duy nhất cho #{hidden_select_id}, count={count}.",
            step=step,
            details={"hidden_select_id": hidden_select_id, "wrapper_count": count},
        )

    return candidates.first


def _stable_control_fingerprint(page: Page, step: str) -> list[dict[str, Any]]:
    fingerprint: list[dict[str, Any]] = []
    for name, selector in REQUIRED_CONTROLS.items():
        locator = _require_one(page, selector, name, step)
        fingerprint.append(
            {
                "name": name,
                "selector": selector,
                "tag": locator.evaluate("el => el.tagName.toLowerCase()"),
                "id": locator.get_attribute("id"),
                "name_attr": locator.get_attribute("name"),
                "multiple": locator.get_attribute("multiple") is not None,
            }
        )
    return fingerprint


def _signature(fingerprint: list[dict[str, Any]]) -> str:
    canonical = json.dumps(fingerprint, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def assert_ui_contract(
    page: Page,
    *,
    step: str = "preflight",
    expected_signature: str | None = None,
) -> dict[str, Any]:
    """Validate the supported page contract and return a safe diagnostic snapshot."""

    if REPORT_PATH_FRAGMENT not in page.url:
        raise UIDriftError(
            "UI_DRIFT_WRONG_PAGE",
            "Trang hiện tại không phải VAHAN Public Report; automation đã dừng.",
            step=step,
            details={"url": page.url},
        )

    form = _require_one(page, REQUIRED_CONTROLS["form"], "form", step)
    fingerprint = _stable_control_fingerprint(page, step)

    for name in ("category", "fuel"):
        control = page.locator(REQUIRED_CONTROLS[name])
        if control.get_attribute("multiple") is None:
            raise UIDriftError(
                "UI_DRIFT_CONTROL_TYPE",
                f"Control {name} không còn là multi-select như contract {UI_CONTRACT_VERSION}.",
                step=step,
                details={
                    "control": name,
                    "expected": "multiple select",
                    "actual": "control không còn thuộc tính multiple",
                },
            )

    category_options = _option_labels(page.locator("#vehicleCategoryGroup"))
    if normalize_text("Two Wheeler") not in category_options:
        raise UIDriftError(
            "UI_DRIFT_REQUIRED_OPTION",
            "Không tìm thấy option Category Group 'Two Wheeler'.",
            step=step,
            details={"control": "category", "expected_option": "Two Wheeler"},
        )

    if page.locator("#vehicleFuel option").count() == 0:
        raise UIDriftError(
            "UI_DRIFT_EMPTY_OPTIONS",
            "Danh sách Fuel đang rỗng hoặc chưa được tải.",
            step=step,
            details={"control": "fuel", "option_count": 0},
        )

    yaxis_options = _option_labels(page.locator("#yAxis"))
    if normalize_text("Fuel") not in yaxis_options:
        raise UIDriftError(
            "UI_DRIFT_REQUIRED_OPTION",
            "Không tìm thấy option Y-Axis 'Fuel'.",
            step=step,
            details={"control": "yaxis", "expected_option": "Fuel"},
        )

    # Validate wrapper association without relying on global DOM order.
    get_dropdown_container(page, "vehicleCategoryGroup", step=step)
    get_dropdown_container(page, "vehicleFuel", step=step)

    signature = _signature(fingerprint)
    snapshot = {
        "contract_version": UI_CONTRACT_VERSION,
        "signature": signature,
        "url_path": page.url.split("?", 1)[0],
        "controls": fingerprint,
        "form_action": form.get_attribute("action"),
    }

    if expected_signature and expected_signature != signature:
        raise UIDriftError(
            "UI_DRIFT_CHANGED_DURING_RUN",
            "Cấu trúc UI đã thay đổi trong lúc flow đang chạy; dữ liệu chưa được xác nhận.",
            step=step,
            details={"expected_signature": expected_signature, "actual_signature": signature},
        )

    return snapshot


def find_dropdown_option(container: Locator, target_text: str, *, label: str, step: str) -> Locator:
    """Find exactly one custom-dropdown option by normalized attribute/label."""

    target = normalize_text(target_text)
    candidates = container.locator("[data-search-text]")
    matches: list[Locator] = []
    for index in range(candidates.count()):
        candidate = candidates.nth(index)
        data_text = normalize_text(candidate.get_attribute("data-search-text"))
        visible_text = normalize_text(candidate.inner_text())
        if target in (data_text, visible_text):
            matches.append(candidate)

    if len(matches) != 1:
        raise UIDriftError(
            "UI_DRIFT_OPTION_NOT_UNIQUE",
            f"Không tìm thấy duy nhất option '{target_text}' trong {label}, count={len(matches)}.",
            step=step,
            details={"label": label, "target": target_text, "count": len(matches)},
        )
    return matches[0]


def find_all_checkbox(container: Locator, *, label: str, step: str) -> Locator:
    """Find the select-all checkbox by its visible label, with a class fallback."""

    candidates = container.locator("input[type='checkbox']")
    matches: list[Locator] = []
    for index in range(candidates.count()):
        candidate = candidates.nth(index)
        parent_text = normalize_text(candidate.locator("xpath=..").inner_text())
        if parent_text == normalize_text("All"):
            matches.append(candidate)

    if len(matches) != 1:
        fallback = container.locator("div.multiselect-dropdown-all-selector input[type='checkbox']")
        if fallback.count() == 1:
            return fallback.first
        raise UIDriftError(
            "UI_DRIFT_ALL_OPTION_NOT_FOUND",
            f"Không tìm thấy checkbox All duy nhất trong {label}.",
            step=step,
            details={"label": label, "count": len(matches)},
        )
    return matches[0]

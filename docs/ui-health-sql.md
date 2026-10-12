# UI Health và preflight

Runner Playwright kiểm form/control theo contract trước thao tác VAHAN.
API lưu trạng thái/diagnostics trong PostgreSQL. `blocked` là kết quả kiểm
contract, không tự xóa chỉ vì runner disconnect hoặc UI reload.
Khi gate không đạt, không Apply/cấp run mới để vượt preflight.

`GET /api/ui-health/status` đọc trạng thái; `POST /api/ui-health/preflight`
kiểm gate. Giao diện chỉ hiện lỗi khi có vấn đề và cho copy/download diagnostics.
Không có lịch UI Health riêng hay nút run-now; hai API cũ trả 404.

Chứng chỉ TLS là kiểm tra riêng: CA install trong image chưa chứng minh
`page.goto` Chromium thành công. [Probe trong runner image](runbook.md) không
bỏ qua TLS. Lỗi VAHAN live phải được ghi là chưa kiểm report end-to-end,
không được thay bằng kết quả fixture xanh.

Source chính: `apps/browser-runner/ui-health-contract.mjs`,
`apps/api-server/app/repositories/ui_contract.py`,
`apps/api-server/app/api/ui_health.py` và `tools/ui-drift-guard/`.
Xem [defect và bằng chứng](round5-review-evidence.md).

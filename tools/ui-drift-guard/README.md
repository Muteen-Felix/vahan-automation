# Developer UI Drift Checks

Đây là bộ kiểm tra Playwright dành cho Dev/CI, được tách khỏi code MVP. Nó
kiểm tra trang VAHAN Public Report ở chế độ chỉ đọc và tạo diagnostic chi tiết
khi contract không còn khớp.

Các file:

- `ui_contract.py`: selector contract, signature và lỗi `UI_DRIFT_*`.
- `test_ui_contract.py`: smoke test live; không nhập CAPTCHA, không Apply.
- `test_ui_diagnostics.py`: kiểm tra format lỗi và vị trí lỗi.

Chạy từ thư mục này để import module local:

```bash
cd tools/ui-drift-guard
python3 test_ui_diagnostics.py
python3 test_ui_contract.py
```

Health check của extension gửi kết quả về `POST /api/ui-health/logs`; backend
lưu CSV runtime ở `apps/api-server/runtime/ui-health-logs`. Hai bộ kiểm tra dùng
cùng vocabulary diagnostic nhưng không phụ thuộc vào nhau, giúp giảm conflict
khi Dev sửa controller MVP.

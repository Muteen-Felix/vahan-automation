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

Health check do Playwright worker chạy gửi kết quả về `POST /api/ui-health/logs`;
API lưu dữ liệu trong PostgreSQL và tạo CSV khi người dùng tải báo cáo. Bộ kiểm
tra Dev/CI ở đây dùng cùng vocabulary diagnostic để phát hiện thay đổi giao diện
trước khi cập nhật worker.

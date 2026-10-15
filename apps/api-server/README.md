# VAHAN API

FastAPI + Socket.IO + PostgreSQL; runtime repositories ở `app/repositories/postgres.py` và `file_store.py`. Không dùng RAM/filesystem làm nơi lưu chính.

Khởi chạy, migration, backup và import: xem [README gốc](../../README.md) và [mô tả SQL](../../docs/postgres-playwright.md).

## Chạy nhanh test API trên Windows

Trong PowerShell, từ thư mục `apps/api-server`, chạy:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\test-quick.ps1
```

Script tạo PostgreSQL tạm chỉ bind vào loopback, chạy migration và `tests/test_api_handlers.py`, rồi xóa container. Có thể truyền `-TestPath tests` để chạy toàn bộ test API cốt lõi. Test cần database riêng có hậu tố `_test` và cờ `VAHAN_ALLOW_DATABASE_CLEAR=test-only`; không chạy các fixture này trên database ứng dụng.

## Chạy toàn bộ kiểm thử API

Để chạy các kiểm thử API native, toàn bộ test API và PostgreSQL integration trong workflow CI, kiểm tra coverage tối thiểu 90.1%, cùng lint và đăng ký test, chạy trong PowerShell từ thư mục `apps/api-server`:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\test-api-all.ps1
```

Script dùng PostgreSQL container tạm, bind vào loopback và tự dọn container cũng như dữ liệu coverage khi hoàn tất. Các suite browser-runner và web UI chạy độc lập trong workflow CI.

Namespace `/ui` dùng session tài khoản; `/runner` dùng token riêng của Playwright worker với `engine=playwright`. API chạy một worker Uvicorn.

Mỗi filter ghi trực tiếp vào `main_reports` với 12 cột tháng qua `POST /api/jobs/{id}/main-report`; transaction đồng thời lưu `report_update_history`, hoàn tất job và giải phóng worker. Không lưu bản sao bảng DOM/Excel. Migration 0004 kiểm tra dữ liệu và lịch sử trước khi bỏ bảng phụ. Xem [flow và kiểm thử](../../docs/annual-reports.md).

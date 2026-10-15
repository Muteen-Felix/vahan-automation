# VAHAN API

FastAPI + Socket.IO + PostgreSQL; runtime repositories ở `app/repositories/postgres.py` và `file_store.py`. Không dùng RAM/filesystem làm nơi lưu chính.

Khởi chạy, migration, backup và import: xem [README gốc](../../README.md) và [mô tả SQL](../../docs/postgres-playwright.md).

Namespace `/ui` dùng session tài khoản; `/runner` dùng token riêng của Playwright worker với `engine=playwright`. API chạy một worker Uvicorn.

Mỗi filter ghi trực tiếp vào `main_reports` với 12 cột tháng qua `POST /api/jobs/{id}/main-report`; transaction đồng thời lưu `report_update_history`, hoàn tất job và giải phóng worker. Không lưu bản sao bảng DOM/Excel. Migration 0004 kiểm tra dữ liệu và lịch sử trước khi bỏ bảng phụ. Xem [flow và kiểm thử](../../docs/annual-reports.md).

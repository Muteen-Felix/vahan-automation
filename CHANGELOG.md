# Changelog

Định dạng theo [Keep a Changelog](https://keepachangelog.com/vi/1.1.0/). Phiên bản theo D-09: `1.0.0`; image tag = version;
nhãn OCI `org.opencontainers.image.version` = `1.0.0`, `org.opencontainers.image.revision` = SHA commit của gói.

Tệp này mô tả **thay đổi trong source**. Kết quả kiểm chứng (E2E, D3 trên VAHAN thật, nâng cấp tại chỗ) nằm ở ledger và
log trong gói bàn giao, không nằm ở đây. Rủi ro còn lại: `docs/release/known-issues.md`.

## [1.0.0] — ứng viên release (ngày phát hành ghi khi gắn tag)

### Thêm

- Lịch chạy báo cáo **Once** và **Monthly**, chọn múi giờ Việt Nam hoặc Ấn Độ; ETA, tiến độ và giờ kết thúc dự kiến trên lịch.
- Trang **Run History** (admin): mỗi lần chạy một dòng, tên bộ lọc giữ nguyên sau khi xóa hoặc đổi tên lịch.
- Export Excel đủ mọi bản ghi khớp bộ lọc State/RTO, có bước xác nhận; **Export all** cũng có xác nhận.
- Runner tự nhận việc; launcher `auto` chọn số runner theo CPU/RAM.
- Mất kết nối VAHAN: lịch tạm dừng và **tự tiếp tục** khi mạng ổn định. Lịch bị tạm dừng thủ công thì không tự tiếp tục.
- Bảng báo cáo năm hiển thị trạng thái cập nhật dữ liệu và thời điểm cập nhật gần nhất.
- Gói cài từ image đã đóng sẵn (`docker load`): image tag `1.0.0`, nhãn OCI revision/version, manifest ghi version và SHA,
  `SHA256SUMS`, CHANGELOG trong source ZIP.
- Service `migrate` (owner DB) chạy migration rồi cấp quyền DML cho role runtime; API production từ chối chạy bằng role có quyền DDL.
- `/api/ready` kiểm revision migration; bộ kiểm tra smoke `scripts/release-smoke.py`.

### Thay đổi

- `POST /api/annual-reports/coverage` trả **tiến độ của lần chạy gần nhất** (tổng, đã xử lý, có dữ liệu, không dữ liệu, lỗi,
  đang chờ, đang chạy, trạng thái) theo năm và bộ lọc; dữ liệu tháng đã lưu không được tính là tiến độ.
- Khối tiến độ cập nhật báo cáo hiển thị cho **mọi người dùng** (kể cả member) và luôn hiện; chưa có lần chạy thì báo
  "No update run is available for this report yet.".
- Thông báo "Report saved" thay bằng trạng thái dữ liệu; nút tạo lịch đổi nhãn thành "Create schedule"; export có hộp xác nhận
  trong ứng dụng thay cho hộp thoại trình duyệt.
- PostgreSQL dùng **image chính thức pin theo digest**; image tự build bị bỏ.
- Python cài từ `requirements.lock` có hash; base image pin digest.
- Phiên bản đồng bộ `1.0.0`: `apps/api-server/pyproject.toml`, `apps/web-ui/package.json`, `apps/browser-runner/package.json`
  và hai `package-lock.json`.

### Phát triển và kiểm thử

- Bộ unit test handler API (`apps/api-server/tests/test_api_handlers.py`) và hai script chạy nhanh trên Windows
  (`apps/api-server/scripts/test-quick.ps1`, `test-api-all.ps1`).
- Công cụ `coverage` (chỉ môi trường phát triển/CI, thêm vào `requirements-dev.lock`; không nằm trong image): CI yêu cầu độ phủ
  `app/api` tối thiểu 90,1%.

### Gỡ bỏ

- Lịch **Daily**. Migration `0014a_daily_schedule_guard` dừng cả lần nâng cấp nếu còn lịch Daily có session; migration
  `0015_remove_daily_schedules` xóa các lịch Daily còn lại và ghi audit.
- Maker Update (`/api/maker-updates*`, `updateKind`), `upload-excel`, `GET`/`PUT /api/ui-health/schedule`, `POST /api/ui-health/run-now`.
- Log OCR thô; ô nhập số worker trên web.

### Bảo mật

- nginx: `server_tokens off` (không lộ phiên bản), giới hạn tần suất đăng nhập, CSP có `script-src 'self'`.
- Tài liệu API (`/api/docs`, `/api/openapi.json`, `/api/redoc`) tắt ở production.
- `.secrets/` nằm trong `.gitignore`; gói không chứa secret hoặc CA riêng.

### Cơ sở dữ liệu

- Revision cuối: `0016_state_revision_gate_gen` (thêm `browser_states.revision`, `ui_preflight_checks.gate_generation`,
  `ui_health_check_seq`; chỉ thêm, không xóa dữ liệu).
- Nâng cấp từ bản có migration `0012`: chuỗi `0013 → 0014 → 0014a → 0015 → 0016`. Lịch Daily đã lưu bị xóa không hoàn tác ngoài
  backup; xem `docs/release/INSTALL.md` mục 7.

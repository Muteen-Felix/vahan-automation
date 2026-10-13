# VAHAN Automation

Thu thập báo cáo Calendar Year / Maker / Month Wise từ VAHAN Public Report.
Admin lưu filter profiles và lịch; Chromium worker thực thi case; PostgreSQL
giữ tiến độ, kết quả, tài khoản và browser state mã hóa. React dashboard
hiển thị báo cáo dùng chung, search State/RTO và export Excel.

## Cài và vận hành

- [Cài mới/nâng cấp từ source hoặc gói image](docs/deployment.md).
- [Runbook: readiness, pause/drain, backup, restart, restore, chẩn đoán](docs/runbook.md).
- [Bằng chứng Đợt 5, defect và những phần chưa kiểm](docs/round5-review-evidence.md).
- [Bảo mật, image pin, lock, scan/SBOM Đợt 4](docs/round4-security-validation.md).

Windows cần Docker Desktop Linux containers và Python. Tại thư mục repository:

```powershell
py -3 scripts/run-docker.py --workers 1
```

Linux/macOS dùng `python3 scripts/run-docker.py --workers 1`.
Launcher tạo cấu hình riêng nếu chưa có, kiểm deployment guard, build/migrate
rồi khởi động stack. Nếu đã load image từ gói, đặt namespace/tag đúng manifest
và thêm `--no-build`; xem hướng dẫn đầy đủ trước khi nâng cấp.

Dashboard mặc định `http://127.0.0.1:5173`; readiness ngoài Docker
`http://127.0.0.1:8000/api/ready`. Production API không có `/docs`, `/redoc`
hay `/openapi.json`. Bootstrap username/password nằm trong `.docker.env`
ở máy cài; không commit/gửi secrets. Đổi cấu hình bootstrap không reset
password tài khoản SQL đã tồn tại. Giữ encryption key khi nâng cấp/restore.

## Luồng thực thi

1. Admin lưu profile gồm report year, bộ lọc và quy tắc kết hợp. Preview cần
   options VAHAN thật. Lịch tạo một lần hoặc hằng tháng, múi giờ Việt Nam/Ấn Độ.
2. UI Health preflight kiểm trang/control, lưu diagnostics trong SQL và chặn
   thao tác khi không xác minh được. Trạng thái blocked khi disconnect còn là
   điểm cần duyệt trong danh sách defect.
3. SQL queue claim từng case bằng transaction. Không có runner thì chờ;
   mỗi runner xử lý một case, concurrency theo pool runner khả dụng. Số
   worker cũ trong lịch bị bỏ qua; form lịch không nhập worker count.
4. Runner điền filter có dependency, xác minh DOM, Apply và dùng Tesseract OCR
   trong image. Ứng dụng không giới hạn số lần bắt đầu OCR. Không log chữ OCR thô.
5. No data là kết quả hợp lệ. Workbook được parse/commit vào bảng chính và
   lịch sử. Retry giữ case/session, không tăng case hay nhân đôi dữ liệu.
6. Export lấy toàn bộ dòng khớp State/RTO, kể cả hơn 100 dòng đang hiển thị.
   Export all cần xác nhận trước download.

Pause ngừng giao mới và drain job hiện có; resume cùng queue. Run History chỉ
admin xem; member chỉ vào Exported Reports. Maker Update đã gỡ; hai API
UI Health lịch/run-now cũ trả 404. Cài mới không nạp dữ liệu mẫu.

## Thành phần

| Thành phần | Vai trò |
| --- | --- |
| `apps/api-server` | FastAPI/Socket.IO, auth, scheduler, SQL repositories/migrations, import/export. |
| `apps/browser-runner` | Node/Playwright, Chromium sandbox, DOM driver, Tesseract qua stdin. |
| `apps/web-ui` | React static build; Nginx proxy API/socket, login throttle và CSP. |
| `docker` | PostgreSQL 17.11 chính thức pin digest, Nginx, seccomp, CA tùy chọn. |
| `scripts` | Launcher, backup, package, runtime/security/DB-role verification. |

Compose dùng một host, một API scheduler và PostgreSQL. Runtime API dùng role
DML hạn chế; migration dùng owner. Image nền pin digest, Python dependencies
có lock/hash. Scan còn phát hiện chưa được vendor vá; không coi là sạch.
Healthy container không chứng minh CAPTCHA/download VAHAN thành công.

## Kiểm thử và bàn giao

```powershell
py -3 scripts/check-doc-links.py
py -3 scripts/build-review-package.py --ref HEAD --with-images --output-dir diagnostics/review-package
py -3 scripts/test-review-package.py --package-dir diagnostics/review-package --output-dir diagnostics/review-install
```

Diagnostics có manifest, SHA-256, log đã che secrets và `results.json`.
Test UI build có fixtures được phân biệt với HTTP/DB/runtime thật và VAHAN
live. Giữ nguyên `outputs/` cho tới khi có danh sách giữ/xóa.

## Tài liệu chi tiết

- [API](docs/api-reference.md), [SQL/worker](docs/postgres-playwright.md).
- [Lịch/queue](docs/run-schedules.md), [UI Health/preflight](docs/ui-health-sql.md).
- [Retry/recovery](docs/batch-error-recovery.md), [báo cáo/Excel](docs/annual-reports.md).
- [Trạng thái và giới hạn](docs/system-status.md).
- [API server](apps/api-server/README.md), [runner](apps/browser-runner/README.md),
  [dashboard](apps/web-ui/README.md).

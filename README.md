# VAHAN Automation

Thu thập báo cáo Calendar Year / Maker / Month Wise từ VAHAN Public Report.
Admin lưu filter profiles và lịch; Chromium worker thực thi case; PostgreSQL
giữ tiến độ, kết quả, tài khoản và browser state mã hóa. React dashboard
hiển thị báo cáo dùng chung, search State/RTO và export Excel.

## Cài mới bằng Docker Compose

Ứng dụng chạy trong Linux containers. Máy cài cần Docker Engine đang chạy và
Docker Compose v2. Cài Docker theo hệ điều hành:

- Windows: [Docker Desktop](https://docs.docker.com/desktop/setup/install/windows-install/), bật Linux containers.
- macOS: [Docker Desktop](https://docs.docker.com/desktop/setup/install/mac-install/).
- Linux: [Docker Engine](https://docs.docker.com/engine/install/) và [Compose plugin](https://docs.docker.com/compose/install/linux/).

Sau khi cài, mở terminal mới và kiểm tra Docker daemon cùng Compose:

```sh
docker --version
docker compose version
docker info
```

Lấy source bằng Git hoặc tải ZIP từ [trang repository](https://github.com/Muteen-Felix/vahan-automation):

```sh
git clone https://github.com/Muteen-Felix/vahan-automation.git
cd vahan-automation
```

Trong thư mục repository, tạo cấu hình và secrets riêng cho máy này. Python
3.12+ chỉ dùng cho bước tạo file `.docker.env`; PostgreSQL, API, Chromium,
Tesseract và web dashboard đều chạy trong Docker:

```powershell
# Windows PowerShell
py -3 scripts/setup-docker.py
```

```sh
# Linux hoặc macOS
python3 scripts/setup-docker.py
```

Khởi động toàn bộ hệ thống từ source. Lần đầu Docker sẽ tải image nền và build
các service, nên máy cần Internet tới Docker registries, npm/PyPI và VAHAN:

```sh
docker compose --env-file .docker.env up -d --build --scale runner=1
docker compose --env-file .docker.env ps --all
```

Khi `postgres`, `api`, `runner` và `web` báo `healthy`, mở
`http://localhost:5173`. Service `migrate` hoàn tất với trạng thái `Exited (0)`.
Thông tin đăng nhập khởi tạo nằm trong `.docker.env`; đổi password admin sau
khi đăng nhập lần đầu và không commit hoặc gửi file này. Nếu cổng mặc định
8000 hoặc 5173 đang được dùng, đổi `API_PORT` hoặc `WEB_PORT` trong `.docker.env`
rồi chạy lại lệnh `up`.

Dashboard mặc định chỉ mở trên chính máy chạy Docker. Readiness API là
`http://localhost:8000/api/ready`. Production API không có `/docs`, `/redoc`
hay `/openapi.json`.

Dừng service nhưng giữ database:

```sh
docker compose --env-file .docker.env down
```

Không thêm `-v` nếu muốn giữ dữ liệu PostgreSQL. Mỗi máy cài mới tự tạo
`.docker.env`; giữ nguyên file đó và encryption key khi nâng cấp/restore.
Để nâng cấp stack đang có dữ liệu, dùng [deployment guide](docs/deployment.md)
và [runbook](docs/runbook.md), không dùng quy trình cài mới ở trên.

Compose không gắn đường dẫn cài đặt riêng của một máy. Bằng chứng build/runtime
hiện có trong repo là trên Linux amd64; Windows, macOS và các kiến trúc khác
chưa được xác nhận end-to-end. Xem [bằng chứng và giới hạn hiện tại](docs/round5-review-evidence.md).

- [Runbook: readiness, pause/drain, backup, restart, restore, chẩn đoán](docs/runbook.md).
- [Bảo mật, image pin, lock, scan/SBOM Đợt 4](docs/round4-security-validation.md).

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
| `docker` | Nginx, seccomp, CA tùy chọn. PostgreSQL dùng image chính thức 17.11 pin digest trong `compose.yaml` (không tự build). |
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

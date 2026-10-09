# VAHAN Automation — Chromium / Playwright / PostgreSQL

Dashboard điều phối báo cáo VAHAN; Playwright điều khiển Chromium trong Docker. Xem [đánh giá nhanh chức năng](docs/system-status.md), [tài liệu API toàn hệ thống](docs/api-reference.md) và [bộ test case nghiệm thu doanh nghiệp](docs/system-test-cases.md).

## Khởi chạy

Cần Docker Desktop đang hoạt động. Từ thư mục repository:

```bash
python3 scripts/setup-docker.py
docker compose --env-file .docker.env up -d --build
```

Hoặc chạy `./run-vahan-rpa.sh`. Dashboard: http://localhost:5173; API: http://localhost:8000; tài liệu API: http://localhost:8000/docs.

Trên Windows dùng PowerShell `./run-vahan-rpa.ps1`. Hướng dẫn production Ubuntu, Windows/macOS Docker Desktop, image tags và HTTPS: [triển khai đa nền tảng](docs/deployment.md).

File `.docker.env` bị Git bỏ qua và không được đưa vào image; script giới hạn quyền file cho tài khoản hiện tại (mode `600` trên POSIX, ACL riêng trên Windows). Tài khoản quản trị đầu tiên lấy từ `VAHAN_UI_AUTH_USERNAME` / `VAHAN_UI_AUTH_PASSWORD` trong file này. Khi nâng cấp checkout có `apps/api-server/.env`, script giữ thông tin đăng nhập hiện có và thay token runner mặc định bằng token riêng. Script không ghi đè cấu hình đã tồn tại. Các lần khởi động sau không đặt lại mật khẩu người dùng trong SQL.

Dashboard đăng nhập trực tiếp bằng tên tài khoản và mật khẩu, không có bước thiết lập hoặc nhập mã xác thực hai bước. Docker đặt `VAHAN_REQUIRE_ADMIN_MFA=false`; tài khoản đã từng thiết lập MFA cũng đăng nhập trực tiếp bằng mật khẩu.

`API_PORT` và `WEB_PORT` trong `.docker.env` mặc định là `8000` / `5173`. Nếu cổng đang dùng, hãy dừng đúng dịch vụ đang chiếm cổng trước khi khởi chạy. PostgreSQL chỉ mở trong mạng Docker.

## Kiến trúc

```mermaid
flowchart LR
  U[Dashboard React] --> N[Nginx :5173]
  N --> A[FastAPI + Socket.IO :8000]
  A <--> P[(PostgreSQL)]
  A <--> R[Playwright worker]
  R --> C[Chromium trong Docker]
  C --> V[VAHAN Public Report]
```

- `web`: giao diện React được build thành static assets; Nginx proxy `/api` và `/socket.io`.
- `api`: migration Alembic, xác thực tài khoản, phân quyền, job, file, cấu hình và sự kiện.
- `runner`: Chromium headless, một job tại một thời điểm, giữ một trang báo cáo để tái sử dụng; tải Excel bằng sự kiện download của Playwright.
- `postgres`: PostgreSQL 17, volume `postgres_data` giữ dữ liệu khi container khởi động lại.

Settings có lịch chạy tự động. Backend tự chuẩn bị profile, điều phối queue và lưu kết quả, kể cả khi đóng dashboard. Ảnh CAPTCHA giữ trong RAM của browser runner; không ghi ảnh mới vào thư mục/SQL và không hiển thị trên dashboard. Worker chờ xác minh của người vận hành, không tự OCR/submit. Mỗi job có giới hạn 10 refresh chủ động, 3 lần bị từ chối và deadline chờ 10 phút; lỗi chạm giới hạn được lưu để kiểm tra và không tự retry tại checkpoint/lượt cuối. Backend nhận ID và trạng thái để theo dõi worker. Xem [lịch chạy tự động](docs/run-schedules.md) và [review guard](docs/validation-loop-review-2026-10-09.md).

## Dữ liệu lưu trong SQL

| Nhóm | Bảng / cách lưu |
| --- | --- |
| Tài khoản, vai trò, trạng thái, hồ sơ | `users`; mật khẩu băm PBKDF2 với salt riêng |
| Phiên đăng nhập và thu hồi khi logout | `auth_sessions`; lưu hash ID phiên |
| Phiên báo cáo, filters, trạng thái, thời gian, lỗi, số lần Apply | `report_sessions`, `jobs`, `job_events` |
| Worker, kết nối và job hiện tại | `runners` |
| Cấu hình ma trận, tiến độ batch, job đang xem của từng tài khoản | `user_state` |
| Lịch kiểm tra định kỳ và lịch chạy báo cáo tự động | `app_settings`; mỗi lịch báo cáo lưu profile snapshot, múi giờ, số worker, checkpoint và tiến độ |
| Bảng chính, tên nhà sản xuất, State/RTO, năm và 12 tháng JAN–DEC | `main_reports`; ngày giờ đầy đủ và nguồn từng tháng lưu trong cùng hàng |
| Lịch sử cập nhật mỗi filter | `report_update_history`; thêm mới / đã lưu / cần xem lại / No record found |
| Ảnh lỗi đã che CAPTCHA và tài liệu kỹ thuật cũ | `stored_files`: BYTEA, metadata, kích thước, SHA-256; không ghi ảnh CAPTCHA mới |
| Lịch sử kiểm tra trang, nội dung xuất CSV | `ui_health_checks` |
| Phiên bản DOM đã xác minh, kết quả kiểm tra worker trước khi tải Maker | `ui_contract_versions`, `ui_preflight_checks`; hợp đồng đang dùng và lỗi từng worker trong `app_settings` |
| Cookie / localStorage của Chromium | `browser_states`, mã hóa Fernet bằng `VAHAN_BROWSER_STATE_KEY` |
| Thao tác API, options đọc từ VAHAN và lỗi worker | `audit_events` |

UI Health kiểm tra các worker được chọn trước khi tải Maker và tạo hàng đợi. Thay đổi DOM xác minh được sẽ cập nhật hợp đồng trong SQL và selector đang dùng; thay đổi không tương thích được kiểm tra lại một lần, sau đó chặn công việc mới và hiện cảnh báo **Copy error** để gửi dev. Chi tiết lưu trữ, điều kiện kiểm tra và kiểm thử: [UI Health với SQL](docs/ui-health-sql.md).

Mỗi filter ghi trực tiếp vào bảng chính trong một transaction SQL, cùng lịch sử cập nhật, trạng thái hoàn tất và giải phóng worker. Dữ liệu có sẵn không thêm trùng; chỉ thêm nhà sản xuất hoặc tháng còn thiếu. Excel được đọc đầy đủ trong bộ nhớ rồi xóa bản tải tạm, không lưu bản sao Excel/DOM trong SQL. Giới hạn 50 MB tải lên, 250 MB giải nén và 500.000 dòng; vượt giới hạn hoặc dữ liệu không hợp lệ thì rollback cả filter.

Exported Reports hiển thị bảng chính 12 tháng, chọn năm từ 2026, tìm State/RTO và phân trang. Nút xuất Excel lấy toàn bộ kết quả khớp tìm kiếm qua mọi trang; nếu không tìm kiếm, hệ thống hỏi xác nhận xuất toàn bộ báo cáo/năm đang chọn. Tên file gồm RTO, mã RTO, State và năm theo mẫu. Phần Update history đã bỏ khỏi giao diện; lịch sử SQL nội bộ vẫn phục vụ ghi dữ liệu và kiểm tra độ phủ. Bảng tổng dùng chung cho mọi tài khoản đăng nhập; cùng bộ lọc chỉ có một bộ dữ liệu, không tách theo người chạy. Chi tiết migration/backup và kiểm thử: [bảng chính](docs/annual-reports.md).

## Chuyển dữ liệu runtime cũ

Trước khi dừng API cũ, xuất lịch sử:

```bash
python3 scripts/export-legacy-history.py --api-url http://127.0.0.1:8000
```

Sau khi Docker chạy, nhập runtime với mount chỉ đọc:

```bash
docker compose --env-file .docker.env run --rm --no-deps   -v "$(pwd)/apps/api-server/runtime:/legacy:ro"   api python -m app.import_legacy /legacy
```

Có thể dùng `--dry-run`. Import giữ nguyên nguồn, lưu file và các dòng trong cùng transaction, có ledger theo đường dẫn + SHA-256 để chạy lại không nhân bản. File thay đổi được giữ thành phiên bản mới. Snapshot giữ lại cả các job lỗi/hủy. Các dữ liệu chỉ còn trong RAM của API cũ phải được xuất trước khi API cũ dừng. Cấu hình cũ trong localStorage được chuyển sang SQL khi admin đăng nhập trên cùng địa chỉ dashboard ban đầu.

## Vận hành và sao lưu

```bash
docker compose --env-file .docker.env ps
docker compose --env-file .docker.env logs -f api runner
curl http://127.0.0.1:8000/api/ready
python3 scripts/backup-docker.py
docker compose --env-file .docker.env stop
```

Windows có thể sao lưu bằng `./backup-vahan-rpa.ps1`.

Backup tạo `backups/<timestamp>/database.dump` bằng `pg_dump` và bản sao `.docker.env` với quyền `600`. Cần giữ cả khóa mã hóa khi khôi phục browser state. Thư mục backup bị Git và Docker build bỏ qua. `docker compose down` giữ volume; `down -v` xóa dữ liệu SQL.

API hiện chạy **một process** vì kết nối Socket.IO được định tuyến trong process. Một worker xử lý tuần tự; lịch sử/configuration lưu bền vững, còn điều phối hàng đợi batch vẫn nằm trong dashboard. Giữ dashboard mở để tiến tới các filter tiếp theo. Khi API/worker khởi động lại giữa job, job bị gián đoạn chuyển `FAILED` và cần Retry rõ ràng; không tự lặp lại thao tác Apply.

Hàng đợi SQL kiểm tra sau từng nhóm 10 case và sau nhóm cuối nếu dưới 10. Case lỗi trong nhóm được retry trước khi sang nhóm kế tiếp. Khi toàn bộ lượt chính kết thúc, hệ thống thu gom **các case vẫn lỗi có thể retry tự động** và chia chúng cho các worker để thực hiện thêm một lượt phục hồi cuối. Mỗi case có một lượt ban đầu, một retry tại checkpoint và một retry cuối; case vẫn lỗi giữ nguyên thông báo để xem/sao chép trong **Failed cases**. Kết quả `NO_DATA` hợp lệ không bị retry. Trạng thái nhóm, lượt cuối, lỗi và số lần thử lưu trong SQL; dừng/chạy tiếp, đổi worker hoặc khởi động lại vẫn giữ đúng session, case và filters gốc. Các lần thử lưu riêng qua `retryOfJobId` / `caseId`. Chi tiết: [phục hồi case lỗi](docs/batch-error-recovery.md).

Trong Run history, **Delete session** chuyển phiên sang **Deleted sessions** và **Restore session** khôi phục phiên. Xóa chỉ ẩn thẻ khỏi lịch sử; file, các lần chạy và dữ liệu tháng vẫn lưu. Backend chặn xóa phiên đang chạy, chặn retry/continue phiên đã xóa cho đến khi khôi phục, và kiểm tra quyền chủ sở hữu (admin quản lý mọi phiên).

Trong một case, worker điền đồng thời 5 nhóm bộ lọc và giữ đúng thứ tự của các trường phụ thuộc. Các giá trị còn sót được xóa; mọi field được yêu cầu đều được đối chiếu lại với DOM sau khi request tải options kết thúc và ngay trước Apply. Không khớp thì dừng case, không lấy báo cáo với bộ lọc sai. Dấu kiểm tra và thời gian từng nhóm lưu bền vững trong `jobs.payload.filter_execution`, với event `filters-verified`. Xem [flow điền song song](apps/browser-runner/README.md).

Sau Apply, chỉ **No record found** mới đã tải xong mới tạo `NO_DATA`. State/RTO, filters và ngày giờ đầy đủ được ghi vào lịch sử cập nhật. Hết giới hạn chờ 5 giây ghi `VAHAN_RESULT_TIMEOUT`.

Khi có dữ liệu, worker lấy workbook đầy đủ, đọc tất cả worksheet và ghi thẳng vào `main_reports` qua `/api/jobs/{id}/main-report`. Hoàn tất chỉ sau khi SQL commit thành công. Các giá trị có sẵn được giữ nguyên; thiếu tháng/nhà sản xuất mới thì bổ sung. Không lưu bảng DOM, các dòng Excel, workbook hoặc TXT vào SQL. Migration `0004_main_reports` chuyển toàn bộ dữ liệu cũ và lịch sử trước khi bỏ bảng phụ; xem [hướng dẫn](docs/annual-reports.md).

Sau mỗi filter lưu SQL, bảng tổng của mọi tài khoản đang xem nhận cập nhật tức thì qua socket. Dòng xác nhận trên bảng ghi rõ State/RTO, ngày giờ lưu, số dòng/tháng mới và số ô đã có sẵn. Lần chạy trùng dữ liệu hiện **Already saved in main table**, nên tổng số dòng không tăng; **No record found** cũng được xác nhận riêng. Không cần đợi cả batch kết thúc.


`observed_at` và `saved_at` là `TIMESTAMPTZ`, giữ đầy đủ năm-tháng-ngày và giờ-phút-giây. Bộ lọc thời kỳ báo cáo được lưu nguyên bản trong `filters`; không tự đặt ngày cho bộ lọc chỉ có tháng/năm. Dashboard hiển thị thời điểm thu thập theo UTC+7. Chi tiết truy vấn tại [PostgreSQL và Playwright](docs/postgres-playwright.md).

## Cấu trúc

- `apps/api-server`: FastAPI, repositories PostgreSQL, migrations, importer.
- `apps/browser-runner`: Playwright worker và DOM driver độc lập.
- `apps/web-ui`: dashboard, trạng thái theo người dùng, quản lý tài khoản/file.
- `docker`: Nginx và seccomp profile chính thức của Playwright.

Playwright package và image đều pin `1.63.0`; worker chạy dưới user `pwuser` và bật Chromium sandbox. [Hướng dẫn Docker của Playwright](https://playwright.dev/docs/docker).

Xem thêm [chi tiết dữ liệu và giới hạn](docs/postgres-playwright.md).

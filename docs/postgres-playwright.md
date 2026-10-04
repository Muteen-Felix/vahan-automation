# PostgreSQL và Playwright

## Quy tắc nhất quán

- Job assignment khóa hàng runner trong transaction: một worker chỉ có một job đang hoạt động.
- Thay đổi trạng thái khóa hàng job, kiểm tra transition và ghi event trước commit.
- Điền song song trong một case giữ dependency giữa các trường. Event runner `job:filters-verified` kiểm tra assignment, phase/trạng thái và expected/actual đối chiếu filters của job trước khi lưu. `jobs.payload.filter_execution` chứa hai phase `filled` / `before-apply`, timestamp, thời gian nhóm và từng control đã kiểm tra; thiếu field hoặc sai giá trị bị từ chối.
- `/api/jobs/{id}/main-report` khóa job, đọc đầy đủ workbook và ghi trực tiếp 12 cột tháng vào `main_reports`, cùng `report_update_history`, trạng thái COMPLETED và giải phóng runner trong một transaction. Không giữ blob hoặc dòng Excel/DOM trong SQL.
- Worker chỉ gửi `/report-result` cho NO_RECORD đã xác nhận mới; lịch sử giữ State/RTO, filters và ngày giờ đầy đủ, không tạo TXT. Timeout là `VAHAN_RESULT_TIMEOUT`.
- Dữ liệu có sẵn không thêm trùng. Chỉ bổ sung hàng/tháng còn thiếu; xung đột được ghi vào lịch sử. Sai dữ liệu, thiếu tên nhà sản xuất hoặc thiếu workbook thì không hoàn tất filter.
- Cancel giải phóng đúng job hiện tại; worker ngừng trang của job đó. Gửi CAPTCHA kiểm tra trạng thái và ID ảnh trong transaction để tránh gửi lặp/stale.
- File và job có owner; HTTP và Socket.IO đều kiểm tra owner. Admin có quyền quản lý. Logout thu hồi phiên trong SQL và ngắt các UI socket của phiên đó.
- Không lưu đáp án CAPTCHA. Ảnh, kết quả, filters và lịch sử vẫn được lưu.

## Truy vấn

```sql
SELECT username, role, active, created_at FROM users;
SELECT status, COUNT(*) FROM jobs GROUP BY status;
SELECT kind, COUNT(*), SUM(size) FROM stored_files GROUP BY kind;
SELECT state,rto,rto_code,maker,year,jan,feb,mar,apr,may,jun,jul,aug,sep,oct,nov,dec
FROM main_reports ORDER BY state,rto,maker LIMIT 100;
SELECT event, actor, created_at, payload FROM audit_events ORDER BY created_at DESC LIMIT 100;

-- Thời gian điền, các nhóm chạy đồng thời và giá trị được kiểm tra trước Apply.
SELECT id, status,
       payload->'filter_execution'->'filled'->>'durationMs' AS fill_ms,
       payload->'filter_execution'->'filled'->'groups' AS groups,
       payload->'filter_execution'->'before-apply' AS verified_before_apply
FROM jobs WHERE payload->'filter_execution'->'filled' IS NOT NULL
ORDER BY created_at DESC LIMIT 20;

-- Ngày tháng năm và giờ Việt Nam, cùng bang/RTO không có dữ liệu.
SELECT job_id,states,rtos,status,filters,
       to_char(observed_at AT TIME ZONE 'Asia/Ho_Chi_Minh','DD/MM/YYYY HH24:MI:SS') AS collected_vn,
       imported_at
FROM report_update_history WHERE status='no-data' ORDER BY imported_at DESC;
```

Chạy SQL qua:

```bash
docker compose --env-file .docker.env exec postgres psql -U vahan -d vahan
```

## API mới

| Endpoint | Quyền / dữ liệu |
| --- | --- |
| `GET /api/jobs` | Job theo owner, admin toàn bộ |
| `POST /api/jobs/{id}/main-report` | Chỉ runner được gán; ghi dữ liệu bảng chính, lịch sử và hoàn tất job |
| `POST /api/jobs/{id}/report-result` | Chỉ runner được gán; ghi No record found và hoàn tất NO_DATA |
| `GET /api/jobs/{id}/report-result?offset=0&limit=100` | Owner/admin; metadata kết quả đã ghi bảng chính |
| `GET /api/user-state` | Trạng thái của người dùng hiện tại |
| `PUT /api/user-state/{key}` | JSON state, tối đa 5 MB / key |
| `GET /api/users`, `POST /api/users`, `PATCH /api/users/{name}` | Admin; user mới có mật khẩu tối thiểu 12 ký tự |
| `POST /api/files`, `GET /api/files` | File của tài khoản; admin xem toàn bộ |
| `GET /api/files/{id}/download` | Tài liệu kỹ thuật theo owner; `/rows` đã ngừng dùng |
| `GET /api/audit` | Admin, phân trang |
| `GET /api/ready` | Kiểm tra PostgreSQL và schema |
| `GET/PUT /api/runner-state/{runnerId}` | Token runner và runner đang kết nối; dữ liệu mã hóa |

Excel chỉ dùng làm nguồn nhập dữ liệu cho bảng chính. Bộ đọc đi qua mọi worksheet; không lưu công thức/style/ảnh/charts hay bản gốc workbook trong SQL. Exported Reports chỉ hiển thị bảng chính và lịch sử cập nhật.

## Migration / local development

Alembic revision `0001_durable_state` sử dụng snapshot schema cố định tại `migrations/schema_v1.py`; revision `0002_report_results` bổ sung `report_results` và `report_rows`, không sửa lịch sử cũ. Revision `0004_main_reports` chuyển dữ liệu/lịch sử sang bảng chính, kiểm tra đầy đủ rồi bỏ các bảng phụ và bản sao file báo cáo. Xem [quy trình migration và backup](annual-reports.md). API Docker tự chạy migration trước Uvicorn.

Có thể chạy backend ngoài Docker nếu cung cấp `DATABASE_URL`, `VAHAN_UI_AUTH_TOKEN_SECRET`, bootstrap user/password, `VAHAN_API_RUNNER_TOKEN`, `VAHAN_BROWSER_STATE_KEY`, rồi chạy `python -m app.migrate`. PostgreSQL của compose không mở ra host theo mặc định.

## Khôi phục backup

Dừng API/worker trước khi khôi phục. Dùng `pg_restore` vào database trống từ `database.dump`, khôi phục các biến cấu hình/khóa từ `.docker.env`, sau đó khởi động dịch vụ. Tài khoản và session đã lưu không bị bootstrap ghi đè. Giữ backup và khóa ngoài Git.

## Giới hạn vận hành

Chromium bắt đầu tại trang trống; chỉ mở VAHAN khi lấy options, chạy job hoặc kiểm tra trang. Readiness báo browser/API sẵn sàng, chưa chứng minh trang chính thức sẽ cho chạy một báo cáo. Thay đổi giao diện hoặc bước xác thực của VAHAN có thể làm job thất bại; xem lỗi và ảnh được lưu.

Health check dùng trang riêng và kiểm tra selector bắt buộc; hiện chưa đối chiếu đầy đủ contract của các option và giá trị trong từng bộ lọc. Batch vẫn được dashboard điều phối; đóng dashboard ngừng tạo job mới nhưng không xóa tiến độ SQL.

Một số test cũ trong `apps/api-server/tests` được viết cho repositories RAM và file store trước khi chuyển sang PostgreSQL. Không chạy chúng với database thật; cần database riêng khi cập nhật kiểm thử PostgreSQL.

Kiểm thử kết quả DOM: `cd apps/browser-runner && npm run test:results`. Kiểm thử SQL/API: tạo database riêng tên `vahan_results_<suffix>_test`, đặt `VAHAN_RESULT_TEST_DATABASE` vào tên đó rồi chạy `python verification/test_report_results.py` từ API với môi trường compose. Script chỉ chấp nhận database test, tự chạy migration và kiểm tra idempotency, rollback, cancellation, assignment và timestamps.

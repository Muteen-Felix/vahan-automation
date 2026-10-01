# VAHAN UI Drift Guard (isolated module)

Thư mục này là lớp kiểm tra giao diện và log riêng, được thêm vào MVP mà
không thay thế controller điền filter/CAPTCHA hiện tại.

## Luồng hoạt động

1. Service worker đặt `chrome.alarms` theo số ngày người dùng lưu trên Web UI
   (mặc định 3 ngày, cho phép từ 1 đến 365 ngày).
2. Khi alarm chạy, extension chỉ tìm tab VAHAN chính thức đã mở đúng URL
   `https://analytics.parivahan.gov.in/analytics/vahanpublicreport?lang=en`.
   Extension không tự mở tab; nếu tab chưa mở hoặc URL bị chuyển sang trang khác,
   lượt kiểm tra được ghi là `CHECK_ERROR` để Dev biết cần xử lý.
3. `health-check-content.js` chỉ đọc DOM: kiểm tra control bắt buộc, wrapper
   multiselect và một số option dữ liệu ổn định (`Two Wheeler`, `Fuel`, danh
   sách Fuel không rỗng).
4. Kết quả được so sánh với lần trước để phát hiện `DATA_CHANGED` khi digest
   option thay đổi.
5. Kết quả và diagnostic được gửi tới backend qua `POST /api/ui-health/logs`.
   Backend lưu CSV theo cửa sổ tối đa 10 ngày hoặc 512 KiB; tên dạng
   `report-YYYY-MM-DD-to-YYYY-MM-DD.csv`. Khi backend tạm thời không khả dụng,
   extension giữ các health check chưa gửi trong hàng đợi local và gửi bù ở lần
   kiểm tra kế tiếp.

Health check production chạy trên trang VAHAN chính thức. Nó không điền filter,
không đọc/giải CAPTCHA, không bấm Apply và không tải báo cáo.

## Các điểm tích hợp

- `guard.js`: contract, signature, diagnostic `UI_DRIFT_*` và safe-repair API
  dành cho controller tương lai.
- `health-check-content.js`: listener chỉ phục vụ message
  `RUN_SCHEDULED_UI_CHECK`.
- `health-check.mjs`: alarm, xác minh tab VAHAN chính thức, so sánh dữ liệu, gửi log
  backend, queue log offline, queue alert và state.
- `src/background.js`: chỉ import/register module health-check.
- `manifest.json`: thêm quyền `alarms` và nạp các content script riêng.

Web UI gọi `GET/PUT /api/ui-health/schedule`. Backend lưu cấu hình trong bộ nhớ
MVP và phát sự kiện `ui-health:schedule-updated` qua namespace `/runner`; runner
đang kết nối sẽ đặt lại alarm ngay. Khi runner khởi động hoặc kết nối lại, nó
đọc lại lịch từ backend. Nếu backend tạm thời không khả dụng, extension giữ
alarm hiện tại hoặc dùng mặc định 3 ngày cho lần cài mới.

Nút **Kiểm tra ngay** trên Web UI gọi `POST /api/ui-health/run-now`. Backend chọn
một runner đang kết nối và phát `ui-health:run-now`; extension tìm một tab VAHAN
chính thức đã mở đúng URL và có content script phản hồi. Việc Web UI đang là tab
active không làm health-check kiểm tra nhầm Web UI; extension không tự mở tab.
Nếu chưa có tab official, hoặc tab đổi URL trước khi kiểm tra, lần chạy được ghi
là `CHECK_ERROR` kèm URL thực tế nếu có.

Web UI gọi `GET /api/ui-health/reports?date=YYYY-MM-DD` để xem các bản ghi của
một ngày và dùng `GET /api/ui-health/reports/{fileName}/download` để tải đúng
file CSV từ backend. Backend giữ file trong `apps/api-server/runtime/ui-health-logs`
(có thể đổi bằng `VAHAN_UI_HEALTH_LOG_DIR`).

State cục bộ:

- `vahanUiHealthCheck`: lần kiểm tra gần nhất.
- `vahanUiPendingDevNotification`: alert chờ connector Dev đọc sau này.
- `vahanUiHealthPendingLogs`: các health check chưa gửi được lên backend.

Hiện tại alert Dev vẫn chưa gửi ra ngoài; connector website/webhook/email có thể
đọc `GET_UI_HEALTH_CHECK` hoặc storage sau này. Nếu Chrome tắt hoàn toàn, alarm
của extension không chạy; cần scheduler backend riêng nếu muốn kiểm tra khi máy
và Chrome đều tắt.

## Kiểm tra

```bash
npm run test:ui-drift
node --check ui-drift/guard.js
node --check ui-drift/health-check-content.js
node --check ui-drift/health-check.mjs
```

Các test controller kiểm tra việc giữ lỗi đầu tiên để tương thích và lưu toàn bộ
`reports[]`/`errorCount` qua state, queue và backend payload.

Bộ test trực tiếp trên tab VAHAN chính thức nằm ở
[`official-devtools-test.js`](./official-devtools-test.js), hướng dẫn chạy ở
[`OFFICIAL-DEVTOOLS-TESTING.md`](./OFFICIAL-DEVTOOLS-TESTING.md).

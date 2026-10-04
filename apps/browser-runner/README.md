# Chromium Playwright worker

`runner.mjs` quản lý Chromium/context, Socket.IO, CAPTCHA do người dùng nhập, download và upload file. `page-driver.js` chứa các thao tác DOM VAHAN, giữ dependency giữa State/RTO và filters.

Playwright package và Docker image pin `1.63.0`. Container chạy non-root, sandbox, seccomp và shared memory 1 GB. Mạng API và browser state được cấu hình qua compose. Health endpoint nội bộ `:3001/health` báo kết nối API/browser.

Worker không giải CAPTCHA hoặc vượt qua validation. VAHAN HTTP 401 được ghi thành lỗi yêu cầu người vận hành xử lý; không retry vô hạn. Browser state mã hóa được tải/lưu qua backend PostgreSQL.

Xem [README gốc](../../README.md).

Sau Apply, DOM driver xác nhận kết quả mới, đúng RTO và đã hết loading. `No record found` gửi NO_RECORD cùng ngày giờ ISO đầy đủ, lưu lịch sử và hoàn tất NO_DATA. Khi có dữ liệu, workbook đầy đủ là bắt buộc: worker gửi một lần tới `/api/jobs/{id}/main-report`, chờ SQL lưu vào bảng chính rồi mới nhận filter tiếp theo và xóa file tạm. Không lưu bản sao DOM/Excel/TXT hoặc ảnh thành công trong SQL. Timeout là lỗi riêng. Kiểm thử: `npm run test:results`, `node test-main-report-save.mjs`.


Trước khi bấm Apply, worker phải nhận ACK lưu `SUBMITTING` từ backend. Sau click mới ghi `job:apply-clicked`, chuyển `WAITING_RESULT` và đọc báo cáo. Nếu dashboard đã lưu `SUBMITTING`, ACK lặp vẫn hợp lệ; trạng thái bị hủy hoặc submission đồng thời không được bấm Apply tiếp. Chạy `npm run test:lifecycle` để kiểm tra thứ tự và các tình huống này.

Một case điền đồng thời 5 nhóm: thời gian, địa lý, loại xe, trục báo cáo và các trường độc lập. Trong mỗi nhóm vẫn giữ các dependency: Delhi NCR → State → RTO; Category Group → Sub-category → Class; EV Type → Fuel; Y-Axis → X-Axis. Hai nhánh phân loại xe và EV/Fuel chạy đồng thời. Các truy vấn tìm Maker chạy tối đa 4 request cùng lúc; tên có dấu phẩy được giữ nguyên trong mảng, không tách thành nhiều hãng.

Driver chờ DOM và request fetch/XHR của trang, kiểm tra giá trị native select/input, trường X-Axis hidden và các trường tùy chọn phải được xóa. Nếu một handler tải muộn reset giá trị, chỉ chạy lại nhóm bị ảnh hưởng, tối đa 2 lượt. Field không có mapping, control bị thiếu hoặc giá trị không khớp sẽ dừng case trước Apply. Khi một nhóm lỗi, hủy request và chờ các nhóm kết thúc trước khi cho phép điền tiếp.

Sau khi điền và ngay trước Apply, worker gửi `job:filters-verified` và phải nhận ACK đã lưu PostgreSQL. Backend đối chiếu từng field với filters của job. `jobs.payload.filter_execution` lưu `filled` và `before-apply`: expected/actual của từng control, timestamp ISO đầy đủ, thời gian kiểm tra, thời gian tổng và từng nhóm, số lượt sửa. Đây là song song các nhóm trong **một case**; mỗi worker vẫn chỉ xử lý một job đang hoạt động.

Chạy `npm run test:filters` để kiểm tra dependency tải chậm, reset muộn, tái sử dụng trang, tên Maker có dấu phẩy, mismatch trước Apply và hủy tác vụ. Có thể so sánh cùng fixture với bản driver trước sửa bằng `VAHAN_BASELINE_DRIVER=/absolute/path/page-driver-before.js npm run test:filters`; kết quả fixture không phải cam kết tốc độ mạng VAHAN.

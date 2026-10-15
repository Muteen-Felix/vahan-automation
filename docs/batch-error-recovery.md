# Retry và recovery case

Case có identity bền vững trong SQL, phân biệt với các job attempt.
Retry phải giữ profile/filter/source và session gốc, có `retryOfJobId`.
Không tạo thêm case để biểu diễn một retry. `NO_DATA` hợp lệ là kết quả cuối,
không phải lỗi cần retry. Case lỗi giữ nguyên nguyên nhân/diagnostics.

Worker disconnect được xử lý qua grace/lease. Queue repository kiểm attempt,
lease và trạng thái cuối trước khi claim/settle để tránh mất/trùng case.
Pause ngừng giao mới, drain case hiện có; resume cấp tiếp trong session cũ.
API restart phải đọc SQL, không khôi phục từ trạng thái UI đơn thuần.

Chính sách attempt/checkpoint thực thi ở
`apps/api-server/app/repositories/batch_queue.py`,
`apps/api-server/app/run_scheduler.py`,
`apps/api-server/app/repositories/postgres.py` và worker `runner.mjs`.
Không tăng quota/attempt bằng sửa trực tiếp SQL trong vận hành.
Ứng dụng không đặt quota bắt đầu OCR. Nếu OCR không chạy, kiểm tra runner,
challenge hiện tại và Tesseract; VAHAN vẫn có thể giới hạn xác minh ở phía họ.

Test lease/concurrency/restart từ Đợt 2–4 và kiểm runtime gói Đợt 5 có phạm vi
khác nhau; xem [báo cáo](round5-review-evidence.md) để biết phần nào đã chạy
trên image, phần nào chỉ fixture và phần nào chưa có bằng chứng VAHAN thật.

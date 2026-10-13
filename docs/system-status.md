# Trạng thái và giới hạn

Nguồn sự thật của run/case/job là PostgreSQL. Bản thử dùng một API scheduler
và các Chromium runner trên một host. Lịch dùng runner hiện có; worker count
cũ không được áp lại, không có ô concurrency trong lịch. Hiện tạo lịch một lần
hoặc hằng tháng, có múi giờ Việt Nam/Ấn Độ và chuyển profile tháng sang năm mới.

Maker Update đã gỡ. Các endpoint `GET /api/ui-health/schedule`,
`POST /api/ui-health/run-now` và `/api/maker-updates` trả 404.
Run History dành cho admin; member chỉ xem Exported Reports. Retry giữ cùng
case/session và không làm tăng số case. Export State/RTO lấy mọi dòng khớp,
không chỉ trang 100 dòng; export toàn bộ yêu cầu xác nhận.

OCR tự động dùng Tesseract trong runner; ứng dụng không đặt quota số lần bắt đầu
OCR. VAHAN vẫn có thể áp dụng chính sách xác minh hoặc giới hạn riêng. OCR ảnh
tổng hợp không chứng minh tỷ lệ giải CAPTCHA thật.
UI Health/browser healthy cũng không chứng minh download đã thành công.

Xem [bằng chứng Đợt 4](round4-security-validation.md),
[bằng chứng Đợt 5 và defect còn mở](round5-review-evidence.md),
[hướng dẫn cài](deployment.md) và [runbook](runbook.md).

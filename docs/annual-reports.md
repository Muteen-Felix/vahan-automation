# Báo cáo và Excel

Workbook của case được parse và commit vào `main_reports` cùng lịch sử cập
nhật trong transaction. Report scope/year/State/RTO/Maker xác định dữ liệu;
`0` khác với tháng chưa có dữ liệu. Retry/ingest lặp không tăng số case hay
nhân đôi dòng. Conflict dữ liệu có lịch sử để kiểm tra.

Dashboard hiển thị tối đa 100 dòng một trang, search State/RTO và chọn
dataset/year. Export truy vấn toàn bộ dòng khớp, không dùng offset/limit của
trang. Export all yêu cầu xác nhận trước download và API `confirmAll=true`.
File có title, summary, header và dữ liệu; kiểm số dòng không tính ba dòng đầu.

Cài mới mặc định không nạp dữ liệu mẫu. Mọi fixture dùng để thử phải có nhãn
SYNTHETIC rõ và dùng project/database riêng. Run History chỉ admin xem.
Không lấy dữ liệu tổng hợp làm bằng chứng đã tải workbook VAHAN thật.

Xem [API](api-reference.md), [báo cáo bằng chứng](round5-review-evidence.md).

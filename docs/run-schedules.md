# Lịch chạy và queue

Profile lưu report year; form lịch không nhập số worker hay report year.
API lịch chấp nhận `profileId`, thời gian có offset, `timeZone`, `year` và
`repeat` một lần/hằng tháng. Các khóa `workerCount` cũ được bỏ qua.
Hai múi giờ là `Asia/Ho_Chi_Minh` và `Asia/Kolkata`.

Khi không có runner khả dụng, lịch chờ. Với một/ba runner khả dụng, tối đa
một/ba case thực thi đồng thời; mỗi worker nhận một case qua transaction SQL.
Preflight và options dùng planning lease để không chiếm runner đang có job.
SQL giữ run/session/task/case identity, lease, tiến độ và retry.

Pause ngừng cấp việc mới và drain case đã giao. Resume dùng cùng queue/session,
kiểm gate rồi cấp tiếp. Mất mạng hoặc API restart không được xem là hoàn tất
case; lease/recovery kiểm trạng thái SQL trước khi giao lại. Kết quả muộn phải
khớp lần giao/identity để không ghi đè case đã hoàn tất.

ETA dựa throughput tổng của run, active elapsed time và số case còn lại;
pause/stall không có tốc độ ổn định thì hiển thị chờ thay vì hứa thời gian.
Lịch tháng giữ wall-clock time theo zone, clamp ngày cuối tháng và tạo profile
năm tiếp theo khi cần. Chỉ hỗ trợ `once` và `monthly`; API từ chối `repeat='daily'` và migration `0015` đã xóa các lịch Daily đã lưu (D-35); nếu lịch Daily còn `sessionId`, revision
`0014a_daily_schedule_guard` dừng nâng cấp và không xóa gì.

Xem [retry](batch-error-recovery.md), [runbook](runbook.md) và bảng kiểm thật/
fixture/chưa kiểm trong [báo cáo Đợt 5](round5-review-evidence.md).

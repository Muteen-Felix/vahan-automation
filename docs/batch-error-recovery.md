# Phục hồi case lỗi trong hàng đợi SQL

| Giai đoạn | Hành vi |
| --- | --- |
| Lượt chính | Worker nhận các case trong nhóm 10 hiện tại. Worker nhanh có thể nhận thêm case trong cùng nhóm. |
| Checkpoint | Khi các lượt đầu của nhóm đã kết thúc, retry các case lỗi trong nhóm. Chỉ chuyển sang nhóm tiếp theo khi các retry này kết thúc. Nhóm cuối dưới 10 cũng được kiểm tra. |
| Quét lỗi cuối | Sau nhóm cuối, lấy các case còn FAILED có thể retry tự động từ SQL, đưa vào lượt phục hồi cuối và phân phối cho các worker đang sẵn sàng. Không yêu cầu worker cũ; ưu tiên worker khác khi có case phù hợp. |
| Kết thúc | Case phục hồi thành công cập nhật With data/No data. Case vẫn lỗi giữ FAILED cùng nguyên nhân cuối, không lặp vô hạn. |

Mỗi case thường có tối đa 3 lượt: ban đầu, checkpoint và lượt cuối. Hủy/tạm dừng không làm mất case hay xóa số lần thất bại đã ghi; một retry bị hủy có thể tiếp tục sau khi resume. `NO_DATA` đã xác nhận không vào danh sách retry. Mỗi lần thử giữ toàn bộ filters, tên báo cáo, session và chuỗi `retryOfJobId`/`caseId` của case gốc.

Ngoại lệ cần người vận hành: `CAPTCHA_REFRESH_LIMIT`, `CAPTCHA_REJECTION_LIMIT`, `CAPTCHA_WAIT_TIMEOUT` chuyển case sang FAILED ngay lần lỗi đó, không tăng giả số lần thất bại để cạn quota. Case vẫn hiện lỗi và `requiresOperator=true`, nhưng `recoveryPending=false`; checkpoint và lượt cuối không tự khởi tạo lại. Pending target cũ mang lỗi này được chặn trước claim khi khôi phục queue. Các case khác vẫn tiếp tục; phiên có thể kết thúc với lỗi. Sau khi xử lý nguyên nhân, retry chủ động thành công được đối soát về case/session gốc. Xem [review](validation-loop-review-2026-10-09.md).

Chính sách lưu tại `app_settings` với key `batch-retry-policy:<sessionId>`: nhóm hiện tại, checkpoint đã kết thúc, phase PRIMARY/CHECKPOINT/FINAL/DONE và danh sách case của lượt cuối. Mọi chuyển phase/claim được đồng bộ bằng khóa session trong transaction SQL. Reload, đổi worker hay khởi động lại không tạo thêm lượt cuối trùng lặp. Phiên lịch sử đã hoàn tất không tự chạy lại chỉ vì được mở xem.

UI hiển thị checkpoint/lượt phục hồi cuối trên thẻ lịch chạy. Mục **Failed cases** mở danh sách case còn lỗi, các lần thử và lỗi gốc; **Copy failed cases** sao chép toàn bộ danh sách. Bộ đếm lỗi chỉ hết khi case đạt With data hoặc No data, đồng thời số case đã xử lý không bị reset khi lượt cuối bắt đầu.

Retry cuối vẫn phải vượt qua SQL UI Health gate trước khi giao việc mới. Nếu website không tương thích, công việc tiếp tục bị chặn và danh sách retry được giữ lại.

Kiểm thử trong database dùng riêng `vahan_queue_*_test` / `vahan_schedule_*_test`: `verification/test_queue_retry_checkpoints.py` và `verification/test_run_schedules.py`. Kiểm thử UI: `npm run test:schedules-ui`, với `SCHEDULE_UI_URL` trỏ tới URL kết thúc bằng `#settings`.

A failed browser document is retired before its worker is released for another case. The next case opens a new page in the same browser context, preserving the session cookies and SQL-approved selectors. Failure screenshots have a five-second timeout; page close has a three-second bound. A new assignment waits for failure cleanup to finish. Read-only document setup reattaches after a navigation destroys its JavaScript context, with one shared deadline, without repeating Apply. This prevents one broken page from repeatedly failing every subsequent case on the same worker.

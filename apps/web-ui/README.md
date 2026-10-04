# VAHAN Dashboard

React/TypeScript/Vite. Docker build static assets, Nginx proxy API + Socket.IO cùng origin. `VITE_API_URL` để trống khi dùng Docker; local dev có thể đặt `http://127.0.0.1:8000`.

AuthGate nạp user state PostgreSQL trước khi mount dashboard. Ma trận, batch và active job lưu theo tài khoản. Settings quản lý tài khoản; Reports có thư viện file. CAPTCHA cần người dùng nhập.

```bash
npm ci
npm run build
```

Xem [README gốc](../../README.md) để chạy toàn bộ stack.

Nút **Copy errors** nằm ngay dưới **Activity** trên giao diện chính, thay cho bảng lỗi. Lỗi có cùng thông báo gốc được gộp thành một mục trong nội dung sao chép, kể cả khi xuất hiện ở nhiều báo cáo hoặc khi chạy lại; bỏ tiền tố/suffix retry do giao diện thêm và chuẩn hoá khoảng trắng khi so sánh. Các thông báo khác nhau vẫn là lỗi riêng. Nội dung sao chép có thông báo, số lần gặp, số lần đã khôi phục, thời gian GMT+7, báo cáo liên quan, mô tả và gợi ý xử lý. Nút báo **Copied** khi sao chép thành công và bị vô hiệu hoá khi chưa có lỗi. Lịch sử vẫn lưu theo tài khoản bằng user state PostgreSQL, giữ 500 lần lỗi gần nhất. NO_DATA và thao tác Stop không được tính là lỗi job. Kiểm tra bằng `npm run test:run-errors` và `npm run test:batch`.

Batch chạy theo nhóm 10 case. Khi nhóm hoàn thành, chạy lại một lần các case lỗi trong đúng nhóm đó, theo thứ tự ban đầu, rồi mới chạy nhóm tiếp theo. Nhóm cuối dưới 10 case cũng được kiểm tra. Case vẫn lỗi sau lần thử lại giữ Failed để có thể chạy lại thủ công.

Lần thử lại giữ nguyên session và toàn bộ filter, gửi `retryOfJobId` của lần chạy lỗi trước. Báo cáo đếm mỗi case một lần với trạng thái mới nhất, tự cập nhật Failed / With data / No data và file tải về. Nút Retry failed cũng cập nhật session gốc. Lịch sử các lần chạy vẫn lưu trong PostgreSQL.

Run history có nút **Delete session** trên mỗi thẻ, với xác nhận trước khi xóa. Phiên vào **Deleted sessions**, có thể **Restore session**. File và dữ liệu tháng được giữ nguyên. Backend chặn xóa phiên có job/batch đang chạy và chặn tiếp tục/retry phiên đã xóa cho đến khi khôi phục. Người dùng chỉ xóa/khôi phục phiên của mình; admin có thể quản lý toàn bộ.

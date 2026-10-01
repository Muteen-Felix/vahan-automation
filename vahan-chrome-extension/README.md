# Vinfast RPA Assistant

Chrome Extension Manifest V3 chạy trực tiếp trên máy client và là runner cho Web UI/backend. Cấu hình bộ lọc, kịch bản và báo cáo được quản lý trên Web UI; extension chỉ nhận job, thao tác trên tab VAHAN, rồi đồng bộ file Excel về backend. Người dùng luôn tự nhập CAPTCHA.

Popup trên thanh extension được rút gọn để hiển thị kết nối backend, trạng thái job hiện tại và cấu hình backend. Extension không chèn widget nổi hoặc nút điều khiển lên trang VAHAN.

## Cài vào Chrome

1. Mở `chrome://extensions`.
2. Bật **Developer mode**.
3. Chọn **Load unpacked**.
4. Chọn thư mục `vahan-chrome-extension`.
5. Mở `https://analytics.parivahan.gov.in/analytics/vahanpublicreport?lang=en`.
6. Mở Web UI, chọn runner **VAHAN Chrome** và tạo báo cáo.
7. Mở popup extension khi cần kiểm tra kết nối/tiến trình hoặc đổi cấu hình backend.
8. Nhập CAPTCHA trên Web UI; extension tiếp tục luồng trên VAHAN.

Không tự động đọc, giải hoặc vượt CAPTCHA. Đây là attended RPA.

## Bảo vệ khi VAHAN yêu cầu đăng nhập HTTP

Nếu tài liệu HTML chính của VAHAN trả `401/HTTP Basic Auth` sau nhiều lần tải
hoặc kiểm thử, extension sẽ không tự điền tài khoản/mật khẩu. Guard chỉ khóa
khi challenge thuộc `main_frame`; 401 của ảnh/CSS/API phụ chỉ hủy request đó,
không làm đỏ toàn bộ hệ thống khi giao diện vẫn dùng được. Với challenge chính,
extension ghi trạng thái `VAHAN_AUTH_REQUIRED`, dừng retry/reload và hiện cảnh
báo trong popup. Trạng thái tạm dừng kéo dài 15 phút để tránh tiếp tục gửi
request vào máy chủ.

Khi gặp trường hợp này: bấm **Cancel** trên hộp thoại Chrome, chờ máy chủ
phục hồi, mở/tải lại đúng trang VAHAN chính thức rồi mở popup và chọn **Đã
đóng hộp thoại, cho phép thử lại**. Không nhập credential vào extension nếu
đây là trang VAHAN public thông thường.

## Kết nối backend MVP

Extension bundle `socket.io-client` vào service worker. Sau khi sửa
`src/background.js`, cần build lại:

```powershell
npm.cmd install
npm.cmd run build
```

Mặc định extension kết nối `http://127.0.0.1:8000/runner` với token
`change-me`. Có thể đổi Server URL, tên runner và token trong phần **Kết nối
backend** của popup. Chrome 116 trở lên được yêu cầu để WebSocket activity giữ
Manifest V3 service worker hoạt động.

## Luồng tải Excel và báo cáo đã xuất

Khi VAHAN hiện nút tải, extension chờ download native của Chrome hoàn tất
(`chrome.downloads.onCreated/onChanged`) và **không hủy** file tải xuống. Đồng
thời extension gửi bản Excel không rỗng lên backend để gắn với job. Sau khi
upload thành công job mới chuyển sang `COMPLETED`; khi đó file xuất hiện ở mục
**Báo cáo đã xuất** trên Web UI và có thể tải lại từ máy chủ.

Sau mỗi lần sửa extension, vào `chrome://extensions`, bấm **Reload** cho
extension rồi tải lại tab VAHAN chính thức. Nếu chỉ build mà không Reload,
Chrome vẫn chạy service worker/content script cũ và có thể tiếp tục báo
`The captured Excel file is empty.`

## UI Drift Protection — đã hoãn, chưa wire vào bản này

Nhánh `develop` từng có `ui-drift.js` (kiểm tra chữ ký UI VAHAN fail-closed
trước/sau Apply). File này **vẫn còn trong repo** nhưng **không được nạp** qua
`manifest.json`/`content.js` hiện tại — vì `content.js` của nhánh này đi theo
kiến trúc server-orchestrated (không tương thích trực tiếp với luồng UI drift
cũ). Đây là quyết định merge có chủ đích (ưu tiên giữ toàn bộ tính năng
server-job/batch runner), không phải xoá bỏ — cần port lại UI Drift Protection
sang kiến trúc hiện tại ở một nhánh riêng sau.

# Tài khoản test (TEST-ACCOUNTS, D-13)

Gói **không kèm credential**. Người test tự tạo tài khoản trên môi trường của mình.

## Admin bootstrap

1. `py -3 scripts/setup-docker.py` sinh `VAHAN_UI_AUTH_USERNAME` (mặc định `admin`) và `VAHAN_UI_AUTH_PASSWORD` ngẫu nhiên trong `.docker.env`.
2. Lần khởi động đầu, API tạo admin này trong DB. Đăng nhập tại web, vào **Settings** và dùng **Change password** (≥ 12 ký tự).
3. Sau khi đổi, mật khẩu trong `.docker.env` **không còn được dùng**; đừng chia sẻ file này.

## Member

1. Admin: trong **Settings**, mục quản lý tài khoản, nút **Create account** (username `[a-zA-Z0-9_.@-]`, mật khẩu ≥ 12 ký tự, role *Member*).
2. Giao mật khẩu qua kênh riêng của nhóm; bắt người nhận đổi ngay lần đăng nhập đầu.
3. Member chỉ xem/xuất báo cáo năm và quản lý đăng nhập của chính mình; mọi API admin (users, audit, lịch, Run History) trả **403**.

## Tạo bằng API (tùy chọn, dùng cho tự động hóa)

`POST /api/users` với Bearer token admin: `{"username": "...", "password": "...", "role": "user"}` → 201.
Vô hiệu hóa: `PATCH /api/users/<username>` `{"active": false}`. Không có API xóa user.

## Phiên

Phiên tối đa 12 giờ, hết hạn nếu không hoạt động 60 phút. Đổi mật khẩu hoặc vô hiệu hóa làm mọi phiên của tài khoản đó hết hiệu lực.
Sau khi nâng cấp qua migration `0012` phải đăng nhập lại.

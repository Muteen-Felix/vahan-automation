# Dữ liệu test (TEST-DATA, D-14)

Gói **không kèm dump**; dữ liệu bắt đầu từ DB trống và một filter profile nhỏ do người test tạo (dump có users/sessions/browser state).

## Chuẩn bị

1. Cài và đăng nhập (`INSTALL.md`, `TEST-ACCOUNTS.md`).
2. Trong màn hình bộ lọc: chọn **một** năm, **một** State, **một–hai** RTO (vài case, chạy xong trong vài phút) và **Save filters**.
   Dùng **Preview** để xem số case dự kiến.
3. **Settings → Show form**: chọn *Saved filters*, *Start date*/*Start time* vài phút sau, *Repeat* = **Once**, rồi **Add schedule**.
   Ứng dụng không có nút "chạy ngay"; mọi lượt chạy đi qua lịch.
4. Xem kết quả ở bảng báo cáo năm, danh sách báo cáo đã xuất và **Run History** (chỉ admin).

## Kịch bản Once / Monthly

Lịch chỉ có **Once** hoặc **Every month** (không còn Daily). Múi giờ (Việt Nam hoặc Ấn Độ) được chọn trong Settings và áp dụng cho form tạo lịch.
Monthly chạy vào ngày đã chọn mỗi tháng (tháng ngắn → ngày cuối tháng) và chuyển sang bộ lọc/lịch của năm sau khi hết năm.

## Reset

| Mục tiêu | Cách | Mất dữ liệu? |
| --- | --- | --- |
| Chạy lại cùng profile | Chạy lại: case đã lưu hiển thị "Already saved" | Không |
| Xóa lịch/lượt chạy | UI: tạm dừng rồi **Delete schedule** (giữ báo cáo đã thu) | Chỉ lịch + queue dở |
| DB sạch hoàn toàn | `docker compose --env-file .docker.env down -v` rồi cài lại | **Tất cả** (kể cả user) |

Chỉ dùng `down -v` trên môi trường test. Không chạy trên máy có dữ liệu cần giữ.

# E2E checklist trên artifact (T27, C4.2)

Chạy sau khi `INSTALL.md` §4–5 đạt. Ghi kết quả vào `evidence/e2e-<rc>.md` kèm ảnh chụp/log; mỗi bước đạt/không đạt + thời điểm UTC.
Dùng **một profile nhỏ** (1 năm, 1 State, 1–2 RTO) theo `TEST-DATA.md`.

| # | Bước | Kỳ vọng |
| --- | --- | --- |
| 1 | `release-smoke.py` (SMOKE.md) | exit 0, `failed: 0`, `skipped: 0` |
| 2 | Đăng nhập admin, đổi mật khẩu | vào được dashboard; phiên mới hoạt động |
| 3 | Lưu filter profile, Preview | số case xem trước > 0 |
| 4 | UI Health preflight | PASS (nếu BLOCKED: ghi diagnostics, **không** tắt gate) |
| 5 | Tạo lịch **Once** vài phút sau | lịch ở `WAITING`, hiển thị đúng giờ và múi giờ |
| 6 | Lịch tới giờ | chạy; ETA hiển thị sau kết quả đầu; số case = Preview |
| 7 | Pause rồi Resume giữa chừng | không mất/trùng case; trạng thái PAUSED rồi RUNNING |
| 8 | Chạy xong | kết quả vào bảng năm; số dòng khớp queue; Run History đúng một dòng |
| 9 | Export Excel (có lọc State/RTO và Export all) | file mở được; số dòng = header `X-Report-Row-Count` = số dòng bảng |
| 10 | Chạy lại cùng profile | case đã lưu hiển thị "Already saved", không trùng |
| 11 | Restart API giữa job (`docker compose restart api`) | case `PROCESSING` giữ hoặc retry sau lease; 0 mất, 0 trùng |
| 12 | Member: đăng nhập, thử API admin | thấy báo cáo; 403 ở users/audit/lịch/Run History |
| 13 | Lịch Monthly (ngày 31, tháng ngắn) | `nextRunAt` là ngày cuối tháng |
| 14 | Xóa lịch đã chạy | báo cáo đã thu còn; Run History giữ tên bộ lọc |
| 15 | Entry point đã gỡ | `/api/maker-updates` → 404; `POST /api/jobs` có `updateKind` → 422; `/api/ui-health/schedule`, `/run-now` → 404; `/docs`, `/openapi.json` → 404 |
| 16 | `docker compose stop` rồi khởi động lại | dữ liệu và đăng nhập còn |

Điều kiện đạt: mọi bước đạt, 0 lỗi Blocker/Critical mới. Lỗi tài liệu → ghi defect, sửa INSTALL và chạy lại từ bước lỗi.

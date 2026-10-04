# Kiểm chứng flow điền song song — 02/10/2026

## Phạm vi

Một worker giữ một case đang hoạt động. Trong case, 5 nhóm điền đồng thời; các trường phụ thuộc giữ đúng thứ tự. Sau khi điền và trước Apply, toàn bộ giá trị được đọc lại từ DOM rồi đối chiếu với filters gốc ở API. Dấu kiểm tra và thời gian nhóm lưu trong PostgreSQL JSONB `jobs.payload.filter_execution`.

## Kiểm thử

- `npm run check`: cú pháp worker và driver hợp lệ.
- `npm run test:filters`: 7 kiểm tra Chromium, gồm 26 control trong fixture đầy đủ, ngày bắt đầu/kết thúc, dependency fetch/XHR tải chậm, reset muộn, tái sử dụng trang, tên Maker có dấu phẩy, mismatch/disabled/duplicate, unsupported filter, lỗi nhóm và fill đồng thời bị từ chối.
- `npm run test:lifecycle`: 6 kiểm tra thứ tự ACK `SUBMITTING`, kiểm tra bộ lọc và lưu bằng chứng trước Apply; không click khi verification lỗi, job đã đổi hoặc submission lặp.
- `npm run test:results`: 14 kiểm tra populated/no-data/stale/wrong-RTO/loading/navigation và subcategory giữ nguyên danh sách.
- `verification/test_report_results.py`: 17 test PostgreSQL/API qua database riêng `vahan_results_parallel_test`; database test đã được xóa sau kiểm thử. Bao gồm hai phase lưu bền vững, timestamp đầy đủ và từ chối proof thiếu field/sai case/sai selector/sai giá trị/trùng field/sai runner/job bị hủy; rollback và idempotency kết quả vẫn qua.
- `git diff --check`: không lỗi whitespace.

Fixture so sánh cùng Chromium và delay request 140 ms, 3 lần cho mỗi driver:

| Driver | Các lần điền (ms) | Median (ms) |
| --- | --- | --- |
| Trước thay đổi | 844, 841, 848 | 844 |
| Điền song song có verification | 560, 562, 568 | 562 |

Median giảm 33%. Đây là số đo fixture, không suy ra mức tăng tốc cố định trên mạng VAHAN. Snapshot driver trước thay đổi dùng trong phép so sánh nằm tại `/tmp/vahan-parallel-fill/page-driver-before.js`.

## Chạy thực tế với Docker đã cập nhật

API và runner đã rebuild và recreate. PostgreSQL, API, runner, web đều healthy; `/api/ready` và dashboard HTTP 200. Docker được cập nhật khi worker đã rảnh.

| Case | Job ID | Kết quả | Điền + kiểm tra (ms) | Control kiểm tra ở mỗi phase | SQL / file |
| --- | --- | --- | --- | --- | --- |
| Port Blair DTO - AN1 | `629454b9-cc68-406e-aff9-0c307bd5aff8` | COMPLETED | 433 | 24 | 1 bảng; 3 Maker tổng 64; 5 dòng DOM gồm tiêu đề/tổng; Excel 16.252 byte, 6 dòng trích xuất |
| Teressa - AN210 | `26b16eab-f539-4f9b-8bf2-6e8f8b256f8e` | NO_DATA | 239 | 24 | `No record found`, TXT; không Excel |

Mọi control đều `match: true` ở hai phase `filled` và `before-apply`. Case Port Blair không cần lượt sửa; 5 nhóm bắt đầu trong 1–2 ms kể từ lúc bắt đầu fill. SQL giữ thời điểm thu thập theo UTC, tương ứng 02/10/2026 15:44:16 và 15:46:02 ở Việt Nam. Các job lịch sử lỗi/hủy được giữ nguyên.

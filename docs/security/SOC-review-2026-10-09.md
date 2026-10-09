# Review các thay đổi SOC — 09/10/2026

Kết luận: cần sửa các lỗi dưới đây trước khi nghiệm thu production cho nhiều doanh nghiệp. Review không thay đổi mã ứng dụng, cấu hình tenant thật hoặc dịch vụ đang chạy.

## Phát hiện

### R1 — P1: tenant `automation` trùng project của hệ thống chính

- Vị trí: `scripts/security_setup.py:41`, `scripts/provision-tenant.py:26–34`, `scripts/run-docker.py:43,58–69`.
- Tenant `legacy` mặc định dùng `vahan-automation`; tenant hợp lệ tên `automation` cũng mặc định dùng `vahan-automation`. Provisioner kiểm tra port/origin, không kiểm tra trùng Compose project.
- Tái hiện với hai file env tạm và port riêng: cả hai tenant được chấp nhận, cùng project `vahan-automation`.
- Khi chạy `--up`, launcher chọn container/volume bằng project này và drain/stop trước khi migrator kiểm tra database identity. Database đã có identity sẽ từ chối muộn, sau khi dịch vụ bị ảnh hưởng. Với database cũ chưa có identity và credential DB hợp lệ được tái sử dụng, migrator còn có thể nhận database cũ làm database của tenant mới; credential mới ngẫu nhiên không tự vượt qua xác thực DB.
- Sửa: kiểm tra project duy nhất và tenant ownership của container/volume/database trước mọi drain/backup/up/stop; chặn tên project dành riêng và cấu hình collision. Không chỉ dựa vào kiểm tra khi API startup.

### R2 — P1: stop thất bại một phần có thể mở lại queue

- Vị trí: `scripts/run-docker.py:62–72`.
- `changed=True` chỉ được đặt sau khi lệnh stop thành công. Compose có thể đã dừng một số service rồi trả lỗi; nhánh `finally` khi đó vẫn gọi `resume()`.
- Fault injection: mock lệnh stop trả `CalledProcessError`; xác nhận `resume()` được gọi dù stop đã được thực hiện. Không dừng container thật.
- Hậu quả: API/worker còn sống có thể nhận việc mới trong stack thiếu service, trái với chính sách giữ gate đóng sau khi bắt đầu thay đổi runtime.
- Sửa: đánh dấu bắt đầu mutation trước lệnh stop; giữ gate khi kết quả stop không rõ hoặc thất bại. Quy trình phục hồi chỉ mở gate sau khi kiểm tra đầy đủ dịch vụ.

### R3 — P2: collector mới có khoảng mù cảnh báo

- Vị trí: `docker/soc/collector.py:36–37,124–136,142–145`.
- Bảng `events` chỉ được tạo khi event đầu tiên đến. Watchdog trên volume mới truy vấn bảng chưa tồn tại rồi nuốt exception. Nếu API và backup không gửi event từ đầu, collector không cảnh báo dù đã quá ngưỡng.
- Tái hiện bằng SQLite tạm và đồng hồ giả: sau 4.000 giây có 0 file cảnh báo; sau khi khởi tạo bảng bằng một event, cùng watchdog phát cảnh báo `backup-stale`.
- Sửa: tạo schema trước khi khởi chạy watchdog/HTTP server; báo lỗi watchdog có cấu trúc và phản ánh trạng thái suy giảm.

### R4 — P2: health collector không kiểm tra khả năng lưu log

- Vị trí: `docker/soc/collector.py:82–85`, `compose.yaml:285–289`.
- `/health` trả 200 vô điều kiện. Khi volume không truy cập được hoặc SQLite không ghi được, ingest có thể trả 503 nhưng Docker vẫn coi SOC healthy, API vẫn vượt dependency health check.
- Tái hiện: đặt DATA vào thư mục không tồn tại; handler `/health` vẫn trả 200 `status=ok`.
- Sửa: readiness kiểm tra storage/schema và freshness của watchdog; trả 503 khi không thể ghi bền vững. Giữ liveness riêng nếu cần.

### R5 — P2: chữ ký release chưa được cưỡng chế khi deploy

- Vị trí: `scripts/run-docker.py:38–46`, `scripts/release-provenance.py:44–51`.
- Manifest được ký và tự kiểm tra khi tạo, nhưng launcher nhận `--image-overrides` trực tiếp mà không xác thực manifest/signature hoặc đối chiếu image ID. Override cũng không nằm trong nội dung được ký.
- Tái hiện với override JSON tạm không có manifest/signature: launcher chuyển file vào Compose config và kết thúc thành công. Các lệnh Docker được mock, không chạy deploy thật.
- Manifest hiện tại có chữ ký hợp lệ và mọi source hash còn khớp. Đây là thiếu kiểm soát ở đường triển khai, không phải bằng chứng manifest hiện tại bị sửa hay image đã bị tấn công.
- Sửa: yêu cầu release bundle khi deploy production; xác thực bằng public key được pin ngoài bundle, đối chiếu image ID từng service và giới hạn override chỉ chứa image. Thực hiện trước mutation.

### R6 — P3: OTP Unicode gây lỗi xác thực nội bộ

- Vị trí: `apps/api-server/app/mfa.py:82–88`, `apps/api-server/app/api/auth.py:22,134`.
- `isdigit()` chấp nhận chữ số Unicode; `hmac.compare_digest()` với chuỗi Unicode không phải ASCII ném `TypeError`.
- Tái hiện `matching_counter(..., '１２３４５６')`: lỗi `comparing strings with non-ASCII characters is not supported`. Với mật khẩu hợp lệ và MFA đã bật, input này có thể làm luồng đăng nhập trả lỗi 500 thay vì từ chối OTP bình thường. Không chứng minh bypass MFA.
- Sửa: chỉ nhận `[0-9]{6}` cho TOTP, xử lý input recovery riêng và trả lỗi xác thực có kiểm soát.

## Kiểm chứng trong lần review này

- Sáu probe ở `diagnostics/soc/review-probes-2026-10-09.json`; dùng env/SQLite tạm, mock deployment và fault injection. Các probe không chứng minh outage thực tế đã xảy ra.
- Chạy lại `verification/test_soc_unit.py`: 9/9 pass. Bộ hiện tại chưa bắt các lỗi trên.
- Đọc trực tiếp `docker ps`: stack chính vẫn chạy `vahan-db-capacity/{api,web,runner}:20261008` và `postgres:17.7-bookworm`, các container báo healthy. Không có service SOC/backup/documents trong project chính. Thay đổi SOC chưa được áp dụng vào runtime chính.
- Xác minh chữ ký manifest local hợp lệ, không có source hash bị lệch hoặc file nguồn thiếu.
- Các kết quả integration, browser, restore và CVE ở hồ sơ triển khai là bằng chứng từ lần kiểm thử trước; không chạy lại toàn bộ trong review này. Không diễn giải “0 fixable High/Critical” thành “không còn lỗ hổng”: hồ sơ vẫn có advisory High/Critical chưa có bản vá và cần triage.

## Thứ tự sửa và phạm vi còn lại

Sửa R1 và R2 trước; tiếp theo R3/R4, R5 rồi R6. Bổ sung kiểm thử collision tenant, lỗi stop một phần, collector volume mới/storage lỗi và release bị thay đổi.

Backup còn cần kiểm tra tình huống đĩa đầy, timeout/lock kéo dài và chính sách lưu giữ SOC/outbox. Chưa kết luận các tình huống đó đã gây lỗi thực tế trong lần review này. HA, hosted Windows/Ubuntu CI, thử tải, triage advisory còn lại và nghiệm thu hạ tầng vẫn chưa được chứng minh.

Lần triển khai SOC vào stack chính trước đó bị automatic approval review chặn do chưa có chấp thuận cụ thể cho drain/backup/restart và gián đoạn dịch vụ. Review này chỉ đọc trạng thái, không thử lại hành động bị chặn.

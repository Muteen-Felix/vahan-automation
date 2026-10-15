# Runbook vận hành bản thử

Mọi lệnh chạy tại thư mục cài đặt, dùng cùng `.docker.env` và Compose project
đã dùng khi cài. Không in password/token/key, không gửi `.docker.env` cùng
diagnostics. Đọc [hướng dẫn cài](deployment.md) trước khi dùng gói.

## Kiểm tra hàng ngày

```powershell
docker compose --env-file .docker.env ps
Invoke-RestMethod http://127.0.0.1:8000/api/ready
docker compose --env-file .docker.env logs --tail 100 api runner
```

Readiness xác nhận API/DB; health runner xác nhận API socket và Chromium
context. Hai tín hiệu này không chứng minh VAHAN form, CAPTCHA hoặc download
hoạt động. Kiểm UI Health và case thất bại trên web, đối chiếu coverage với
profile dự kiến. Chạy probe Chromium/Tesseract trong image:

```powershell
docker compose --env-file .docker.env run --rm --no-deps -e VAHAN_RUNTIME_LIVE_PROBE=1 --entrypoint node runner test-container-runtime.mjs
```

Probe OCR dùng ảnh tổng hợp, stdin, sandbox bật và không log chữ OCR thô.
Probe VAHAN chỉ điều hướng, không Apply hay tải báo cáo. Đọc `liveVahan`
trong JSON; lỗi TLS không được bỏ qua bằng `ignoreHTTPSErrors`.

## Pause, restart và cập nhật

1. Pause lịch/queue trong Settings; chờ case đang chạy drain. Kiểm trạng thái
   PAUSED và active job đã hoàn tất. Không dùng container restart thay Pause.
   Ngoại lệ lịch **Daily** (chỉ có ở bản trước migration `0015`): lịch Daily còn session, kể cả `PAUSED`, chặn migration — Resume
   rồi chờ hoàn tất, hoặc Stop/Delete trên bản cũ (hệ quả: `docs/release/INSTALL.md` §7).
2. Chạy guard và backup:

   ```powershell
   py -3 scripts/run-docker.py --check-release
   py -3 scripts/backup-docker.py
   ```

   Guard chỉ đọc; có active job, lease planning, queue/lịch chạy thì từ chối
   deploy. Backup gồm dump, `.docker.env` và manifest hash, chứa secrets và
   phải lưu riêng có kiểm soát truy cập.
3. Load image từ gói đã đối chiếu hash; cập nhật tag đúng manifest. Giữ secrets,
   project và volume. Chạy `py -3 scripts/run-docker.py --no-build --workers 1`.
4. Kiểm migration exit 0, API/web/runner healthy, readiness ngoài Docker,
   login, báo cáo đã lưu và UI Health. Resume cùng queue/session sau khi
   preflight đạt; không tạo run thay thế để che queue đang lỗi.

Không chạy song song hai API scheduler trên cùng DB trong bản single-host này.
Job/queue authority ở PostgreSQL; Socket.IO chỉ chuyển trạng thái. Worker mất
kết nối được xử lý bằng grace/lease và queue recovery, không sửa SQL bằng tay.

## Dừng và khởi động lại

```powershell
docker compose --env-file .docker.env stop
py -3 scripts/run-docker.py --no-build --workers 1
```

Docker Desktop cần chạy để container phục hồi sau reboot. Không dùng `down -v`
với dữ liệu cần giữ. Chưa xóa bất kỳ file nào trong `outputs/` cho tới khi
người quản lý đưa danh sách giữ/xóa.

## Restore vào môi trường tách biệt

Không restore đè DB đang chạy. Tạo thư mục/project phục hồi riêng, dùng cấu
hình backup với cùng encryption key, đặt cổng khác, load đúng image của backup
và xác minh SHA-256 trong manifest backup. Khởi động PostgreSQL trước:

```powershell
docker compose --env-file .docker.env up -d --no-build --wait postgres
# PowerShell không redirect dump nhị phân qua pipeline text.
docker compose --env-file .docker.env cp <backup-directory>/database.dump postgres:/tmp/restore.dump
docker compose --env-file .docker.env exec -T postgres pg_restore -U vahan -d vahan --clean --if-exists --no-owner --no-acl --exit-on-error /tmp/restore.dump
py -3 scripts/run-docker.py --no-build --workers 1
```

`--no-acl` tránh tham chiếu role chưa có trên cluster mới; `migrate` cấp lại
quyền runtime sau restore. Kiểm dữ liệu trước khi chuyển traffic; đọc phạm vi
restore đã thử trong báo cáo. Không rollback binary qua migration
không tương thích; dùng bản image/backup tương ứng tại project tách biệt.

## Chẩn đoán

| Triệu chứng | Thao tác |
| --- | --- |
| Login 429 | Chờ quota nginx hồi; không retry login liên tục. Kiểm proxy/IP nguồn. |
| Origin bị từ chối | So sánh URL dashboard với HTTP và Socket.IO allowlist trong `.docker.env`. |
| UI Health blocked | Giữ diagnostics; kiểm TLS, form/selector và source VAHAN. Không tắt gate. |
| OCR không tự hoàn thành | Kiểm trạng thái runner, CAPTCHA hiện tại và log Tesseract; ứng dụng không giới hạn số lần bắt đầu OCR. VAHAN có thể tự giới hạn hoặc yêu cầu xác minh. |
| Worker reconnecting | Kiểm API/socket/browser logs, chờ grace/lease. Đối chiếu caseId/jobId trước khi thao tác lại. |
| `/api/ready` lỗi | Kiểm PostgreSQL, migrate exit status và DB role; không cấp superuser cho API. |
| Dữ liệu không hiển thị | Kiểm year/dataset/State/RTO, coverage và lịch sử commit báo cáo. Không bật mẫu để che dữ liệu thiếu. |
| Cài lại thấy DB trống | Kiểm Compose project/volume; không tạo thêm run cho tới khi tìm đúng dữ liệu. |

Lưu commit/package manifest, timestamp UTC, lệnh, exit code, log có che secrets
và defect ID khi bàn giao. [Báo cáo Đợt 5](round5-review-evidence.md) phân biệt
test build bằng fixture với dữ liệu VAHAN thật.

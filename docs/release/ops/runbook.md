# Runbook vận hành bản release (T52a, Q7, O1)

Mọi lệnh chạy tại thư mục cài đặt với cùng `.docker.env` và cùng Compose project đã dùng khi cài. Không in secret; không gửi `.docker.env`
cùng log. Chi tiết chẩn đoán mở rộng: `docs/runbook.md` (trong source bundle).

## 1. Theo dõi tối thiểu (O1)

| Kiểm | Lệnh / nguồn | Ngưỡng cảnh báo |
| --- | --- | --- |
| Stack | `docker compose --env-file .docker.env ps` | service ≠ healthy, `migrate` ≠ Exited (0) |
| Sẵn sàng | `GET http://127.0.0.1:<WEB_PORT>/api/ready` từ **ngoài** stack, mỗi 1–5 phút | ≠ 200 |
| Runner | trang Settings / `GET /api/runners` | ít hơn N ONLINE > 5 phút |
| Lịch | Settings: trạng thái `Error`, `Waiting for network` | `Waiting for network` > 30 phút |
| Đĩa/RAM | `docker system df`, `docker stats --no-stream` | đĩa < 15% trống; runner bị OOM-kill |
| Backup | tuổi file backup mới nhất | > 24 giờ khi đang có lịch chạy |

Probe ngoài stack và kênh gửi cảnh báo do bên vận hành sở hữu; alerting đầy đủ chưa thuộc bản 1.0 (KI-06).

### Quy trình cảnh báo tối thiểu (DEF-24)

Người trực vận hành chịu trách nhiệm chạy probe từ host hoặc máy giám sát mỗi 1–5 phút
và kiểm tra tuổi backup hằng ngày. Khi bàn giao, ghi rõ tên người trực, người nhận escalations
và kênh liên lạc nội bộ trong sổ vận hành; không đưa thông tin cá nhân/secret vào evidence.
Đây là quy trình vận hành; repository chưa tự tạo lịch probe hoặc tự gửi thông báo.

1. Khi `/api/ready` khác 200 hoặc không kết nối được, xác nhận lại sau 60 giây.
   Nếu hai lần liên tiếp lỗi, báo người trực ngay; trường hợp mất dữ liệu/OOM lặp lại thì báo ngay lần đầu.
2. Ghi thời điểm UTC, project, SHA/manifest digest, URL probe, mã HTTP và trạng thái
   `docker compose --env-file .docker.env ps`. Chỉ thu log đã che secret.
3. Kiểm theo bảng sự cố bên dưới; nếu sau 15 phút chưa khôi phục, chuyển người phụ trách hệ thống.
   Runner thiếu quá 5 phút, chờ mạng quá 30 phút và backup quá 24 giờ cũng phải báo người trực.
4. Chỉ thay container sau khi `py -3 scripts/run-docker.py --check-release` cho phép.
   Với lỗi DB/migration, giữ evidence và chọn restore/rollback theo mục 3–4, không thử migration ngược.
5. Sau khi khôi phục, xác nhận `/api/ready` trả 200 hai lần liên tiếp, đủ runner ONLINE,
   queue/lịch tiếp tục đúng; ghi thời điểm kết thúc và nguyên nhân trước khi đóng sự cố.

### Đối chiếu lock với image đã đóng gói (DEF-25/26)

Chạy từ checkout chứa công cụ bổ sung, với source giải nén từ đúng gói được duyệt:

```powershell
py -3 scripts/compare-lock-image.py --manifest <package-manifest.json> --source-root <source-giai-nen> --expected-sha <full-SHA> --expected-manifest-digest <sha256> --out <evidence>/lock-image.json
```

Máy chạy cần Python có `packaging` (đã nằm trong môi trường kiểm thử API).
Công cụ chỉ chạy image ID đã có sẵn, không pull/build, tắt mạng và filesystem ghi của container probe;
kiểm revision, hash lock nhúng và toàn bộ dependency production Python/npm của API/runner.
Dependency build của web không còn trong image nginx, nên không nằm trong phép so này.
Kết quả khác version, thiếu/thừa package hoặc lệch hash lock là FAIL; không đọc được image là NOT_RUN.
Không sửa manifest hoặc dùng fingerprint cũ để thay cho phép kiểm mới.
PostgreSQL đối chiếu riêng reference pin trong source Compose với manifest, image ID/digest và platform;
image upstream không mang revision F.

## 2. Backup

```powershell
py -3 scripts/run-docker.py --check-release     # từ chối nếu còn job/lịch đang chạy
py -3 scripts/backup-docker.py                  # dump custom-format + .docker.env + manifest SHA-256
```

Backup chứa secret và `VAHAN_BROWSER_STATE_KEY`: lưu tách biệt, kiểm soát truy cập. Mất khóa này = không giải mã được browser state.

## 3. Restore (vào project tách biệt, không đè DB đang chạy)

```powershell
$env:COMPOSE_PROJECT_NAME = 'vahan-restore'          # + cổng khác trong .docker.env của bản restore
docker compose --env-file .docker.env up -d --no-build --wait postgres
docker compose --env-file .docker.env cp <backup>/database.dump postgres:/tmp/restore.dump
docker compose --env-file .docker.env exec -T postgres pg_restore -U vahan -d vahan --clean --if-exists --no-owner --no-acl --exit-on-error /tmp/restore.dump
py -3 scripts/run-docker.py --no-build --workers <N>      # migrate cấp lại quyền role runtime
```

Kiểm: đăng nhập, bảng năm, Run History, lịch Once/Monthly còn. Xác minh SHA-256 trong manifest backup trước khi restore.

## 4. Rollback

Rollback = dừng stack hiện tại + restore backup vào volume mới + dùng image của bản trước. **Không** hạ binary qua migration không tương thích.
Migration `0015` xóa lịch Daily và không có downgrade dữ liệu; khôi phục chỉ bằng backup. Revision `0014a_daily_schedule_guard`
chạy trước và dừng nâng cấp (không xóa, không ghi gì) nếu lịch Daily còn session — xử lý trên bản cũ theo INSTALL.md §7.

## 5. Sự cố thường gặp

| Triệu chứng | Thao tác |
| --- | --- |
| `/api/ready` 503 | Kiểm PostgreSQL healthy, `migrate` đã thoát 0, revision DB = head; không cấp superuser cho API |
| Runner mất kết nối | Chờ grace/lease; case `PROCESSING` được retry theo checkpoint; đối chiếu caseId trước khi thao tác lại |
| UI Health BLOCKED | Giữ diagnostics, kiểm TLS/selector VAHAN; **không** tắt gate |
| Login 429 | Giới hạn nginx; chờ, không retry liên tục |
| Image PostgreSQL | Chỉ dùng image chính thức theo digest trong `compose.yaml`; không tự build lại (`docs/release/pins.md`) |
| Hết RAM | Giảm `VAHAN_WORKER_REPLICAS` khi rảnh rồi khởi động lại; `--assess-only` để xem đề xuất |

Ghi lại: commit/manifest, thời điểm UTC, lệnh, exit code, log đã che secret, defect ID.

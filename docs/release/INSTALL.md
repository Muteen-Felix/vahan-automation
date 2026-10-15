# Cài đặt VAHAN RPA từ gói (INSTALL)

Tài liệu cho người cài **từ gói image đã đóng sẵn** (`docker load`), không build lại trên máy đích.
Giá trị `<VERSION>`, `<SHA12>`, `<N>` được điền theo manifest của gói (T52b).

## 1. Điều kiện

| Hạng mục | Yêu cầu |
| --- | --- |
| Docker | Docker Desktop (WSL2) hoặc Docker Engine chạy **Linux containers**, kèm Docker Compose v2 |
| Python | 3.12+ trên **host** (chỉ để chạy `scripts/*.py`); `py -3` trên Windows, `python3` trên Linux/macOS |
| Tài nguyên | ≥ 1,25 GiB RAM và 1,5 CPU cho mỗi runner, cộng PostgreSQL/API/web; ~15 GiB đĩa cho image. Chạy `python scripts/run-docker.py --assess-only` để biết số runner đề xuất |
| Cổng | `5173` (web) và `8000` (API) trên `127.0.0.1`, hoặc đổi trong `.docker.env` |
| Mạng | Ra được `https://analytics.parivahan.gov.in`. **Mạng không được thay chứng chỉ TLS tới VAHAN** (D-24 = A, KI-15): nếu có proxy phá TLS thì image đã đóng gói không gọi được VAHAN và không thuộc phạm vi hỗ trợ của bản 1.0 |
| Nền tảng đã kiểm | Windows 11 + Docker Desktop/WSL2 (amd64). Ubuntu Engine / macOS: chỉ có trong tài liệu, chưa kiểm runtime (KI-04) |

## 2. Kiểm gói và nạp image

Gói gồm `vahan-<SHA12>-source.zip`, `vahan-<SHA12>-images.tar`, `vahan-<SHA12>-manifest.json` (và `SHA256SUMS` nếu có).

```powershell
Get-FileHash .\vahan-<SHA12>-source.zip -Algorithm SHA256    # so với manifest.files
Get-FileHash .\vahan-<SHA12>-images.tar -Algorithm SHA256
docker image load -i .\vahan-<SHA12>-images.tar
docker image ls                                              # phải có đủ 4 image (mục 3)
```

**Dừng nếu** SHA-256 không khớp manifest hoặc thiếu image.

## 3. Bốn image phải có sau `docker load`

| Image | Nguồn | Kiểm |
| --- | --- | --- |
| `vahan-review/api:<SHA12>` | tự build | ID khớp `manifest.imageIds` |
| `vahan-review/runner:<SHA12>` | tự build | ID khớp |
| `vahan-review/web:<SHA12>` | tự build | ID khớp |
| `docker.io/library/postgres:17.11-bookworm@sha256:3645570c…3826` | **image chính thức, pin digest** (không tự build) | ID/digest khớp `manifest.images`, platform `linux/amd64` |

```powershell
docker image inspect --format "{{.Id}}  {{index .RepoTags 0}}" vahan-review/api:<SHA12> vahan-review/runner:<SHA12> vahan-review/web:<SHA12>
docker image inspect --format "{{.Id}}  {{.Os}}/{{.Architecture}}" docker.io/library/postgres:17.11-bookworm@sha256:3645570cccdfa447589da9f57dd740faa29b30938e861289a5574b6ca6b03826
```

## 4. Cấu hình và khởi động

```powershell
Expand-Archive .\vahan-<SHA12>-source.zip -DestinationPath .\vahan-installed
Set-Location .\vahan-installed
py -3 scripts/setup-docker.py          # tạo .docker.env với secret ngẫu nhiên; KHÔNG ghi đè khóa đã có
```

1. Mở `.docker.env` (file được bảo vệ quyền, **không gửi cùng log**). Đặt `VAHAN_IMAGE_NAMESPACE=vahan-review` và
   `VAHAN_IMAGE_TAG=<SHA12>` đúng manifest. Biến khác: `docs/release/config/config-reference.md`.
2. Dùng project riêng nếu máy đã có stack khác: `$env:COMPOSE_PROJECT_NAME='vahan-trial'` (Linux: `export …`) cho **mọi** lệnh sau.
3. Khởi động bằng image đã nạp, **không build**:

```powershell
py -3 scripts/run-docker.py --no-build --workers <N>      # hoặc bỏ --workers để launcher chọn theo CPU/RAM
docker compose --env-file .docker.env ps                  # postgres, api, web, runner×N: healthy; migrate: Exited (0)
```

Thứ tự đúng: `postgres` healthy → `migrate` (owner `vahan`, chạy migration rồi cấp quyền DML cho `DB_APP_USERNAME`) thoát 0 →
`api` chạy bằng role runtime hạn chế → `web`, `runner`. Mọi service healthy trong ≤ 5 phút.

## 5. Kiểm sau cài

```powershell
$env:VAHAN_SMOKE_ADMIN_PASSWORD = '<VAHAN_UI_AUTH_PASSWORD trong .docker.env>'
py -3 scripts/release-smoke.py --base-url http://127.0.0.1:5173 --admin-user admin --min-runners <N> `
    --compose-project <tên project> --require-compose-checks --output smoke.json
```

Mong đợi: exit 0, `failed: 0`, `skipped: 0`. Chi tiết: `docs/release/SMOKE.md`. Sau đó đăng nhập tại `http://127.0.0.1:5173`
(`TEST-ACCOUNTS.md`).

## 6. Dừng, khởi động lại, gỡ cài đặt

```powershell
docker compose --env-file .docker.env stop                 # dữ liệu còn trong volume
py -3 scripts/run-docker.py --no-build --workers <N>       # khởi động lại (không build)
docker compose --env-file .docker.env down                 # gỡ container, GIỮ volume
```

**Không** dùng `down -v` nếu cần giữ dữ liệu. Gỡ hẳn (mất dữ liệu): `down -v` rồi xóa thư mục cài đặt và image `vahan-review/*`.
Reset dữ liệu test: `TEST-DATA.md`.

## 7. Nâng cấp tại chỗ (có dữ liệu)

Áp dụng khi máy đã chạy một bản cũ. **Không** `down -v`; **không** dùng `docker compose up` với tag cũ.

1. Chờ mọi lượt chạy theo lịch hoàn tất (**ưu tiên**). Bản cũ còn lịch **Daily** (chỉ bản trước migration `0015`): **không** Pause
   rồi để đó — lịch Daily `PAUSED` còn session vẫn **chặn migration** (bước 6). Nếu một lịch Daily đang `PAUSED`, Resume rồi chờ
   nó hoàn tất. Lịch Once/Monthly `PAUSED` không chặn. Nếu không thể chờ, làm trên **bản cũ**, trước khi nạp gói mới:
   - **Stop** lịch Daily: job đang chạy bị chuyển `CANCELLED` và runner được giải phóng; case chưa chạy ở lại hàng đợi
     (`PAUSED`) nhưng sau migration không còn lịch để Resume (hàng đợi mồ côi; report và lịch sử vẫn còn). Lượt đã dừng có thể
     hiện tên bộ lọc "Unnamed filter" trong Run History vì lịch không còn tham chiếu session đó (chưa kiểm trên UI).
   - **Xóa** lịch Daily: chỉ khi hàng đợi `PAUSED` và không còn job đang chạy; **xóa hàng đợi cùng các case chưa hoàn tất**,
     giữ report, job, file và Run History (tên bộ lọc được lưu). Không hoàn tác ngoài backup.
2. `py -3 scripts/run-docker.py --check-release` — từ chối khi còn job/lịch đang chạy **hoặc lịch Daily còn session (kể cả
   `PAUSED`)** (chỉ đọc).
3. Backup: `py -3 scripts/backup-docker.py` (dump + `.docker.env` + manifest hash; **chứa secret**, lưu riêng, kiểm soát truy cập).
   Thử restore dump vào project tách biệt trước khi nâng cấp (`ops/runbook.md`).
4. `docker load` gói mới (mục 2–3), đặt `VAHAN_IMAGE_TAG` mới, chạy `py -3 scripts/setup-docker.py` (bổ sung `DB_APP_USERNAME`/
   `DB_APP_PASSWORD` nếu `.docker.env` cũ chưa có; **không đổi khóa cũ**; `DB_APP_PASSWORD` ≥ 24 ký tự).
5. `py -3 scripts/run-docker.py --no-build --workers <N>`; kiểm `migrate` exit 0 (migration tự chạy khi nâng cấp), API healthy, đăng nhập lại.
6. Từ bản có migration `0015`: **lịch Daily đã lưu bị xóa** (chỉ Once/Monthly còn lại). Trước đó revision
   `0014a_daily_schedule_guard` **dừng cả lần nâng cấp, không xóa và không ghi gì** nếu còn lịch Daily có `sessionId` (bất kể
   status): `migrate` thoát ≠ 0, API không lên, log `migrate` liệt kê ID/owner/tên/status của lịch bị chặn — gỡ trên bản cũ
   (bước 1) rồi nâng cấp lại. Khi chạy được: số lượng + ID được ghi vào log `migrate` và `app_settings` key
   `migration-audit:0015_remove_daily_schedules`. Report/job/session/lịch sử không bị xóa.
7. Chạy lại `docker compose --env-file .docker.env run --rm migrate` lần hai: phải thoát 0 và không đổi gì (idempotent).

Rollback = dừng stack và restore backup vào volume mới (`ops/runbook.md`); migration không có downgrade cho dữ liệu đã xóa.

## 8. HTTPS / proxy

Stack không tự cấp TLS (KI-05). Giữ `WEB_BIND_ADDRESS=127.0.0.1` và đặt reverse proxy HTTPS phía trước; cập nhật
`VAHAN_API_CORS_ORIGINS` / `VAHAN_API_SOCKETIO_CORS_ORIGINS` theo origin HTTPS thực tế. Tài liệu API bị tắt ở production: `/api/docs`, `/api/openapi.json`, `/api/redoc` → 404 với token admin (401 không token). Ở gốc web, `/docs`, `/openapi.json`, `/redoc` trả shell SPA (200), không phải Swagger.

## 9. Lỗi thường gặp

| Triệu chứng | Nguyên nhân / cách xử lý |
| --- | --- |
| `migrate` thoát ≠ 0 | `docker compose --env-file .docker.env logs migrate`; thường do `DB_APP_PASSWORD` < 24 ký tự hoặc DB đang bị client khác giữ |
| Compose báo thiếu biến | Chạy lại `scripts/setup-docker.py`; không sửa tay thành chuỗi rỗng |
| Runner không online | `docker compose logs runner`; kiểm `VAHAN_API_RUNNER_TOKEN` giống nhau ở api/runner và mạng ra VAHAN |
| Login 429 | Giới hạn nginx; chờ vài phút, không thử lặp |
| Cài lại thấy DB trống | Sai Compose project/volume — dừng, không tạo dữ liệu mới cho tới khi tìm đúng volume |

# Cài đặt từ gói thử

Gói thử gồm `vahan-<SHA>-source.zip`, `vahan-<SHA>-images.tar` và
`vahan-<SHA>-manifest.json`. Manifest ghi commit nguồn, SHA-256 của hai file
và ID của bốn image. Gói không chứa `.docker.env`, CA của công ty, backup,
Git metadata hay `outputs/`. Không xóa hay di chuyển file trong `outputs/`
ở checkout hiện có khi cài hoặc cập nhật.

## Điều kiện

Docker Engine/Docker Desktop chạy Linux containers, Docker Compose và Python
3.12 trở lên. Windows dùng PowerShell, `py -3`; Linux/macOS dùng `python3`.
Gói image đã build không cần npm, Python API dependencies hoặc Tesseract trên
host. Máy vẫn cần mạng tới VAHAN để lấy báo cáo. Test UI dành cho developer
cần Node 22, dependencies npm và browser Playwright/Chrome trên host.

## Tạo gói từ commit

Chạy tại repository. Chỉ nội dung của commit được đóng gói; sửa chưa commit
không được đưa vào gói. Thư mục đích mới tránh ghi đè bằng chứng cũ.

```powershell
py -3 scripts/build-review-package.py --ref HEAD --with-images --output-dir diagnostics/review-package
```

`--with-images` build bốn image với SBOM/provenance rồi `docker image save`.
Nếu chỉ tạo source zip, bỏ cờ này; bản source cần build và Internet khi cài.
Image chứa CA riêng phải được build tại môi trường đích bằng source package;
công cụ tạo gói không tự đưa CA không được theo dõi bởi Git vào gói.

## Cài mới bằng image đã đóng gói

1. Đối chiếu SHA-256 với manifest trước khi giải nén/load. Ví dụ:

   ```powershell
   Get-FileHash .\vahan-<SHA>-source.zip -Algorithm SHA256
   Get-FileHash .\vahan-<SHA>-images.tar -Algorithm SHA256
   docker image load -i .\vahan-<SHA>-images.tar
   Expand-Archive .\vahan-<SHA>-source.zip -DestinationPath .\vahan-installed
   Set-Location .\vahan-installed
   py -3 scripts/setup-docker.py
   ```

2. Mở `.docker.env` tại máy đích. Đặt `VAHAN_IMAGE_NAMESPACE` và
   `VAHAN_IMAGE_TAG` đúng giá trị trong manifest (`vahan-review`, SHA rút gọn).
   Giữ những password/token/key được tạo mới; không gửi file này cùng log.
   Đặt `API_PORT`/`WEB_PORT` và origin allowlist theo địa chỉ dashboard thực tế.
   Nếu dùng project riêng, đặt `$env:COMPOSE_PROJECT_NAME = 'vahan-trial'`
   trong cùng PowerShell cho mọi lệnh Compose/launcher/backup.

3. Khởi chạy bằng gói, không build lại:

   ```powershell
   py -3 scripts/run-docker.py --no-build --workers 1
   docker compose --env-file .docker.env ps
   Invoke-RestMethod http://127.0.0.1:8000/api/ready
   ```

   Linux/macOS dùng `export COMPOSE_PROJECT_NAME=vahan-trial` và `python3`.
   Chọn worker count thủ công cho bản thử; launcher đánh giá tài nguyên khi
   không có `--workers`. Không dùng image tag của gói khác.

4. Mở `http://127.0.0.1:5173`, đăng nhập bằng hai khóa bootstrap trong
   `.docker.env`, đổi password trong Settings. Database mới không có dữ liệu
   báo cáo mẫu. API `/docs`, `/redoc`, `/openapi.json` trả 404 trong production.
   Không dùng `/docs` trên cổng web để kiểm API: Nginx có SPA fallback.

## Cài từ source và CA riêng

```powershell
py -3 scripts/setup-docker.py
# Nếu cần: đặt CA gốc đã xác minh vào docker/certs/*.crt trước khi build.
py -3 scripts/run-docker.py --workers 1
```

Không tắt TLS verification hoặc Chromium sandbox để vượt lỗi chứng chỉ.
CA được cài vào image chưa chứng minh Chromium tin chuỗi chứng chỉ VAHAN;
phải chạy probe trong [runbook](runbook.md).

## Nâng cấp và dữ liệu

Xem [runbook](runbook.md) để pause/drain, backup và kiểm deployment guard trước
khi cập nhật. `migrate` chạy provisioning/migration bằng DB owner; API sử dụng
`vahan_app` với quyền DML hạn chế. Giữ nguyên `VAHAN_BROWSER_STATE_KEY` và
signing/runner secrets của bản đang chạy khi nâng cấp.

Volume `postgres_data` phụ thuộc tên Compose project. Giữ đúng project cũ khi
nâng cấp; đổi tên project sẽ tạo database khác. `stop`/`down` giữ volume;
`down -v` xóa dữ liệu và chỉ được dùng trong test disposable.

## Tái hiện kiểm cài gói

```powershell
py -3 scripts/test-review-package.py --package-dir diagnostics/review-package --output-dir diagnostics/review-install
```

Script xác minh hash/image ID, giải nén vào thư mục mới, chạy launcher thật
bằng `--no-build`, cài DB mới, kiểm API/build UI/runner và ghi `results.json`
cùng log đã che secrets. Chỉ project có tên ngẫu nhiên `vahan-review-*` bị
dọn sau kiểm; stack đang dùng và `outputs/` của repository được giữ nguyên.
Phạm vi dữ liệu tổng hợp và phần VAHAN chưa kiểm được phải được đọc cùng
[báo cáo bằng chứng](round5-review-evidence.md).

Mặc định script **không** gọi VAHAN: preflight D3 được ghi `NOT_RUN` (không phải Pass).
Chỉ khi thêm `--vahan-preflight` nó mới chạy và được ghi riêng ở `d3` trong `results.json`
(`--live-case` cần kèm cờ này). Exit status: `0` = kiểm gói đạt (D3 `NOT_RUN` hoặc `PASS`),
`1` = kiểm gói lỗi, `2` = kiểm gói đạt nhưng D3 được yêu cầu mà không đạt.

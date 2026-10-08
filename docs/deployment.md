# Triển khai và đóng gói đa nền tảng

Ứng dụng được đóng gói thành các Linux container. Cùng một source và Compose file chạy trên Ubuntu, macOS và Windows thông qua Docker; Windows cần Docker Desktop ở chế độ Linux containers. Máy production nên dùng Ubuntu Server, Docker Engine và Compose plugin. Stack hiện là một máy chủ Compose: API, PostgreSQL, web và tối đa 10 Chromium workers không tự phân tán sang nhiều host.

## Nền tảng hỗ trợ

| Host | Cách chạy | Vai trò phù hợp |
| --- | --- | --- |
| Ubuntu Desktop/Server | Docker Engine + Compose plugin | Production hoặc phát triển |
| Windows 10/11 | Docker Desktop, backend WSL 2, Linux containers; chạy script PowerShell | Phát triển hoặc vận hành tại máy người dùng |
| macOS | Docker Desktop, Linux containers; chạy script shell | Phát triển và kiểm tra |

Không chạy các container này ở chế độ Windows containers. Browser runner dùng image Playwright Linux. Windows Server không phải target của Docker Desktop; dùng Ubuntu Server làm host production.

## Khởi động

Từ thư mục repository:

```powershell
./run-vahan-rpa.ps1
```

```bash
./run-vahan-rpa.sh
```

Hai script gọi chung `scripts/run-docker.py`: tạo `.docker.env` nếu chưa có, giới hạn quyền đọc file, kiểm tra Compose, build image và khởi động stack. Windows luôn truyền `--env-file .docker.env`, không cần tạo symlink `.env`. Có thể kiểm tra cấu hình mà không đổi container:

```powershell
./run-vahan-rpa.ps1 --config-only
```

```bash
./run-vahan-rpa.sh --config-only
```

Để chạy bằng image đã build hoặc đã tải từ registry, dùng `--no-build`. Docker Compose v2 và Docker Engine/Desktop phải đang hoạt động.

## Build và phát hành image

Compose build bốn image được đặt tag theo `VAHAN_IMAGE_NAMESPACE` và `VAHAN_IMAGE_TAG` trong `.docker.env`. Mặc định là `vahan-automation/{api,runner,web,worker-control}:local`. Tất cả runner dùng chung một image. Không cần mount mã nguồn hoặc đường dẫn máy host vào container; mã OCR cần thiết đã nằm trong API image.

Để tạo bản có tag phát hành và đẩy tới registry của bạn, đặt namespace đầy đủ, ví dụ `registry.example.com/team/vahan`, và tag, ví dụ `2026.10.08`, trong `.docker.env`; sau đó:

```bash
docker login registry.example.com
docker compose --env-file .docker.env build
docker compose --env-file .docker.env push api runner web worker-control
```

Trên production, đặt cùng namespace/tag, đăng nhập registry rồi chạy:

```bash
docker compose --env-file .docker.env pull
python3 scripts/run-docker.py --no-build
```

Build trên Linux production hoặc CI cùng kiến trúc CPU với máy đích. Linux containers chạy trên Windows/macOS cũng phụ thuộc kiến trúc CPU; image amd64 trên Apple Silicon có thể chạy qua giả lập nhưng chậm hơn image arm64.

## Cấu hình host production

- Giữ `API_BIND_ADDRESS=127.0.0.1`. API chỉ được publish trên loopback của host; Nginx trong Compose vẫn truy cập API nội bộ.
- Đặt `WEB_BIND_ADDRESS=127.0.0.1` nếu một reverse proxy trên host kết thúc HTTPS và chuyển tiếp tới cổng web. Nếu cần truy cập trực tiếp trong mạng riêng, đặt `0.0.0.0` và giới hạn cổng bằng firewall; Compose không tự cấp TLS.
- Dùng tên miền HTTPS, VPN hoặc firewall để giới hạn người truy cập dashboard. Không công khai Docker socket, PostgreSQL hoặc cổng worker.
- Giữ volume `postgres_data`, sao lưu thường xuyên bằng `python3 scripts/backup-docker.py`. Bản backup chứa database và `.docker.env`, do đó chỉ tài khoản vận hành được đọc.
- Giữ `.docker.env`, backup, signing key và browser-state key ngoài Git. Sao lưu các khóa cùng database để có thể khôi phục cookie mã hóa và phiên đăng nhập.
- `worker-control` cần Docker socket để điều chỉnh số runner. Chỉ triển khai trên host chuyên dụng, giữ API/controller trong mạng Compose nội bộ và giới hạn quyền quản trị Docker trên host.

Stack hiện cung cấp một API process và một PostgreSQL primary, không phải dịch vụ HA. Khi cập nhật API/runner trên host đang xử lý job, chờ batch về trạng thái cuối trước khi triển khai image mới. Lệnh `docker compose down -v` xóa database volume; không dùng cho cập nhật thông thường.

## Kiểm thử nền tảng

`.github/workflows/platform.yml` chạy Python, Playwright/Chromium, kiểm tra TypeScript/build và kiểm thử giao diện trên runner Ubuntu, Windows và macOS. Một job Ubuntu riêng kiểm tra Compose và build các Linux images. Các kiểm thử database chạy trong PostgreSQL tạm của CI, tách khỏi database người dùng.

Local `--config-only` kiểm tra được Compose và file cấu hình; nó không thay thế việc chạy workflow trên từng hosted OS. Sau khi workflow được kích hoạt cho branch/PR, tab Actions ghi kết quả Windows, Ubuntu và macOS theo từng run.

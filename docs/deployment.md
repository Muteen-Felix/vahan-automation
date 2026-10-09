# Triển khai và đóng gói đa nền tảng

Ứng dụng được đóng gói thành các Linux container. Cùng một source và Compose file chạy trên Ubuntu, macOS và Windows thông qua Docker; Windows cần Docker Desktop ở chế độ Linux containers. Máy production nên dùng Ubuntu Server, Docker Engine và Compose plugin. Stack local chạy trên một máy Compose; worker Chromium được nhân bản từ một service và không tự phân tán sang nhiều host.

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

Mặc định launcher đánh giá CPU/RAM Docker, RAM trống của host và mức dùng thực tế của runner trước khi chọn số instance; worker đang chạy được giữ lại để không ngắt job. Xem kết quả mà không thay đổi container bằng `py -3 scripts/run-docker.py --assess-only` trên Windows hoặc `python3 scripts/run-docker.py --assess-only` trên Linux/macOS. Có thể ghi đè thủ công bằng `--workers 3`; để chạy image đã build hoặc tải từ registry, kết hợp `--no-build`. Docker Compose v2 và Docker Engine/Desktop phải đang hoạt động.

## Build và phát hành image

Compose build ba image được đặt tag theo `VAHAN_IMAGE_NAMESPACE` và `VAHAN_IMAGE_TAG` trong `.docker.env`. Mặc định là `vahan-automation/{api,runner,web}:local`. Tất cả runner dùng chung một image. Không cần mount mã nguồn hoặc đường dẫn máy host vào container; mã OCR cần thiết đã nằm trong API image.

Để tạo bản có tag phát hành và đẩy tới registry của bạn, đặt namespace đầy đủ, ví dụ `registry.example.com/team/vahan`, và tag, ví dụ `2026.10.08`, trong `.docker.env`; sau đó:

```bash
docker login registry.example.com
docker compose --env-file .docker.env build
docker compose --env-file .docker.env push api runner web
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
- Giữ volume `postgres_data`, sao lưu thường xuyên bằng `python3 scripts/backup-docker.py`. Bản backup chứa database và `.docker.env`, do đó chỉ tài khoản vận hành được đọc. Redis giữ AOF trong volume `redis_data` để bảo toàn stream khi container khởi động lại; script backup hiện tại chưa xuất volume Redis.
- Giữ `.docker.env`, backup, signing key và browser-state key ngoài Git. Sao lưu các khóa cùng database để có thể khôi phục cookie mã hóa và phiên đăng nhập.
- Số browser worker do operator cấu hình; API giữ hạn mức task đồng thời trong PostgreSQL. Không mount Docker socket vào container. Các browser container nhàn rỗi vẫn dùng tài nguyên host.

Stack hiện cung cấp một API process và một PostgreSQL primary, không phải dịch vụ HA. Khi cập nhật API/runner trên host đang xử lý job, chờ batch về trạng thái cuối trước khi triển khai image mới. Lệnh `docker compose down -v` xóa database volume; không dùng cho cập nhật thông thường.

## Kiểm thử nền tảng

`.github/workflows/platform.yml` chạy Python, Playwright/Chromium, kiểm tra TypeScript/build và kiểm thử giao diện trên runner Ubuntu, Windows và macOS. Một job Ubuntu riêng kiểm tra Compose và build các Linux images. Các kiểm thử database chạy trong PostgreSQL tạm của CI, tách khỏi database người dùng.

Local `--config-only` kiểm tra được Compose và file cấu hình; nó không thay thế việc chạy workflow trên từng hosted OS. Sau khi workflow được kích hoạt cho branch/PR, tab Actions ghi kết quả Windows, Ubuntu và macOS theo từng run.

Network recovery uses the existing SQL app_settings table (network-connectivity); no schema migration is needed. The API polls VAHAN connectivity every five seconds and requires two successful checks before automatic continuation. Only schedules carrying networkPaused resume automatically; manual pauses and deletions remain authoritative. Deploy API, web and browser-runner together for transport-error reports and bounded browser cancellation.

## Giới hạn phiên đăng nhập

Phiên UI hết hạn sau 12 giờ kể từ lúc đăng nhập hoặc 60 phút không có thao tác. Backend kiểm tra thời hạn cho HTTP và Socket.IO; polling, heartbeat và lưu user-state nền không kéo dài idle timeout. UI báo hoạt động qua `POST /api/auth/activity`, không cấp token mới hoặc thay đổi mốc 12 giờ. Endpoint `/api/auth/renew` đã được bỏ.

Migration `0012_auth_session_limits` thu hồi các phiên cũ không có thời hạn, vì vậy người dùng cần đăng nhập lại sau triển khai. Logout/hết phiên chỉ kết thúc quyền truy cập UI; scheduler và job đã tiếp nhận vẫn chạy bằng xác thực riêng của runner. Job cần CAPTCHA thủ công có thể phải chờ đăng nhập lại. Khóa tài khoản chủ sở hữu vẫn dừng lịch chạy theo chính sách hiện có.

Với lượt triển khai local này, nên để các báo cáo VAHAN đang chạy hoàn tất trước khi thay runner nếu có thể. Nếu worker dừng giữa task, message pending trong Redis và trạng thái queue trong PostgreSQL sẽ phục hồi sau khi lease hết hạn. Launcher dùng `--remove-orphans` để gỡ controller cũ cùng mount Docker socket. Không dùng `down -v`; giữ nguyên các volume dữ liệu.

# Pins — image và nguồn tải (T21/T21a)

## PostgreSQL (D-33, T21a)

| Trường | Giá trị |
| --- | --- |
| Reference | `docker.io/library/postgres:17.11-bookworm@sha256:3645570cccdfa447589da9f57dd740faa29b30938e861289a5574b6ca6b03826` |
| Loại digest | OCI image index (đa kiến trúc) |
| Platform được hỗ trợ | `linux/amd64` — manifest `sha256:66aafa11cf15800a3c94763f7e11d1e7b2e37e5e84bc4ce027cb6e1e4bfaf4df` |
| Upstream | `docker-library/postgres` revision `2603e26e245e558218728ee14e0a42dcb020dc7f`, base `debian:bookworm-slim` |
| Phiên bản server | PostgreSQL 17.11 (Debian 17.11-1.pgdg12+2) — major 17 |
| Kiểm chứng | 13/10/2026: `docker buildx imagetools inspect`, `docker pull`, `docker image inspect`, `docker run … postgres --version` |
| Nhãn revision F | **Không có** (image upstream); manifest ghi reference + digest + platform |

Cùng một reference ở: `compose.yaml` (service `postgres`), `.github/workflows/platform.yml`
(service `postgres` của job `database-integration`), `scripts/scan_container_images.py`
(đọc từ `compose.yaml` qua `scripts/postgres_pin.py`) và `scripts/build-review-package.py`
(đọc từ `docker compose config --images`). `scripts/test_postgres_pin.py` kiểm các nơi này khớp nhau.

Không còn `docker/postgres.Dockerfile` và không còn khối `build:` của `postgres`.

### Đổi pin
1. `docker buildx imagetools inspect docker.io/library/postgres:<tag>` và chọn digest index.
2. Sửa **cả** `compose.yaml` và `.github/workflows/platform.yml`, rồi bảng trên.
3. Chạy `python -m unittest scripts/test_postgres_pin.py` (từ thư mục `scripts`), `scripts/test_container_scan.py`, quét lại theo T21.
4. Nâng major (17 → 18) cần migration dữ liệu riêng — không thuộc thay đổi pin thông thường.

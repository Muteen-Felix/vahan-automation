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

## Image ứng dụng (api, runner, web) — giới hạn truy vết source ↔ image

Quyết định **tạm thời** (phương án A, Felix duyệt 14/10/2026; đề xuất ghi `DECISIONS.md` chờ Felix chấp thuận riêng).

| Điều cần biết | Trạng thái |
| --- | --- |
| Trường `sha:` trong ledger `docs/release/evidence/R*.md` | SHA của **source revision đang được đánh giá**. Nó không xác định SHA hay digest của image đã chạy. `evidence-check.py` chỉ đọc `row`/`sha`/`snapshot`/`fingerprint` và phân loại theo path (`path-map.json`). |
| D3 đợt 4: source SHA của build | **Not verified** — bằng chứng hiện có không liên kết image D3 với source SHA; image D3 đợt 4 được dựng trước T29 nên không có label revision. Từ T29 3 Dockerfile ứng dụng khai báo `org.opencontainers.image.revision`/`version` lúc build (DEF-27); chỉ build sau T29 mới có nhãn. |
| D3 đợt 4: digest image, và việc D3 chạy cùng image với candidate | **Not verified**. |
| `LABEL` revision / `VCS_REF` (T29: đã làm, chưa có E-CI) | Chỉ **khai báo** revision lúc build. Nó không chứng minh bytes hay digest image giống nhau, và không chứng minh image được build từ SHA đó nếu không có provenance xác thực. |
| `test-*.mjs` trong image runner | `apps/browser-runner/Dockerfile:26` có `COPY apps/browser-runner/ ./`; `.dockerignore` không loại `test-*.mjs`; `path-map.json` xếp `apps/browser-runner/test-*.mjs` là `non_runtime`. Không file chạy-thật nào import `./test-*`, `CMD` là `node runner.mjs`. Sửa một test đổi layer `COPY` nên **image ID/digest đổi (suy từ cơ chế Docker, chưa kiểm bằng build)**, trong khi `evidence-check.py` vẫn báo D3 hợp lệ (`build_inputs` không có khóa digest image ứng dụng). |
| API image | Chỉ copy `app/`, `migrations/`, `alembic.ini` (`apps/api-server/Dockerfile:10-12`), nên thay đổi test không đổi image API. |

**Hệ quả:** trường `sha:` nhận diện source revision được đánh giá khi có dữ liệu; với D3 đợt 4, source SHA của build chưa xác định. Ledger không chứng minh image digest hay việc D3 chạy cùng image candidate. Nếu RG2 yêu cầu exact image digest (hoặc cùng-image giữa D3 và candidate) thì cần plan L2 riêng sau D3 (loại `test-*.mjs` khỏi image và/hoặc bổ sung provenance); không thực hiện ở đây.

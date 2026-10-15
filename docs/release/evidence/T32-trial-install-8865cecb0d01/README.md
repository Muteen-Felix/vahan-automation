# T32 — build thử và cài thử từ gói (trial, E-local)

- Commit: `8865cecb0d017a1ec29a6b29fa9fced5b18de3bc` (nhánh `release/pre-go-live`, working tree sạch). **Đây là trial, không phải artifact cuối** — phải làm lại trên candidate cuối.
- Gói: `scripts/build-review-package.py --ref HEAD --with-images` (3 image tự build + image PostgreSQL chính thức đã pull theo digest).
- Cài thử: `scripts/test-review-package.py` vào Compose project tạm, cổng ngẫu nhiên, volume tạm, `--workers 1`; project đã được dọn (`disposable-project-cleanup` PASS). Không đụng stack `vahan-automation-*` đang chạy.
- Kết quả: **55 check, 0 lỗi** (`results.json`, `run-summary.log`), gồm: image ID khớp manifest, `migrate` + role runtime, readiness ngoài Docker, `/docs` 404, route cũ 404, đăng nhập, DB mặc định rỗng, restart API giữ phiên/state, backup + restore vào project tách biệt, Chromium sandbox + Tesseract thật, runner test, 13 test UI trên bản build, **UI Health preflight trên VAHAN thật PASS** (`live-preflight.json`).

| Image | Nguồn | ID | Platform | Nhãn revision |
| --- | --- | --- | --- | --- |
| `vahan-review/web:8865cecb0d01` | built from the commit | `sha256:e9b82cbfe965…` | linux/amd64 | None |
| `docker.io/library/postgres:17.11-bookworm` (@sha256:3645570c…3826) | upstream, pinned | `sha256:3645570cccdf…` | linux/amd64 | None |
| `vahan-review/api:8865cecb0d01` | built from the commit | `sha256:4da30178ee6a…` | linux/amd64 | None |
| `vahan-review/runner:8865cecb0d01` | built from the commit | `sha256:d3900fba51e6…` | linux/amd64 | None |

## Giới hạn (Not verified)
- Nhãn `org.opencontainers.image.revision` chưa có ở 3 image app (T29, RG3).
- Dữ liệu import/export dùng fixture **SYNTHETIC** (nhãn trong tên file); **không** chạy một case VAHAN đầy đủ (`--live-case` không bật). Preflight là kiểm DOM contract trên trang VAHAN thật, không phải thu thập báo cáo.
- Chạy trên Windows 11 + Docker Desktop (amd64) trên chính máy dev; không phải máy/VM sạch riêng (D-12 = A).
- Chưa dùng INSTALL.md làm kịch bản (script tự động cài); T45 theo INSTALL.md vẫn phải chạy trên artifact cuối.

# T32 / T28b (snapshot) / T52a (INSTALL.md thực chiến) — **NOT RUN** trên `e46e39e627fa`

- ngày: 2026-10-15
- source cần kiểm: `e46e39e627fac5e0e8ad5f36ca22e51e61f3e40a` (BASE_SHA)
- kết quả (lần chạy đầu): **Not verified — không build gói, không cài thử, không tạo config snapshot thật.**
- **ĐÃ THAY THẾ:** cài thử, config snapshot và smoke sau đó đã chạy được; xem `T32-trial-install-e46e39e627fa/README.md`. File này giữ lại làm lịch sử lần dừng vì thiếu RAM.
- lý do: thiếu RAM host theo ngưỡng của chính repo; phương án duy nhất để có RAM là dừng stack `vahan-automation` đang chạy hoặc đóng ứng dụng của người dùng — cả hai bị cấm trong yêu cầu ("thiếu RAM hoặc cần dừng stack đang chạy ⇒ dừng và báo").

## Số đo (Verified, `python scripts/run-docker.py --assess-only`, chỉ đọc)

| Lần | Host RAM available | Ngưỡng cho 1 runner thêm | Thiếu |
| --- | --- | --- | --- |
| 1 | 2,02 GiB | 2,66 GiB | 0,64 GiB |
| 2 | 1,86 GiB | 2,66 GiB | 0,79 GiB |
| 3 | 1,92 GiB | 2,66 GiB | 0,73 GiB |

Docker Engine 12 vCPU / 9,71 GiB; host 15,58 GiB tổng; 3 runner + api + web + postgres đang `healthy` (stack `vahan-automation`, không bị đụng). Đĩa trống 211 GB. Lần T32 trước (`f1e07f8a93a1`) bắt đầu với 3,35 GiB available và ngưỡng 2,66 GiB.

## Hệ quả cho các mục phụ thuộc

| Mục | Trạng thái | Ghi chú |
| --- | --- | --- |
| T32 gói + cài thử cho BASE_SHA | **Not run** | Gói/bằng chứng của `f1e07f8a93a1` và `8865cecb0d01` **không** dùng được cho BASE_SHA: `git diff --name-only f1e07f8a93a1 HEAD` chạm `apps/api-server/app/*`, migration `0016`, `apps/browser-runner/runner.mjs`, `pyproject.toml`, `requirements-dev.lock` |
| T28b config snapshot từ môi trường thử | **Not run** | Cần project thử đã cài. Phần logic allowlist/canary của `scripts/config-snapshot.py` **đã** có test: `scripts/test_evidence_check.py::SnapshotAllowlist` (7 test, đã chạy trong đợt này: 31 test OK) |
| T52a dùng `INSTALL.md` làm kịch bản thật | **Not run** | Chưa có danh sách lệch INSTALL.md ↔ thực tế cho BASE_SHA |
| `config-snapshot` / `build-fingerprint` cho ledger D3 | **chưa ghi** | Không thể dựng hồi tố cho build `fa04898` đã chạy D3 |

## Điều kiện để chạy tiếp (Felix quyết)

1. Giải phóng ≥ 0,8 GiB RAM host (đóng ứng dụng khác) **hoặc** chạy trên máy/VM khác (D-12 phương án A), rồi chạy lại: `python scripts/build-review-package.py --ref e46e39e627fa… --output-dir outputs/trial-e46e39e627fa --with-images` → `python scripts/test-review-package.py --package-dir … --output-dir …` → `python scripts/config-snapshot.py --env-file <env của project thử> --out …`.
2. Hoặc cho phép dừng stack `vahan-automation` (cần quyết định riêng; stack giữ dữ liệu thật).

## Cập nhật sau khi người dùng giải phóng RAM (2026-10-15, lần chạy thứ hai)

- RAM đo lại: **2,70 GiB available** (đạt ngưỡng 2,66 GiB) ⇒ đã **build gói** từ đúng BASE_SHA.
- Lệnh: `python scripts/build-review-package.py --ref e46e39e627fac5e0e8ad5f36ca22e51e61f3e40a --output-dir outputs/trial-e46e39e627fa --with-images` ⇒ exit 0. Gói thô (`images.tar` ~731 MiB, `source.zip`) để ngoài repo (`outputs/`, không commit); manifest: `T32-package-manifest-e46e39e627fa.json`.

| File | sha256 (khớp `manifest.files`) |
| --- | --- |
| `vahan-e46e39e627fa-source.zip` | `854187c87f8c6a92c1b6583b07a790c56c8a6b679236100def25efe6953962db` |
| `vahan-e46e39e627fa-images.tar` | `7257c0dd4cc5566d0e778f5a8596ec676e3fc56d2d9ee05cbd6d65bfc3afc639` |

| Image | Nguồn | ID | Platform | Nhãn revision |
| --- | --- | --- | --- | --- |
| `vahan-review/api:e46e39e627fa` | tự build | `sha256:89586075522aefd153226c6a7de39bf4f2c940a687d32d5594efe521d7b01994` | linux/amd64 | null |
| `vahan-review/runner:e46e39e627fa` | tự build | `sha256:61394f43a862e854af5d023e1893d51c236bbb30144a04d37987f6d3e3dd2c50` | linux/amd64 | null |
| `vahan-review/web:e46e39e627fa` | tự build | `sha256:30125774f739cca751ac4e21c9025cfba150ff7ddb279674d4730b823be94f3c` | linux/amd64 | null |
| `docker.io/library/postgres:17.11-bookworm@sha256:3645570c…3826` | upstream, pin digest | `sha256:3645570cccdfa447589da9f57dd740faa29b30938e861289a5574b6ca6b03826` | linux/amd64 | null |

- Ngay sau khi build RAM host **tụt còn 0,49–0,61 GiB** (bốn lần đo cách 30 s; stack hiện có 4 runner, Docker engine không đổi). Vì vậy **cài thử, config snapshot và release-smoke vẫn Not run**; không dừng/đụng stack đang chạy, không dọn build cache hay image của người dùng.
- Kết quả: **gói BASE_SHA = built (E-local); cài thử/T28b/T52a = Not verified.** Gói chưa được cài, chưa được kiểm ID sau `docker load` (ID ở bảng là ID image vừa build trên máy này).
- Tài nguyên còn lại do lần này tạo: 3 tag `vahan-review/{api,runner,web}:e46e39e627fa` (Docker local) và `outputs/trial-e46e39e627fa/`; bản nháp trình điều khiển cài thử (làm theo INSTALL.md §2–§5, chụp snapshot, `release-smoke`, `down --volumes` chỉ project tạm) đang để ở scratchpad phiên làm việc, chưa chạy.

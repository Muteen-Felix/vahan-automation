# T32 / T28b (snapshot) / T52a (INSTALL.md thực chiến) — **NOT RUN** trên `e46e39e627fa`

- ngày: 2026-10-15
- source cần kiểm: `e46e39e627fac5e0e8ad5f36ca22e51e61f3e40a` (BASE_SHA)
- kết quả: **Not verified — không build gói, không cài thử, không tạo config snapshot thật.** Không có Pass nào được ghi cho BASE_SHA ở mục này.
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

# T32 — build thử và cài thử từ gói trên candidate `f1e07f8a93a1` (trial, E-local)

- Commit nguồn của gói: `f1e07f8a93a1fcc22d68ad2c81430dbb4ec11168` (nhánh `release/pre-go-live`). **Đây là trial, không phải artifact cuối.**
- Gói: `scripts/build-review-package.py --ref f1e07f8a93a1 --output-dir outputs/trial-f1e07f8a93a1 --with-images` (3 image tự build + image PostgreSQL chính thức pin digest). Gói thô (`images.tar` ~736 MB, `source.zip`) **không** nằm trong repo; chỉ giữ manifest + sha256.
- Cài thử: `scripts/test-review-package.py` vào Compose project tạm, cổng ngẫu nhiên, volume tạm, `--workers 1`. Cả 3 project đã được dọn (`disposable-project-cleanup` PASS, 0 container/volume còn lại); stack `vahan-automation` đang chạy không bị đụng.
- **T32 (gói) và D3 (preflight VAHAN thật) là hai kết quả riêng.** CI xanh và T32 **không thay thế** D3.

## Gói

| File | sha256 (khớp `manifest.files`) |
| --- | --- |
| `vahan-f1e07f8a93a1-source.zip` | `d626def6da87a8811a129633dc6e71a332cefc48b22627c87d71f9708edf100e` |
| `vahan-f1e07f8a93a1-images.tar` | `6f9d081702cf6a815ab21c10662fabc8e504da577c598c2e408e6e46d88887e0` |

| Image | Nguồn | ID | Platform | Nhãn revision |
| --- | --- | --- | --- | --- |
| `vahan-review/api:f1e07f8a93a1` | tự build | `sha256:6e35808a7fb09f49cbdadf908b57fc81f6effb0239e5a4ec13aa5593b982d5c4` | linux/amd64 | None |
| `vahan-review/runner:f1e07f8a93a1` | tự build | `sha256:794cb55c689167df48c94aa3ef90e5ad25874be1270ea3e7415283d6691e4864` | linux/amd64 | None |
| `vahan-review/web:f1e07f8a93a1` | tự build | `sha256:1c4a6c2fa0a03c9d4971987745e9a86c90642b5f693e0c079669f32149546030` | linux/amd64 | None |
| `docker.io/library/postgres:17.11-bookworm@sha256:3645570c…3826` | upstream, pin digest | `sha256:3645570cccdfa447589da9f57dd740faa29b30938e861289a5574b6ca6b03826` | linux/amd64 | None |

## Ba lần chạy (ngày 2026-10-14, giờ UTC)

| # | Thời gian | Project | Script | Kiểm gói | D3 preflight | Exit | File |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 02:40:54 → 02:46:05 | `vahan-review-d19f50c67a94` | `test-review-package.py` tại `f1e07f8` (preflight chạy vô điều kiện) | 54 pass / 1 fail của 55 | **FAIL** — `UI_HEALTH_BLOCKED`/`UI_DRIFT`, 26/26 control thiếu, `revision 0`, `attempts 2`, `checkedAt 02:45:31Z` | 1 | `first-run-results.json`, `first-run-live-preflight-fail.json` |
| 2 | 03:00:32 → 03:05:22 | `vahan-review-4d624a416fd0` | bản đã tách D3 (không cờ) | **54/54 pass** | **NOT_RUN** | 0 | `results-offline.json` |
| 3 | 03:05:52 → 03:11:10 | `vahan-review-f3be010513f9` | bản đã tách D3, `--vahan-preflight` | **54/54 pass** | **PASS** — HTTP 200, `errorCount 0`, `attempts 1`, `revision 1`, `checkedAt 03:10:37Z` | 0 | `results-d3-preflight.json`, `d3-live-preflight-pass.json` |

- Lần 2 và 3 dùng `scripts/test-review-package.py` sha256 `b50da63cf0ce0339903c87d3555aa49faf75fcce7723f262f2db97df4fd2943e` (`driverScriptSha256` trong `results.json`); nội dung đó được commit ở `b04fb08`.
- Lần 2: `outcome = PACKAGE_PASS_D3_NOT_RUN`, `d3Status = NOT_RUN`, không có entry `live-*` trong `checks`. NOT_RUN không phải Pass.
- Kiểm gói gồm: nạp image (ID khớp manifest), launcher `--no-build`, readiness, `/docs` 404, route cũ 404, đăng nhập, DB mặc định rỗng, CRUD profile và lịch Monthly (hai múi giờ), quyền member, restart API giữ phiên/state, import 1.000 dòng synthetic + 4 export Excel đủ 1.000 dòng, backup + restore vào project tách biệt, Chromium sandbox + Tesseract thật, 13 test runner, 13 test UI trên bản build, kiểm fail-closed khi runner ngắt kết nối (dữ liệu **synthetic**, nhãn trong tên).

## Điều kết luận được và không được

- [Fact] Source runtime của `8865cec` (T32 trước, preflight PASS ngày 2026-10-13 15:40Z) và `f1e07f8` giống hệt nhau: `git diff 8865cec f1e07f8` chỉ chạm 7 file docs/evidence.
- [Fact] Trên cùng source, preflight VAHAN thật có **2 lần PASS và 1 lần FAIL không giải thích được** (lần 1). Lần fail có `observedControls` count 0 cho cả 26 control (gồm `#apply`) và `optionsHash` rỗng, nghĩa là trang đã commit đúng URL nhưng không có control nào trong cửa sổ chờ. Không có title, status cuối hay screenshot của trang.
- [Assumption] Nguyên nhân là môi trường/thời điểm (trang chưa render trong 10 giây, hoặc interstitial tạm thời), chưa được chứng minh.
- **R6 giữ chưa Verified.** Bằng chứng fail-closed là check synthetic (PASS); preflight thật chưa ổn định đủ để kết luận. Cần lặp thêm lần độc lập hoặc làm phần B (runner ghi chẩn đoán) trước khi chốt D3 R6.
- Lần chạy 3 chỉ chứng minh runner thấy đủ control tại 03:10Z; **không** chứng minh thu thập báo cáo, CAPTCHA hay một case hoàn chỉnh (`--live-case` không bật, `liveSingleCase = NOT_RUN`).

## Giới hạn (Not verified)

- Chạy trên máy dev (Windows 11 + Docker Desktop/WSL2, amd64), **song song** với stack `vahan-automation` đang chạy (4 runner); không phải máy/VM sạch riêng (D-12 phương án B). RAM host available khi bắt đầu: 3,35 GiB (lần 1), 3,71 GiB (lần 2) so với ngưỡng 2,66 GiB.
- Script cài tự động, **chưa** dùng `INSTALL.md` làm kịch bản; T45 theo INSTALL.md vẫn phải chạy trên artifact cuối.
- Chưa có `config-snapshot-*.json` cho lần chạy này (C5.4 chưa đạt cho T32).
- Nhãn `org.opencontainers.image.revision` chưa có ở 3 image app (T29, RG3).
- Chưa kiểm: nền tảng khác, nâng cấp tại chỗ (INSTALL §7), `--workers > 1`, mạng đích có thay TLS hay không.
- CI: run `38500323319` (push `release/pre-go-live`, head `f1e07f8a93a1`) đạt 5/5 check. Commit `b04fb08`/`2e20553` (script/test/docs, non-runtime) chưa có kết quả CI tại thời điểm ghi.
- `results.json` giữ nguyên văn như script ghi, gồm đường dẫn host trong trường `command` (cùng kiểu với evidence `8865cecb0d01`); không có secret (log đã che; đã quét `password|accessToken|Bearer` = 0).

## Dọn tài nguyên do lần chạy này tạo

- Project tạm `vahan-review-<hex>` (+ `-restore`): script đã dọn (`down --volumes`).
- Còn lại, chờ quyết định: image `vahan-review/{api,runner,web}:f1e07f8a93a1` và `outputs/trial-f1e07f8a93a1{,-install,-offline,-d3}/` (không commit). Xoá đúng 3 tag: `docker image rm vahan-review/api:f1e07f8a93a1 vahan-review/runner:f1e07f8a93a1 vahan-review/web:f1e07f8a93a1`.

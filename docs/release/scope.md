# Phạm vi bàn giao 1.0

Nguồn quyết định: `PLAN.md` revision r26, §3 và §11 (12/10/2026; bản đầu 11/10/2026). Baseline lịch sử đối chiếu code: HEAD `b210529` (12/10/2026). **Ở hai cột "Việc còn phải kiểm chứng" và "Code ở HEAD", chỉ các ô nêu `6f686ea` hoặc `grep 14/10` được đọc lại ở `6f686ea` (14/10/2026, WP-A1); ô còn lại giữ nội dung đọc ở `b210529`, chưa có bằng chứng đã đối chiếu lại.** Tài liệu này ghi **phạm vi đã chọn**, không xác nhận code hoặc test đã hoàn tất; phạm vi chỉ đổi theo quyết định đã ghi ở PLAN (D-35 bỏ Daily, D-18 không quota OCR). CI xanh trên `fa04898`/`6f686ea` (E-CI14) và `a406ce9` (E-CI15, run `38585468041`; cả hai ở `defects.md`) không phải D3. Gate RG0 cần thêm `defects.md`, `known-issues.md` và bằng chứng T02 (PLAN §11.1).

| ID | Phạm vi 1.0 | Trạng thái | Việc còn phải kiểm chứng / hoàn thiện |
| --- | --- | --- | --- |
| R1 | API, PostgreSQL, migration, health/ready | In | T30/T44: health, restart giữ dữ liệu; service `migrate` thoát 0 và api chạy bằng role runtime hạn chế (S12). HEAD: `/api/ready` kiểm revision migration (`health.py:23-33`) |
| R2 | Login, đổi mật khẩu, logout, vai trò admin/member, thời hạn phiên | In | T11, S3, T30 |
| R3 | Filter profile, tải options, preview số case | In | T30 trên VAHAN thật |
| R4 | Lịch sử phiên, chi tiết, tải file từng case, xóa/khôi phục | In | T30 |
| R5 | Bảng năm, phân trang 100 dòng/trang; Excel **export đủ mọi bản ghi khớp bộ lọc State/RTO**, không bị giới hạn bởi 100 dòng đang hiển thị, **có bước xác nhận**; không lọc thì **Export all** (cũng có xác nhận) | In (D-04 = A; Felix chốt 12/10: export có lọc phải xác nhận) | HEAD `6f686ea`: nút `Export filtered to Excel` hiện, request mang `state`/`rto`, **có hộp xác nhận cả khi lọc** (`AnnualReports.tsx:72-79`; UI test `test-annual-reports.mjs:12-15`); pytest đã có 1.000 dòng và lọc > 100 dòng (`test_annual_reports.py`, xem DEF-09); còn T30 mở workbook và xác nhận trên UI thật |
| R6 | UI Health preflight, fail closed | In | T30 |
| R7 | Lịch Once/Monthly (Daily đã bỏ, lịch Daily đã lưu bị xóa theo D-35, Felix 13/10) | In | T30; migration `0015_remove_daily_schedules` kiểm ở T45b |
| R7b | Chọn múi giờ Việt Nam/Ấn Độ cho lịch | In | T15b bổ sung test API/UI; T30 |
| R8 | ETA trên lịch | In | T15 thực hiện và đo theo D-28. HEAD `6f686ea`: đã render ETA (`RunScheduleProgress.tsx:8,33-35`); đo synthetic đạt D-28 (`evidence/R8-eta.md`, Reopened ở `fa04898`); D3 VAHAN thật chưa chạy |
| R9 | Pause/resume không mất hoặc trùng case | In | T10, T16b, T30; bỏ ô nhập số worker trên web theo T16c. HEAD `6f686ea`: không còn ô nhập số worker ở `AutomaticRunSettings.tsx` (grep 14/10) |
| R9b | Runner tự claim; **mặc định giới hạn song song 20 (giữ — D-34)**; launcher `auto` chọn số runner theo CPU/RAM (tối đa 20); lịch dùng số runner thực tế, không áp số lớn đã lưu | In | T16b/T16c: giới hạn hiệu dụng của lịch = số runner thực tế sẵn sàng khi chạy/tiếp tục; giá trị lớn đã lưu (lịch cũ, local storage, API) không được áp lại; `--workers N` thủ công vẫn tồn tại, không có trần cứng; `scripts/test_worker_capacity.py` vào CI (T11). **BF-06** (lịch kẹt `PREFLIGHT_WAITING` khi runner rảnh > giới hạn; Major/P0): code preflight đã đổi (`ui_health.py:195,236`), chưa có test 3 runner idle qua `scheduler_tick`. **BF-07** (thông báo 409 sai nguyên nhân, `jobs.py:114`; Minor/P1) nếu kịp |
| R10 | Tắt lịch, dừng, xóa nhưng giữ dữ liệu đã thu | In | T30 |
| R11 | Retry, checkpoint, diagnostics; `NO_DATA` không retry | In | T30 |
| R12 | Pause khi mất kết nối VAHAN, tự tiếp tục sau khi mạng ổn | In | T11, T30 |
| R13 | Maker Update | Excluded | T17 gỡ `/api/maker-updates*` và từ chối `updateKind`/`updateRunId`/`updateTaskId` ở `POST /api/jobs`. HEAD `6f686ea`: **đã gỡ** (router không còn maker-update; `main.py:93-95` trả 404; `models/job.py:85-92` từ chối `updateKind`≠NORMAL); còn D3 |
| R14 | CAPTCHA auto-solve, không có đường nhập tay | In | T19f bỏ raw OCR log; **không có quota OCR theo số lượt/10 phút** (D-18, Felix cập nhật 13/10); T33/T30. HEAD `6f686ea`: log OCR thô đã hết khỏi `runner.mjs` (grep 14/10); test: `apps/browser-runner/test-ocr-start.mjs:9-10` (assertion tĩnh trên source: không còn `OCR raw output:`/`Auto-OCR result:`) và `:35-43` (vòng 25 lượt trên fixture: 25 `start`, 25 `ocr`, 25 `submit`; không gọi tesseract thật) và `apps/api-server/tests/test_ocr_unlimited.py`; chạy trong CI (E-CI15, step `Test browser runner` và `Run database-backed verification…` success, mức step) |
| R15 | Gỡ **hết** API legacy: `upload-excel`, `GET`/`PUT /api/ui-health/schedule`, `POST /api/ui-health/run-now` | In (D-07 = A — gỡ nốt; Felix chốt 12/10) | HEAD đã gỡ `upload-excel`, `PUT schedule`, `HealthCheckSchedule.tsx`. **HEAD `6f686ea`: đã gỡ nốt** — `ui_health.py` không còn hai route; `main.py:93` trả 404; test 404 ở `tests/test_api.py:47-48,58`. Caller trong repo: không có (PLAN §11.1); client ngoài repo không xác minh được bằng code |
| R16 | Đối chiếu kết quả tự động với người kiểm tra độc lập | In | T31/T46 trước RG4; người kiểm tra chưa thực hiện |
| **R17** | **Trang Run History** (admin): mỗi lần chạy lọc một dòng, mới nhất trước, giờ Việt Nam; tên bộ lọc giữ nguyên sau khi xóa/đổi tên lịch; số case đếm một lần (retry không thêm dòng); `GET /api/annual-reports/run-history` chỉ admin | **In** (D-31, Felix chốt 12/10) | T15c, T11: đăng ký `verification/test_run_history.py` (DB `vahan_history_platform_test`) vào CI; **chế độ dữ liệu mẫu đã bỏ ở HEAD `6f686ea`** (`RunHistory.tsx` không còn; `test-permissions-ui.mjs:75` khẳng định không có ô "Show sample data"); member không thấy trang và API trả 403; D3 (T30). HEAD: `update_status.py:18-20`, `RunHistory.tsx`, `repositories/run_history.py` |

## Chức năng không bàn giao

| Mục | Trạng thái | Ranh giới |
| --- | --- | --- |
| Import dữ liệu cũ | Excluded | `app/import_legacy.py` và `scripts/export-legacy-history.py` còn trong source nhưng không có quy trình bàn giao (D-25) |

## An ninh và vận hành

Cột "Code ở HEAD" ghi những gì đã đọc được trong source: baseline lịch sử ở HEAD `b210529` (12/10); ô nêu `6f686ea`, `grep 14/10` hoặc E-CI15 đã được đọc lại ở revision đó. Đó **không** phải bằng chứng D3; test được nêu trong ô, nếu có, mới có bằng chứng CI mức step (E-CI15).

| Mục | Trạng thái | Cam kết 1.0 | Code ở HEAD (baseline `b210529`, 12/10; ô nêu `6f686ea`/14/10 đã đọc lại) |
| --- | --- | --- | --- |
| S1 | In | Bỏ raw OCR log theo R14 (D-18; không quota) | Đã bỏ khỏi `runner.mjs` (grep 14/10); `test-ocr-start.mjs:9-10` (assertion tĩnh trên source; CI E-CI15 mức step) |
| S3 | In | Nginx rate limit cho login; bộ đếm DB theo tài khoản/IP Deferred (KI-22, Major) | `docker/nginx.conf:1,10-13` (`limit_req` 10 req/phút, burst 10); chưa có test |
| S5 | In | Origin allowlist cho Socket.IO | `config.py:119`, `config.py:83-100` (từ chối `*` khi production); `test_production_config.py` |
| S6 | In | Headers/CSP, kiểm web qua nginx | `docker/security-headers.conf:1-4`; CSP có `script-src 'self'`; chưa `server_tokens off`; chưa có web test qua nginx |
| S7 | In | Cờ tắt `/docs`, `/redoc`, `/openapi.json` | `main.py:53-55` (tắt khi `VAHAN_ENVIRONMENT=production`; compose đặt production, `compose.yaml:50`); `README.md:98` còn link `/docs` |
| S8 | Deferred | Kiểm nhất quán runner–job–kết nối và credential riêng từng runner chưa làm; KI-14 còn mở | Không đổi |
| S9 | In | Python lock có hash, pin base image, scan/SBOM (D-01); **PostgreSQL = image chính thức pin digest, bỏ image tự build ở RG1 (T21a, D-33)** | API: `requirements.lock` có hash, `--require-hashes` (`apps/api-server/Dockerfile:7-8`), base image pin digest; PostgreSQL = image chính thức pin digest (`compose.yaml`), `docker/postgres.Dockerfile` đã xóa; còn `apt-get upgrade` không pin, chưa script so lock↔image |
| S10 | Deferred | Giới hạn RAM/CPU/pids và container hardening chờ tài nguyên công ty; KI-21 (Major) | Không đổi (`compose.yaml:71`); thêm log giới hạn 10 MB × 5 |
| **S12** | **In** | Tách quyền DB: service `migrate` (owner `vahan`) chạy migration rồi cấp DML cho role runtime `DB_APP_USERNAME`; API production từ chối chạy bằng role có quyền DDL/superuser. **Phải kiểm cài mới (T45) và nâng cấp từ bản cũ (T45b)** — D-32, Felix chốt 12/10 | `compose.yaml:25-37`, `app/provision_database.py`, `main.py:23-31`, `config.py:83-100`, `scripts/{setup-docker,deployment_guard}.py`; `provision_database`: (a)(b) `scripts/test_runtime_role_lifecycle.py`, (c)–(f) `scripts/test_provision_database.py` (WP-B `1f6da24`; step `Run database-backed verification in isolated processes` xanh ở E-CI15, run `38585468041` trên `a406ce9`, mức step — chưa đọc log từng test) |
| O1 | In | Probe `/api/ready` từ ngoài Docker và runbook xử lý | `/api/ready` kiểm revision migration; probe ngoài + runbook chưa có |
| O1 alerting mở rộng | Deferred | Chưa có email/SMS tự động; KI-06 | Không đổi |

## Tài liệu

**Cập nhật 14/10:** commit `95aa029` (12/10) từng xóa 10 tệp tài liệu, nhưng ở `6f686ea` 11 tệp `docs/*.md` mà `README.md` dẫn tới đã được khôi phục bằng merge và đều tồn tại; `scripts/check-doc-links.py` xanh ở CI. Hồ sơ bàn giao nằm ở `docs/release/` (`INSTALL.md`, `SMOKE.md`, `ops/runbook.md`, `security/*`, `qa/*`, `config/*`). Chưa đối chiếu nội dung `docs/*.md` với phạm vi (T24a).

Các mục **In** là yêu cầu cần triển khai và kiểm chứng, không phải trạng thái “đã xong”. Mọi mục Deferred cần có known issue, severity và owner trong `known-issues.md`; accepted risk chỉ do Felix quyết ở RG5 (D-20).

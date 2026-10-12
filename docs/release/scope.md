# Phạm vi bàn giao 1.0

Nguồn quyết định: `PLAN.md` revision r26, §3 và §11 (12/10/2026; bản đầu 11/10/2026). Đối chiếu code: HEAD `b210529` (12/10/2026). Tài liệu này ghi **phạm vi đã chọn**, không xác nhận code hoặc test đã hoàn tất; chưa test/build nào được chạy ở HEAD. Gate RG0 cần thêm `defects.md`, `known-issues.md` và bằng chứng T02 (PLAN §11.1).

| ID | Phạm vi 1.0 | Trạng thái | Việc còn phải kiểm chứng / hoàn thiện |
| --- | --- | --- | --- |
| R1 | API, PostgreSQL, migration, health/ready | In | T30/T44: health, restart giữ dữ liệu; service `migrate` thoát 0 và api chạy bằng role runtime hạn chế (S12). HEAD: `/api/ready` kiểm revision migration (`health.py:23-33`) |
| R2 | Login, đổi mật khẩu, logout, vai trò admin/member, thời hạn phiên | In | T11, S3, T30 |
| R3 | Filter profile, tải options, preview số case | In | T30 trên VAHAN thật |
| R4 | Lịch sử phiên, chi tiết, tải file từng case, xóa/khôi phục | In | T30 |
| R5 | Bảng năm, phân trang 100 dòng/trang; Excel **export đủ mọi bản ghi khớp bộ lọc State/RTO**, không bị giới hạn bởi 100 dòng đang hiển thị, **có bước xác nhận**; không lọc thì **Export all** (cũng có xác nhận) | In (D-04 = A; Felix chốt 12/10: export có lọc phải xác nhận) | HEAD: nút `Export filtered to Excel` đã hiện và request mang `state`/`rto` (`AnnualReports.tsx:77-79,106-110`); **thiếu bước xác nhận khi lọc** (`:76` chỉ xác nhận khi không lọc) — T16; còn thiếu test pytest 1.000 dòng và export có lọc khớp > 100 dòng; T30 mở workbook |
| R6 | UI Health preflight, fail closed | In | T30 |
| R7 | Lịch Once/Daily/Monthly | In | T30 |
| R7b | Chọn múi giờ Việt Nam/Ấn Độ cho lịch | In | T15b bổ sung test API/UI; T30 |
| R8 | ETA trên lịch | In | T15 thực hiện và đo theo D-28. HEAD: chưa render (`RunScheduleProgress.tsx:19` chỉ hiện reports/min) |
| R9 | Pause/resume không mất hoặc trùng case | In | T10, T16b, T30; bỏ ô nhập số worker trên web theo T16c. HEAD: ô khi tạo lịch đã bỏ, ô theo từng lịch còn (`AutomaticRunSettings.tsx:198-201`) |
| R9b | Runner tự claim; **mặc định giới hạn song song 20 (giữ — D-34)**; launcher `auto` chọn số runner theo CPU/RAM (tối đa 20); lịch dùng số runner thực tế, không áp số lớn đã lưu | In | T16b/T16c: giới hạn hiệu dụng của lịch = số runner thực tế sẵn sàng khi chạy/tiếp tục; giá trị lớn đã lưu (lịch cũ, local storage, API) không được áp lại; `--workers N` thủ công vẫn tồn tại, không có trần cứng; `scripts/test_worker_capacity.py` vào CI (T11). **BF-06** (lịch kẹt `PREFLIGHT_WAITING` khi runner rảnh > giới hạn; Major/P0): code preflight đã đổi (`ui_health.py:195,236`), chưa có test 3 runner idle qua `scheduler_tick`. **BF-07** (thông báo 409 sai nguyên nhân, `jobs.py:118`; Minor/P1) nếu kịp |
| R10 | Tắt lịch, dừng, xóa nhưng giữ dữ liệu đã thu | In | T30 |
| R11 | Retry, checkpoint, diagnostics; `NO_DATA` không retry | In | T30 |
| R12 | Pause khi mất kết nối VAHAN, tự tiếp tục sau khi mạng ổn | In | T11, T30 |
| R13 | Maker Update | Excluded | T17 gỡ `/api/maker-updates*` và từ chối `updateKind`/`updateRunId`/`updateTaskId` ở `POST /api/jobs`. HEAD: **chưa gỡ** (`api/__init__.py:13,30`; `jobs.py:105-106`) |
| R14 | CAPTCHA auto-solve, không có đường nhập tay | In | T19f bỏ raw OCR log, giới hạn **20 lần bắt đầu OCR/10 phút chung toàn hệ thống**; hết lượt thì job `FAILED`, web hiện lỗi; T33/T30. HEAD: log OCR còn (`runner.mjs:163-164`), chưa có giới hạn |
| R15 | Gỡ **hết** API legacy: `upload-excel`, `GET`/`PUT /api/ui-health/schedule`, `POST /api/ui-health/run-now` | In (D-07 = A — gỡ nốt; Felix chốt 12/10) | HEAD đã gỡ `upload-excel`, `PUT schedule`, `HealthCheckSchedule.tsx`. **Còn phải gỡ (T18):** `GET /api/ui-health/schedule` (`ui_health.py:43-49`) và `POST /api/ui-health/run-now` (`ui_health.py:66-100`), cùng test giữ chúng (`tests/test_api.py:51,54`). Caller trong repo: không có (PLAN §11.1); client ngoài repo không xác minh được bằng code |
| R16 | Đối chiếu kết quả tự động với người kiểm tra độc lập | In | T31/T46 trước RG4; người kiểm tra chưa thực hiện |
| **R17** | **Trang Run History** (admin): mỗi lần chạy lọc một dòng, mới nhất trước, giờ Việt Nam; tên bộ lọc giữ nguyên sau khi xóa/đổi tên lịch; số case đếm một lần (retry không thêm dòng); `GET /api/annual-reports/run-history` chỉ admin | **In** (D-31, Felix chốt 12/10) | T15c, T11: đăng ký `verification/test_run_history.py` (DB `vahan_history_platform_test`) vào CI; chế độ dữ liệu mẫu (`Show sample data`, `?mockRunHistory=1`) mặc định tắt, có nhãn "not actual collection results", không gọi API; member không thấy trang và API trả 403; D3 (T30). HEAD: `update_status.py:18-20`, `RunHistory.tsx`, `repositories/run_history.py` |

## Chức năng không bàn giao

| Mục | Trạng thái | Ranh giới |
| --- | --- | --- |
| Import dữ liệu cũ | Excluded | `app/import_legacy.py` và `scripts/export-legacy-history.py` còn trong source nhưng không có quy trình bàn giao (D-25) |

## An ninh và vận hành

Cột "Code ở HEAD" ghi những gì đã đọc được trong source ngày 12/10; đó **không** phải bằng chứng đã kiểm chứng (chưa có test/D3).

| Mục | Trạng thái | Cam kết 1.0 | Code ở HEAD `b210529` |
| --- | --- | --- | --- |
| S1 | In | Bỏ raw OCR log và giới hạn CAPTCHA theo R14 (D-18) | Chưa làm: `runner.mjs:163-164` |
| S3 | In | Nginx rate limit cho login; bộ đếm DB theo tài khoản/IP Deferred (KI-22, Major) | `docker/nginx.conf:1,10-13` (`limit_req` 10 req/phút, burst 10); chưa có test |
| S5 | In | Origin allowlist cho Socket.IO | `config.py:119`, `config.py:83-100` (từ chối `*` khi production); `test_production_config.py` |
| S6 | In | Headers/CSP, kiểm web qua nginx | `docker/security-headers.conf:1-4`; CSP tối thiểu, không `script-src`; chưa `server_tokens off`; chưa có web test qua nginx |
| S7 | In | Cờ tắt `/docs`, `/redoc`, `/openapi.json` | `main.py:53-55` (tắt khi `VAHAN_ENVIRONMENT=production`; compose đặt production, `compose.yaml:50`); `README.md:98` còn link `/docs` |
| S8 | Deferred | Kiểm nhất quán runner–job–kết nối và credential riêng từng runner chưa làm; KI-14 còn mở | Không đổi |
| S9 | In | Python lock có hash, pin base image, scan/SBOM (D-01); **PostgreSQL = image chính thức pin digest, bỏ image tự build ở RG1 (T21a, D-33)** | Chưa lock/digest; PostgreSQL đang build từ `docker/postgres.Dockerfile` (`compose.yaml:11-13`, tag `17.11-bookworm`) — sẽ bỏ ở T21a |
| S10 | Deferred | Giới hạn RAM/CPU/pids và container hardening chờ tài nguyên công ty; KI-21 (Major) | Không đổi (`compose.yaml:71`); thêm log giới hạn 10 MB × 5 |
| **S12** | **In** | Tách quyền DB: service `migrate` (owner `vahan`) chạy migration rồi cấp DML cho role runtime `DB_APP_USERNAME`; API production từ chối chạy bằng role có quyền DDL/superuser. **Phải kiểm cài mới (T45) và nâng cấp từ bản cũ (T45b)** — D-32, Felix chốt 12/10 | `compose.yaml:25-37`, `app/provision_database.py`, `main.py:23-31`, `config.py:83-100`, `scripts/{setup-docker,deployment_guard}.py`; **`provision_database` chưa có test** (T19i) |
| O1 | In | Probe `/api/ready` từ ngoài Docker và runbook xử lý | `/api/ready` kiểm revision migration; probe ngoài + runbook chưa có |
| O1 alerting mở rộng | Deferred | Chưa có email/SMS tự động; KI-06 | Không đổi |

## Tài liệu

`docs/` chỉ còn `docs/release/`: commit `95aa029` (12/10) đã xóa 10 tệp (`api-reference.md`, `deployment.md`, `system-status.md`, `run-schedules.md`, `ui-health-sql.md`, `batch-error-recovery.md`, `context/…`, `plans/…`, `.DS_Store`). `README.md:30,154,177,181-186` và `apps/api-server/README.md:5,9` vẫn dẫn tới các tệp không còn tồn tại; nơi ghi hướng dẫn cài/nâng cấp/vận hành/API thay thế do T24a/T52a đề xuất (PLAN §5.3), chưa tạo.

Các mục **In** là yêu cầu cần triển khai và kiểm chứng, không phải trạng thái “đã xong”. Mọi mục Deferred cần có known issue, severity và owner trong `known-issues.md`; accepted risk chỉ do Felix quyết ở RG5 (D-20).

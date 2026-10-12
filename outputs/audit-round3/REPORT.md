# Đợt 3 — Kết quả hoàn thiện chức năng

## Kết quả chạy

- Verification suite: **65/65 mục PASS**, 0 FAIL. Có 227 pytest case có báo cáo JUnit; 0 skipped.
- API core trên database thử nghiệm sạch: **90 PASS, 0 FAIL, 0 skipped**. Có một cảnh báo deprecation của Alembic về `path_separator`, không ảnh hưởng kết quả.
- Web UI Playwright: **13/13 script PASS**; production build `npm.cmd run build` PASS.
- Browser runner và các script/tool verification: mọi file PASS; xem bảng theo file bên dưới.

## Run 100 case và sai số ETA

- Kết quả: **100/100 case duy nhất hoàn tất**, peak concurrency 3; 101 lần giao job do một job được retry sau recovery.
- Thời gian thực: **45 phút 21 giây** (2026-10-12T09:07:47.695078+00:00 đến 2026-10-12T09:53:09.026559+00:00). Mốc 30 phút đầu tiên được lấy tại 1804.5 giây, khi queue có 59 case hoàn tất. 30-minute checkpoint error: 42.6s absolute; ETA was 42.6s early.
- ETA có 411 mẫu; toàn run: median absolute error 361.6s, mean 363.1s, p90 614.3s, max 4380.7s.
- Từ khi đã hoàn tất ít nhất 20 case (335 mẫu): median 320.0s, mean 307.6s, p90 573.1s, max 815.6s.
- Bài đo ghi nhận một lần restart tiến trình đo sau 49 case; cùng queue/session được tiếp tục. Vì vậy thời gian và sai số bao gồm recovery. Đây là worker protocol test dùng HTTP, Socket.IO, PostgreSQL và kết quả NO_RECORD tổng hợp theo đồng hồ thật; không phải benchmark Chrome/OCR trực tiếp trên VAHAN.

## Phạm vi đã xác minh

- Timezone Việt Nam `Asia/Ho_Chi_Minh` (UTC+07:00) và Ấn Độ `Asia/Kolkata` (UTC+05:30), gồm rollover ngày UTC, giờ local và lịch tháng qua tháng 2.
- Run History chỉ admin; retry giữ nguyên một run và một case trong history; sample data tắt mặc định và hiện nhãn “Sample data — demonstration only.” khi bật.
- Excel export hỏi xác nhận trước request tải; xuất hết hàng khớp State/RTO qua nhiều trang và xuất đủ 1.000 hàng khi không lọc.
- Maker Update runtime đã gỡ; hai API UI Health cũ và route Maker Update trả 404. Kiểm OpenAPI, anonymous/member/admin/runner và không phát sự kiện runner cũ.
- Migration kiểm database có dữ liệu qua 0012 → 0013 → 0014 và downgrade/upgrade vòng lại; xác minh dữ liệu task, attempts, jobs, auth và outbox.

## Phân loại các lỗi test trong quá trình xác minh

- Assertion mobile cũ trong `test-run-schedules-ui.mjs` giới hạn card dưới 360px, không còn phù hợp sau khi thêm ba dòng ETA. Hàng progress mobile cao 98px khiến giới hạn đó không thể đạt cùng metadata và actions. Đổi ngưỡng thành dưới 410px để phản ánh layout mới; test UI đầy đủ sau đó PASS. Đây là test lỗi thời, không phải lỗi hiển thị sản phẩm.
- Test Socket.IO cũ từng mong `POST /api/ui-health/run-now` trả 202 và gửi sự kiện. Hành vi đó bị yêu cầu gỡ; test được thay bằng kiểm 404 và không gửi sự kiện, hiện PASS. Đây là kỳ vọng test lỗi thời.
- Một lần chạy core ban đầu có một assertion retry/history không tái hiện: test retry chạy độc lập PASS và full core suite trên DB mới PASS 90/90. Giữ log lần đầu trong audit để phân biệt; chưa có lỗi sản phẩm tái hiện.

## Verification theo file

### Core API (`apps/api-server/tests`)

| File/module | Kết quả |
|---|---:|
| `apps/api-server/tests/test_api.py` | 25 PASS, 0 FAIL |
| `apps/api-server/tests/test_excel.py` | 13 PASS, 0 FAIL |
| `apps/api-server/tests/test_queue_recovery.py` | 7 PASS, 0 FAIL |
| `apps/api-server/tests/test_report_history.py` | 2 PASS, 0 FAIL |
| `apps/api-server/tests/test_repositories.py` | 6 PASS, 0 FAIL |
| `apps/api-server/tests/test_retired_features.py` | 10 PASS, 0 FAIL |
| `apps/api-server/tests/test_runner_queue.py` | 3 PASS, 0 FAIL |
| `apps/api-server/tests/test_schedule_capacity_api.py` | 2 PASS, 0 FAIL |
| `apps/api-server/tests/test_socketio_flow.py` | 3 PASS, 0 FAIL |
| `apps/api-server/tests/test_time_zones.py` | 6 PASS, 0 FAIL |
| `apps/api-server/tests/test_ui_health_logs.py` | 5 PASS, 0 FAIL |
| `apps/api-server/tests/test_upload_limits.py` | 8 PASS, 0 FAIL |

### Backend, browser runner, scripts và tools

| File / bước | Kết quả |
|---|---:|
| `apps/api-server/scripts/test-user-state-codec.py` | PASS |
| `apps/api-server/verification/test_account_passwords.py` | PASS; 7 tests |
| `apps/api-server/verification/test_account_passwords.py-migrate` | PASS |
| `apps/api-server/verification/test_annual_reports.py` | PASS; 23 tests |
| `apps/api-server/verification/test_annual_reports.py-migrate` | PASS |
| `apps/api-server/verification/test_captcha_ephemeral.py` | PASS; 8 tests |
| `apps/api-server/verification/test_captcha_ephemeral.py-migrate` | PASS |
| `apps/api-server/verification/test_captcha_refresh_race.py` | PASS; 5 tests |
| `apps/api-server/verification/test_captcha_refresh_race.py-migrate` | PASS |
| `apps/api-server/verification/test_filter_profiles.py` | PASS; 8 tests |
| `apps/api-server/verification/test_filter_profiles.py-migrate` | PASS |
| `apps/api-server/verification/test_main_live_workbook.py` | PASS |
| `apps/api-server/verification/test_main_migration.py` | PASS |
| `apps/api-server/verification/test_ocr_platform.py` | PASS; 6 tests |
| `apps/api-server/verification/test_ocr_platform.py-migrate` | PASS |
| `apps/api-server/verification/test_permissions.py` | PASS; 5 tests |
| `apps/api-server/verification/test_permissions.py-migrate` | PASS |
| `apps/api-server/verification/test_production_config.py` | PASS; 15 tests |
| `apps/api-server/verification/test_production_config.py-migrate` | PASS |
| `apps/api-server/verification/test_queue_migrations.py` | PASS; 2 tests |
| `apps/api-server/verification/test_queue_migrations.py-migrate` | PASS |
| `apps/api-server/verification/test_queue_retry_checkpoints.py` | PASS; 5 tests |
| `apps/api-server/verification/test_queue_retry_checkpoints.py-migrate` | PASS |
| `apps/api-server/verification/test_report_coverage.py` | PASS; 8 tests |
| `apps/api-server/verification/test_report_coverage.py-migrate` | PASS |
| `apps/api-server/verification/test_report_results.py` | PASS; 22 tests |
| `apps/api-server/verification/test_report_results.py-migrate` | PASS |
| `apps/api-server/verification/test_retry_sessions.py` | PASS; 12 tests |
| `apps/api-server/verification/test_retry_sessions.py-migrate` | PASS |
| `apps/api-server/verification/test_run_controls.py` | PASS; 5 tests |
| `apps/api-server/verification/test_run_controls.py-migrate` | PASS |
| `apps/api-server/verification/test_run_history.py` | PASS; 7 tests |
| `apps/api-server/verification/test_run_history.py-migrate` | PASS |
| `apps/api-server/verification/test_run_schedules.py` | PASS; 39 tests |
| `apps/api-server/verification/test_run_schedules.py-migrate` | PASS |
| `apps/api-server/verification/test_session_limits.py` | PASS; 8 tests |
| `apps/api-server/verification/test_session_limits.py-migrate` | PASS |
| `apps/api-server/verification/test_shared_batch_queue.py` | PASS |
| `apps/api-server/verification/test_shared_batch_queue.py-migrate` | PASS |
| `apps/api-server/verification/test_shared_migration.py` | PASS |
| `apps/api-server/verification/test_ui_contract.py` | PASS; 11 tests |
| `apps/api-server/verification/test_ui_contract.py-migrate` | PASS |
| `apps/api-server/verification/test_update_status.py` | PASS; 3 tests |
| `apps/api-server/verification/test_update_status.py-migrate` | PASS |
| `apps/api-server/verification/test_worker_lifecycle.py` | PASS; 2 tests |
| `apps/api-server/verification/test_worker_lifecycle.py-migrate` | PASS |
| `apps/api-server/verification/test_worker_pool.py` | PASS; 7 tests |
| `apps/api-server/verification/test_worker_pool.py-migrate` | PASS |
| `apps/browser-runner/test-filter-fill.mjs` | PASS |
| `apps/browser-runner/test-health-navigation.mjs` | PASS |
| `apps/browser-runner/test-health-trigger.mjs` | PASS |
| `apps/browser-runner/test-image-pipe.mjs` | PASS |
| `apps/browser-runner/test-job-lifecycle.mjs` | PASS |
| `apps/browser-runner/test-main-report-save.mjs` | PASS |
| `apps/browser-runner/test-navigation.mjs` | PASS |
| `apps/browser-runner/test-options.mjs` | PASS |
| `apps/browser-runner/test-page-recovery.mjs` | PASS |
| `apps/browser-runner/test-profile-options.mjs` | PASS |
| `apps/browser-runner/test-results.mjs` | PASS |
| `apps/browser-runner/test-ui-health-contract.mjs` | PASS |
| `historical-fixture-setup` | PASS |
| `scripts/test_deployment_guard.py` | PASS; 12 tests |
| `scripts/test_worker_capacity.py` | PASS; 7 tests |
| `tools/ui-drift-guard/test_ui_contract.py` | PASS |
| `tools/ui-drift-guard/test_ui_diagnostics.py` | PASS |

### Web UI Playwright

| File | Kết quả |
|---|---:|
| `apps/web-ui/scripts/test-batch-timing.mjs` | PASS |
| `apps/web-ui/scripts/test-schedule-timing.mjs` | PASS |
| `apps/web-ui/scripts/test-time-zones.mjs` | PASS |
| `apps/web-ui/scripts/test-session-ui.mjs` | PASS |
| `apps/web-ui/scripts/test-annual-reports.mjs` | PASS |
| `apps/web-ui/scripts/test-filter-profiles-ui.mjs` | PASS |
| `apps/web-ui/scripts/test-health-page-ui.mjs` | PASS |
| `apps/web-ui/scripts/test-navigation-ui.mjs` | PASS |
| `apps/web-ui/scripts/test-run-schedules-ui.mjs` | PASS |
| `apps/web-ui/scripts/test-update-history-ui.mjs` | PASS |
| `apps/web-ui/scripts/test-account-settings-ui.mjs` | PASS |
| `apps/web-ui/scripts/test-network-ui.mjs` | PASS |
| `apps/web-ui/scripts/test-permissions-ui.mjs` | PASS |

### Build

| Lệnh | Kết quả |
|---|---:|
| `npm.cmd run build` (`apps/web-ui`) | PASS |

## Log và dữ liệu đo

- `results.json`: kết quả từng file của suite backend/runner/scripts/tools.
- `core-repeat.xml` và `core-repeat.log`: lần chạy full API core cuối cùng.
- `ui-platform-rerun.log`, `web-build-final.log`: UI và build.
- `eta-measurement.json`, `eta-observations.jsonl`: sai số từng dự báo và số liệu tổng hợp.
- `eta-run.log`: tiến trình benchmark và hoàn tất 100 case.

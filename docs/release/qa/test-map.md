# Test map — luồng chính → test tự động → D3 (T52a, C3.1)

Đường dẫn tính từ gốc repo. "CI" = đăng ký trong `.github/workflows/platform.yml` hoặc `apps/web-ui/scripts/test-platform.mjs`.
Cột D3 là kiểm chứng thủ công/E2E trên VAHAN thật (ledger `docs/release/evidence/Rxx.md`); **trống = chưa có kết quả**, không ngụ ý đã pass.

| Luồng | Dòng | Test tự động (API / runner) | Test tự động (web) | D3 |
| --- | --- | --- | --- | --- |
| Đăng nhập, đổi mật khẩu, phiên, member bị chặn | R2 | `verification/test_account_passwords.py`, `test_permissions.py`, `test_session_limits.py` | `test-account-settings-ui.mjs`, `test-permissions-ui.mjs`, `test-session-ui.mjs` | R2 |
| Lưu filter profile, tải option, preview | R3 | `verification/test_filter_profiles.py`; runner `test-options.mjs`, `test-profile-options.mjs`, `test-filter-fill.mjs` | `test-filter-profiles-ui.mjs` | R3 |
| UI Health preflight (fail closed) | R6 | `verification/test_ui_contract.py`, `tests/test_ui_health_logs.py`; runner `test-ui-health-contract.mjs` | `test-health-page-ui.mjs` | R6 |
| Lịch Once/Monthly, múi giờ, xóa Daily cũ | R7, R7b | `verification/test_run_schedules.py`, `test_daily_schedule_removal.py`, `tests/test_time_zones.py`, `tests/test_annual_schedule_rollover.py` | `test-run-schedules-ui.mjs`, `test-time-zones.mjs` | R7, R7b |
| Chạy queue, lưu kết quả, retry/NO_DATA | R4, R11 | `verification/test_report_results.py`, `test_queue_retry_checkpoints.py`, `test_retry_sessions.py`, `test_shared_batch_queue.py`; runner `test-job-lifecycle.mjs`, `test-main-report-save.mjs`, `test-results.mjs` | `test-navigation-ui.mjs` | R4, R11 |
| Pause / tiếp tục / worker / giới hạn song song | R9, R9b | `verification/test_run_controls.py`, `test_worker_pool.py`, `test_worker_lifecycle.py`; `tests/test_runner_queue.py`, `test_schedule_capacity_api.py`; `scripts/test_worker_capacity.py` | — | R9, R9b |
| Mất / khôi phục mạng VAHAN | R12 | runner `test-page-recovery.mjs`, `test-navigation.mjs` | `test-network-ui.mjs` | R12 |
| Bảng năm, export Excel (có lọc và Export all) | R5 | `verification/test_annual_reports.py`, `test_report_coverage.py`, `test_update_status.py` | `test-annual-reports.mjs` | R5 |
| ETA | R8 | `verification/measure_eta_run.py` (đo ≥ 100 case, ≥ 30 phút) | `test-batch-timing.mjs`, `test-schedule-timing.mjs` | R8 |
| CAPTCHA auto-solve, không log OCR thô, không quota | R14 | `verification/test_ocr_platform.py`, `test_captcha_ephemeral.py`, `test_captcha_refresh_race.py`, `tests/test_ocr_unlimited.py`; runner `test-ocr-start.mjs`, `test-image-pipe.mjs` | — | R14 |
| Run History | R17 | `verification/test_run_history.py` | `test-update-history-ui.mjs` | R17 |
| Entry point đã gỡ (Maker Update, API legacy) | R13, R15 | `tests/test_api.py`, `tests/test_retired_features.py` | — | trên artifact: 404/422 |
| Role DB, production config, migration | R1, S12 | `verification/test_production_config.py`, `test_queue_migrations.py`, `scripts/test_runtime_role_lifecycle.py`, `scripts/test_deployment_guard.py` | — | T45, T45b |
| Container / image / công cụ release | C2.x | `scripts/test_container_security.py`, `test_container_scan.py`, `test_postgres_pin.py`, `test-review-package.py` | `test-installed-dashboard.mjs` | T44, T45 |
| Công cụ bằng chứng | C0.1, C5.4 | `scripts/test_evidence_check.py`, `test_release_smoke.py`, `test_config_template.py` | — | — |

## Case quan trọng (C3.2) → nơi kiểm

pause/resume, đổi worker: `test_run_controls.py`, `test_worker_pool.py` · retry checkpoint, NO_DATA: `test_queue_retry_checkpoints.py` ·
mất mạng: `test-page-recovery.mjs`, `test-network-ui.mjs` · phiên hết hạn: `test_session_limits.py` · member bị chặn: `test_permissions.py` ·
"Already saved": `test-annual-reports.mjs` / `test_report_results.py` · restart API giữa job: `test_worker_lifecycle.py` ·
claim song song không vượt giới hạn: `test_worker_pool.py`, `tests/test_runner_queue.py`.

Bản đồ này chỉ ánh xạ; kết quả pass/fail của từng test nằm ở `evidence/test-results-F.md` (T41), không ở đây.

# T16b bước (1) — Kết quả test ở H2 (đối chiếu baseline B)

**Ngày chạy:** 11/10/2026 · **Task:** T16b bước (1) trong `PLAN.md` · **Trạng thái:** báo cáo thô để Codex review; chưa phân loại nguyên nhân, chưa sửa code/test.

## 1. SHA và phạm vi

| Mục | Giá trị |
| --- | --- |
| SHA đã chạy | `b8e371c57b58bd78a3de1579ee78bf025fa2d55f` (HEAD của `release/pre-go-live`, commit `..` của mac, 11/10 01:11) |
| Quan hệ với H2 | Cây **không tính `tmp/`** giống hệt H2 `d6505ef` — Verified: `git diff d6505ef HEAD -- . ':!tmp'` rỗng; commit `b8e371c` chỉ xóa 152 file `tmp/**` |
| Cây chạy | Clone sạch `git clone --no-hardlinks` từ thư mục chính, `git status` rỗng. File chưa track của thư mục chính (`docs/release/`, `outputs/*`) **không** nằm trong cây chạy |
| Baseline B | `2bc878e`; số liệu lấy từ `C:\Dev\staging\evidence\2bc878e-baseline\py-results.json`, `js-results.txt` (Verified ở r10, không chạy lại) |
| Không áp dụng | Không phải CI; không có run trên Ubuntu (KI-04); không phải artifact; chưa chạy lặp (xem §7) |

## 2. Môi trường

| Thành phần | Giá trị | Ghi chú |
| --- | --- | --- |
| OS | Windows 11 Pro 10.0.26200 | |
| Python | 3.12.10 (venv mới trong clone) | `pip install -e "apps/api-server[dev]"` |
| Gói Python | fastapi 0.143.0, SQLAlchemy 2.1.4, pydantic 2.14.0, pytest 9.1.1, pytest-asyncio 1.4.0, asyncpg 0.32.0, alembic 1.20.0, python-socketio 5.17.0, openpyxl 3.1.5 | Không có lock; trùng phiên bản đã ghi ở baseline §8 (FastAPI 0.143.0, SQLAlchemy 2.1.4, pydantic 2.14.0, pytest 9.1.1) |
| Node | v22.23.3 (`npm ci` ở `apps/browser-runner`, `apps/web-ui`) | |
| Chromium (Playwright) | cache có sẵn `chromium-1243`, `chromium_headless_shell-1243` | Không cài mới; runner test dùng được |
| PostgreSQL | PostgreSQL 17.7 (Debian 17.7-3.pgdg12+1) | Container tạm `postgres:17.7-bookworm` (image `sha256:86e0b703…bbfd`), `127.0.0.1:55432`, đã tạo mới cho phiên này; DROP/CREATE DB trước mỗi file |
| Docker | Engine 29.8.0, 9,7 GiB | **Docker Desktop đang tắt lúc bắt đầu; tôi đã khởi động nó** (cần để chạy PostgreSQL như baseline §8) |
| Secrets test | Hằng số test-only lấy từ `.github/workflows/platform.yml` (`VAHAN_API_RUNNER_TOKEN`, `VAHAN_UI_AUTH_TOKEN_SECRET`, `VAHAN_BROWSER_STATE_KEY`); mật khẩu DB ngẫu nhiên, đã che khỏi log | Không có secret thật |

## 3. Cách chạy

- Mỗi file test dùng **một DB riêng** (`DROP DATABASE … WITH (FORCE)` rồi `CREATE`), biến môi trường theo `.github/workflows/platform.yml`. DB URL: `postgresql+asyncpg://vahan:<password>@127.0.0.1:55432/<db>`.
- Chạy tuần tự, một lần mỗi file, `python -m pytest <file> -v -rfEs --no-header -p no:cacheprovider` từ `apps/api-server`; pytest không có `-x`.
- Driver: `run_h2.py` (toàn bộ), `run_web.py` (chạy lại web), `run_web2.py` (chạy từng file của `test:platform`). Log từng lệnh nằm ở `C:\Dev\staging\evidence\b8e371c-H2\` (ngoài repo; xem §8).
- **Không** sửa code/test; **không** đăng ký test mới; cùng danh sách file với baseline B (không file nào thêm/xóa).

## 4. Kết quả Python

Cột `P/F/E/S` = passed / failed / error / skipped. Baseline B ở cùng định dạng (collection error cộng vào E).

| Mục | Lệnh (rút gọn) | H2 `P/F/E/S` | rc | giây | B `P/F/E/S` | So với B |
| --- | --- | --- | --- | --- | --- | --- |
| `migrate fresh DB` | `python -m app.migrate  (DATABASE_URL=.../vahan_migrate_fresh_test)` | exit 0 | 0 | 2.9 | exit 0 | = B |
| `alembic heads` | `python -m alembic heads` | exit 0 | 0 | 1.6 | exit 0 | = B |
| `verification/test_report_results` | `VAHAN_RESULT_TEST_DATABASE=vahan_results_platform_report_test python -m pytest verification/test_report_result` | 22 / 0 / 0 / 0 | 0 | 27.1 | 22 / 0 / 0 / 0 | = B |
| `verification/test_annual_reports` | `VAHAN_RESULT_TEST_DATABASE=vahan_results_platform_annual_test python -m pytest verification/test_annual_report` | 18 / 0 / 0 / 0 | 0 | 17.2 | 18 / 0 / 0 / 0 | = B |
| `verification/test_filter_profiles` | `VAHAN_RESULT_TEST_DATABASE=vahan_results_platform_profiles_test python -m pytest verification/test_filter_prof` | 8 / 0 / 0 / 0 | 0 | 17.9 | 8 / 0 / 0 / 0 | = B |
| `verification/test_ui_contract` | `VAHAN_RESULT_TEST_DATABASE=vahan_results_platform_contract_test python -m pytest verification/test_ui_contract` | 10 / 1 / 0 / 0 | 1 | 18.0 | 11 / 0 / 0 / 0 | **xanh ở B → đỏ ở H2** |
| `verification/test_run_controls` | `VAHAN_RESULT_TEST_DATABASE=vahan_results_platform_controls_test python -m pytest verification/test_run_control` | 2 / 3 / 0 / 0 | 1 | 16.5 | 4 / 1 / 0 / 0 | đỏ ở cả hai, **số đỏ tăng** |
| `verification/test_update_status` | `VAHAN_RESULT_TEST_DATABASE=vahan_results_platform_update_test python -m pytest verification/test_update_status` | 3 / 0 / 0 / 0 | 0 | 8.9 | 3 / 0 / 0 / 0 | = B |
| `verification/test_worker_pool` | `VAHAN_RESULT_TEST_DATABASE=vahan_results_platform_pool_test python -m pytest verification/test_worker_pool.py ` | 3 / 4 / 0 / 0 | 1 | 24.3 | 7 / 0 / 0 / 0 | **xanh ở B → đỏ ở H2** |
| `verification/test_session_limits` | `VAHAN_SESSION_TEST_DATABASE=vahan_session_platform_test python -m pytest verification/test_session_limits.py -` | 8 / 0 / 0 / 0 | 0 | 26.5 | 8 / 0 / 0 / 0 | = B |
| `verification/test_retry_sessions` | `VAHAN_RETRY_TEST_DATABASE=vahan_retry_platform_test python -m pytest verification/test_retry_sessions.py -v -r` | 3 / 9 / 0 / 0 | 1 | 19.8 | 12 / 0 / 0 / 0 | **xanh ở B → đỏ ở H2** |
| `verification/test_report_coverage` | `VAHAN_COVERAGE_TEST_DATABASE=vahan_coverage_platform_test python -m pytest verification/test_report_coverage.p` | 8 / 0 / 0 / 0 | 0 | 17.4 | 8 / 0 / 0 / 0 | = B |
| `verification/test_run_schedules` | `VAHAN_SCHEDULE_TEST_DATABASE=vahan_schedule_platform_test python -m pytest verification/test_run_schedules.py ` | 18 / 18 / 0 / 0 | 1 | 175.8 | 36 / 0 / 0 / 0 | **xanh ở B → đỏ ở H2** |
| `verification/test_queue_retry_checkpoints` | `VAHAN_QUEUE_TEST_DATABASE=vahan_queue_platform_test python -m pytest verification/test_queue_retry_checkpoints` | 4 / 1 / 0 / 0 | 1 | 61.5 | 5 / 0 / 0 / 0 | **xanh ở B → đỏ ở H2** |
| `verification/test_account_passwords` | `VAHAN_ACCOUNT_TEST_DATABASE=vahan_account_platform_test python -m pytest verification/test_account_passwords.p` | 7 / 0 / 0 / 0 | 0 | 25.1 | 7 / 0 / 0 / 0 | = B |
| `verification/test_ocr_platform (no DB var)` | `python -m pytest verification/test_ocr_platform.py -v -rfEs  (DATABASE_URL=.../vahan_api_test, no *_TEST_DATAB` | 6 / 0 / 0 / 0 | 0 | 1.2 | 6 / 0 / 0 / 0 | = B |
| `verification/test_captcha_ephemeral (no DB var)` | `python -m pytest verification/test_captcha_ephemeral.py -v -rfEs  (DATABASE_URL=.../vahan_api_test, no *_TEST_` | 2 / 0 / 0 / 0 | 0 | 2.8 | 2 / 0 / 0 / 0 | = B |
| `verification/test_captcha_refresh_race (no DB var)` | `python -m pytest verification/test_captcha_refresh_race.py -v -rfEs  (DATABASE_URL=.../vahan_api_test, no *_TE` | 3 / 0 / 0 / 0 | 0 | 2.6 | 3 / 0 / 0 / 0 | = B |
| `verification/test_permissions (no DB var)` | `python -m pytest verification/test_permissions.py -v -rfEs  (DATABASE_URL=.../vahan_api_test, no *_TEST_DATABA` | 5 / 0 / 0 / 0 | 0 | 3.7 | 5 / 0 / 0 / 0 | = B |
| `verification/test_shared_batch_queue (script)` | `PYTHONPATH=. DATABASE_URL=.../vahan_shared_batch_platform_test python verification/test_shared_batch_queue.py` | exit 1 | 1 | 3.5 | exit 0 | **xanh ở B → đỏ ở H2** |
| `verification/test_main_live_workbook` | `VAHAN_MIGRATION_TEST_DATABASE=vahan_results_migration_snapshot_test python -m pytest verification/test_main_li` | 0 / 0 / 1 / 0 | 2 | 2.9 | 0 / 0 / 1 / 0 | = B (đỏ ở cả hai) |
| `verification/test_main_migration` | `VAHAN_MIGRATION_TEST_DATABASE=vahan_results_migration_snapshot_test python -m pytest verification/test_main_mi` | 0 / 0 / 1 / 0 | 2 | 2.4 | 0 / 0 / 1 / 0 | = B (đỏ ở cả hai) |
| `verification/test_shared_migration` | `VAHAN_SHARED_TEST_DATABASE=vahan_results_shared_snapshot_test python -m pytest verification/test_shared_migrat` | 0 / 0 / 1 / 0 | 2 | 2.6 | 0 / 0 / 1 / 0 | = B (đỏ ở cả hai) |
| `tests/test_api` | `DATABASE_URL=.../vahan_api_api_test python -m pytest tests/test_api.py -v -rfEs` | 1 / 8 / 0 / 0 | 1 | 5.0 | 1 / 8 / 0 / 0 | = B (đỏ ở cả hai) |
| `tests/test_excel` | `DATABASE_URL=.../vahan_api_excel_test python -m pytest tests/test_excel.py -v -rfEs` | 0 / 0 / 11 / 0 | 1 | 5.2 | 0 / 0 / 11 / 0 | = B (đỏ ở cả hai) |
| `tests/test_repositories` | `DATABASE_URL=.../vahan_api_repositories_test python -m pytest tests/test_repositories.py -v -rfEs` | 6 / 0 / 0 / 0 | 0 | 3.0 | 6 / 0 / 0 / 0 | = B |
| `tests/test_socketio_flow` | `DATABASE_URL=.../vahan_api_socketio_flow_test python -m pytest tests/test_socketio_flow.py -v -rfEs` | 0 / 4 / 0 / 0 | 1 | 5.4 | 0 / 4 / 0 / 0 | = B (đỏ ở cả hai) |
| `tests/test_ui_health_logs` | `DATABASE_URL=.../vahan_api_ui_health_logs_test python -m pytest tests/test_ui_health_logs.py -v -rfEs` | 5 / 0 / 0 / 0 | 0 | 2.9 | 5 / 0 / 0 / 0 | = B |
| `scripts/test-user-state-codec.py` | `python scripts/test-user-state-codec.py` | exit 0 | 0 | 0.2 | exit 0 | = B |

**Tổng pytest H2:** 142 passed / 48 failed / 11 error + 3 collection error (migration-snapshot) / 0 skipped — **B:** 177 passed / 13 failed / 11 error + 3 collection error. Tổng số test cùng bằng B (201 = 177 + 13 + 11). Mọi bước `python -m app.migrate` chuẩn bị DB cho `tests/` đều exit 0. Test `tests/` đỏ **giống hệt B** (8 + 4 failed, 11 error). **Không test nào ở trạng thái skipped/xfail** ở cả hai.

`verification/` H2: 130 passed / 36 failed (B: 165 passed / 1 failed). Năm file xanh ở B nay đỏ: `test_ui_contract` (1), `test_worker_pool` (4), `test_retry_sessions` (9), `test_run_schedules` (18), `test_queue_retry_checkpoints` (1); `test_run_controls` đỏ nặng hơn (B: 1 failed → H2: 3 failed); cộng script `test_shared_batch_queue` (B: pass).

## 5. Kết quả runner / web

| Mục | Lệnh | H2 rc | giây | B (rc, giây) |
| --- | --- | --- | --- | --- |
| runner | `npm run check` (`apps/browser-runner`) | 0 | 1.5 | (0, 2) |
| runner | `npm run test:ui-health` (`apps/browser-runner`) | 0 | 3.7 | (0, 3) |
| runner | `npm run test:results` (`apps/browser-runner`) | 0 | 8.8 | (0, 9) |
| runner | `npm run test:lifecycle` (`apps/browser-runner`) | 0 | 1.0 | (0, 1) |
| runner | `npm run test:filters` (`apps/browser-runner`) | 0 | 44.0 | (0, 42) |
| runner | `npm run test:options` (`apps/browser-runner`) | 0 | 2.6 | (0, 3) |
| runner | `npm run test:navigation` (`apps/browser-runner`) | 0 | 5.5 | (0, '2 + 1') |
| runner | `npm run test:image-pipe` (`apps/browser-runner`) | 0 | 1.2 | (0, 2) |
| runner | `npm run test:profile-options` (`apps/browser-runner`) | 0 | 3.0 | (0, 3) |
| runner | `npm run test:main-report-save` (`apps/browser-runner`) | 0 | 1.0 | (0, 1) |
| web | `npm run check` | 0 | 5.8 | (0, 5) |
| web | `npm run build` | 0 | 8.6 | (0, 8) |
| web | `node scripts/test-artifact-path.mjs` | 0 | 0.2 | (0, 0) |
| web (chạy lại, §7.1) | `npm run test:platform` | 1 | 4.1 | (0, 109) |
| web (chạy lại, §7.1) | `NETWORK_UI_URL=http://127.0.0.1:5189/ node scripts/test-network-ui.mjs` | 0 | 9.9 | pass (PLAN §8) |
| web (chạy lại, §7.1) | `ACCOUNT_UI_URL=http://127.0.0.1:5189/ node scripts/test-account-settings-ui.mjs` | 1 | 2.0 | pass (PLAN §8) |
| web (chạy lại, §7.1) | `PERMISSIONS_UI_URL=http://127.0.0.1:5193/ PLAYWRIGHT_CHANNEL=chromium node scripts/test-permissions-ui.mjs` | 0 | 8.7 | pass (PLAN §8) |

`npm run test:platform` dừng ở file đầu tiên đỏ (`test-schedule-timing`), nên 7 file sau không chạy trong lệnh đó. Để có kết quả từng file, tôi chạy riêng từng file trong cùng môi trường URL của `test-platform.mjs` (Vite :5184):

| File | H2 rc | giây |
| --- | --- | --- |
| `scripts/test-batch-timing.mjs` | 0 | 0.8 |
| `scripts/test-schedule-timing.mjs` | 1 | 0.8 |
| `scripts/test-session-ui.mjs` | 0 | 10.3 |
| `scripts/test-annual-reports.mjs` | 1 | 2.0 |
| `scripts/test-filter-profiles-ui.mjs` | 1 | 39.6 |
| `scripts/test-health-page-ui.mjs` | 1 | 32.3 |
| `scripts/test-navigation-ui.mjs` | 0 | 3.5 |
| `scripts/test-run-schedules-ui.mjs` | 1 | 32.0 |
| `scripts/test-update-history-ui.mjs` | 0 | 18.2 |

B: cả 9 file pass (`test:platform` rc 0). 4/9 xanh, 5/9 đỏ ở H2.

## 6. Lỗi thực tế

Văn bản lỗi lấy nguyên từ log (đã bỏ phần đường dẫn clone). **Nguyên nhân gốc chưa được xác minh** — mục "Phân loại sơ bộ" chỉ là giả thuyết để T16b(2).

### `verification/test_ui_contract`

- `test_disabled_worker_error_is_retained_without_blocking_selected_pool` — AssertionError: 'playwright-2' not found in {} : keep disabled-worker diagnostic

### `verification/test_run_controls`

- `test_five_worker_limit_is_enforced_across_ten_claimants` — AssertionError: 1 != 5
- `test_one_worker_can_retry_its_own_failed_case` — KeyError: 'jobId'
- `test_pause_and_reduce_workers_preserves_completed_cases` — AssertionError: ValueError not raised

### `verification/test_worker_pool`

- `test_disabled_worker_and_planning_reservations_obey_limit` — AssertionError: ValueError not raised
- `test_limits_one_five_ten_keep_containers_connected` — AssertionError: 10 != 1
- `test_preflight_reservation_blocks_unsafe_shrink` — AssertionError: PoolError not raised
- `test_shrink_preserves_busy_job_and_can_grow` — AssertionError: PoolError not raised

### `verification/test_retry_sessions`

- `test_delete_and_restore_keep_cases_files_and_monthly_data` — fastapi.exceptions.HTTPException: 409: Runner was assigned another job or disconnected.
- `test_delete_is_blocked_for_active_job_and_between_batch_cases` — fastapi.exceptions.HTTPException: 409: Runner was assigned another job or disconnected.
- `test_deleted_session_cannot_accept_retry_until_restored` — AssertionError: 'Restore' not found in 'Runner was assigned another job or disconnected.'
- `test_distinct_new_cases_with_identical_filters_are_not_merged` — fastapi.exceptions.HTTPException: 409: Runner was assigned another job or disconnected.
- `test_failed_retry_chain_keeps_one_failure_until_recovered` — fastapi.exceptions.HTTPException: 409: Runner was assigned another job or disconnected.
- `test_legacy_retries_are_collapsed_and_can_be_retried_again` — fastapi.exceptions.HTTPException: 409: Runner was assigned another job or disconnected.
- `test_no_data_retry_updates_no_data_and_txt` — fastapi.exceptions.HTTPException: 409: Runner was assigned another job or disconnected.
- `test_retry_replaces_failure_counts_and_download_without_new_case` — fastapi.exceptions.HTTPException: 409: Runner was assigned another job or disconnected.
- `test_stopped_retry_continues_same_case` — fastapi.exceptions.HTTPException: 409: Runner was assigned another job or disconnected.

### `verification/test_run_schedules`

- `test_automatic_preflight_records_all_selected_workers_without_ui` — fastapi.exceptions.HTTPException: 409: {'code': 'PREFLIGHT_WAITING', 'message': 'Waiting for all selected workers to be online and idle. No website change was recorded; the check will retry automatically.', 'retryAfterMs': 5000, 'diagnostics': {'allowed': False, 'preflightId': '6eabdfe9-5d98-4c03-b7
- `test_committed_assignment_is_redelivered_after_socket_failure` — AssertionError: None != 'Fixture delivery failure'
- `test_daily_run_finishes_with_next_future_slot` — AssertionError: datetime.datetime(2026, 10, 11, 14, 42, 41, 752389, tzinfo=datetime.timezone.utc) not greater than datetime.datetime(2026, 10, 11, 14, 43, 44, 501991, tzinfo=datetime.timezone.utc)
- `test_dates_validation_and_daily_and_monthly_time_zones` — AssertionError: ValidationError not raised
- `test_delete_checks_ownership_and_active_jobs_even_if_status_is_paused` — AssertionError: ValueError not raised
- `test_delete_paused_run_discards_queue_and_retains_collected_data` — IndexError: list index out of range
- `test_diagnostics_show_stuck_step_and_busy_unselected_worker` — AttributeError: module 'app.run_diagnostics' (app\\run_diagnostics.py) does not have the attribute 'settings'
- `test_expired_or_revoked_dashboard_session_does_not_stop_dispatch` — AssertionError: 0 != 2
- `test_headless_checkpoints_final_sweep_and_resume_recover_all_failures` — AssertionError: Automatic recovery did not finish
- `test_legacy_stopped_run_can_continue_saved_queue` — AssertionError: 0 != 1
- `test_network_outage_requeues_interrupted_case_without_failure_and_resumes` — IndexError: list index out of range
- `test_pause_drain_resize_up_and_down_preserves_same_cases` — AssertionError: 0 != 2 : Pausing must not claim the next pending case.
- `test_pause_during_preparation_fences_old_plan` — AssertionError: 0 != 3
- `test_pause_epoch_ownership_and_worker_validation` — AssertionError: ValueError not raised
- `test_resume_check_failure_keeps_session_paused` — AssertionError: 0 != 2
- `test_stop_cancels_active_jobs_and_retains_history` — AssertionError: 0 != 2
- `test_ui_health_block_prevents_any_new_assignment` — AssertionError: 0 != 2
- `test_unattended_dispatch_worker_cap_completion_and_no_data` — AssertionError: 0 != 2

### `verification/test_queue_retry_checkpoints`

- `test_group_barrier_final_scan_distribution_restart_and_no_data` — KeyError: 'task'

### `verification/test_main_live_workbook`

- `(lỗi thu thập khi import module)` — asyncpg.exceptions.UndefinedTableError: relation "stored_files" does not exist // sqlalchemy.dialects.postgresql.asyncpg.AsyncAdapt_asyncpg_dbapi.ProgrammingError: relation "stored_files" does not exist // sqlalchemy.exc.ProgrammingError: (sqlalchemy.dialects.postgresql.asyncpg.ProgrammingError) rel

### `verification/test_main_migration`

- `(lỗi thu thập khi import module)` — asyncpg.exceptions.UndefinedTableError: relation "annual_records" does not exist // sqlalchemy.dialects.postgresql.asyncpg.AsyncAdapt_asyncpg_dbapi.ProgrammingError: relation "annual_records" does not exist // sqlalchemy.exc.ProgrammingError: (sqlalchemy.dialects.postgresql.asyncpg.ProgrammingError)

### `verification/test_shared_migration`

- `(lỗi thu thập khi import module)` — asyncpg.exceptions.UndefinedTableError: relation "main_reports" does not exist // sqlalchemy.dialects.postgresql.asyncpg.AsyncAdapt_asyncpg_dbapi.ProgrammingError: relation "main_reports" does not exist // sqlalchemy.exc.ProgrammingError: (sqlalchemy.dialects.postgresql.asyncpg.ProgrammingError) rel

### `tests/test_api`

- `test_ui_health_schedule_defaults_to_three_days` — assert 401 == 200 // +  where 401 = <Response [401 Unauthorized]>.status_code
- `test_ui_health_schedule_allows_web_ui_origin` — assert 401 == 200 // +  where 401 = <Response [401 Unauthorized]>.status_code
- `test_ui_health_schedule_can_be_updated` — assert 401 == 200 // +  where 401 = <Response [401 Unauthorized]>.status_code
- `test_ui_health_schedule_rejects_invalid_interval` — assert 401 == 422 // +  where 401 = <Response [401 Unauthorized]>.status_code
- `test_ui_health_run_now_requires_connected_runner` — assert 401 == 409 // +  where 401 = <Response [401 Unauthorized]>.status_code
- `test_ui_health_log_can_be_saved_reviewed_and_downloaded` — assert 401 == 201 // +  where 401 = <Response [401 Unauthorized]>.status_code
- `test_create_job_requires_online_runner` — assert 401 == 404 // +  where 401 = <Response [401 Unauthorized]>.status_code
- `test_create_get_and_cancel_job` — assert 401 == 201 // +  where 401 = <Response [401 Unauthorized]>.status_code

### `tests/test_excel`

- `ERROR at setup of test_upload_and_download_excel_flow` — AttributeError: <module 'app.api.excel' from 'apps\\api-server\\app\\api\\excel.py'> has no attribute '_report_dir'
- `ERROR at setup of test_upload_rejects_non_excel_bytes` — AttributeError: <module 'app.api.excel' from 'apps\\api-server\\app\\api\\excel.py'> has no attribute '_report_dir'
- `ERROR at setup of test_job_cannot_complete_without_saved_excel` — AttributeError: <module 'app.api.excel' from 'apps\\api-server\\app\\api\\excel.py'> has no attribute '_report_dir'
- `ERROR at setup of test_no_data_keeps_state_and_rto_without_creating_excel` — AttributeError: <module 'app.api.excel' from 'apps\\api-server\\app\\api\\excel.py'> has no attribute '_report_dir'
- `ERROR at setup of test_cancelled_job_cannot_become_no_data_or_write_text` — AttributeError: <module 'app.api.excel' from 'apps\\api-server\\app\\api\\excel.py'> has no attribute '_report_dir'
- `ERROR at setup of test_upload_excel_non_existent_job` — AttributeError: <module 'app.api.excel' from 'apps\\api-server\\app\\api\\excel.py'> has no attribute '_report_dir'
- `ERROR at setup of test_upload_excel_rejects_empty_file` — AttributeError: <module 'app.api.excel' from 'apps\\api-server\\app\\api\\excel.py'> has no attribute '_report_dir'
- `ERROR at setup of test_download_excel_not_found` — AttributeError: <module 'app.api.excel' from 'apps\\api-server\\app\\api\\excel.py'> has no attribute '_report_dir'
- `ERROR at setup of test_repeat_and_concurrent_uploads_save_one_readable_workbook` — AttributeError: <module 'app.api.excel' from 'apps\\api-server\\app\\api\\excel.py'> has no attribute '_report_dir'
- `ERROR at setup of test_storage_failure_returns_useful_error_with_cors` — AttributeError: <module 'app.api.excel' from 'apps\\api-server\\app\\api\\excel.py'> has no attribute '_report_dir'
- `ERROR at setup of test_cancellation_during_workbook_validation_leaves_no_report` — AttributeError: <module 'app.api.excel' from 'apps\\api-server\\app\\api\\excel.py'> has no attribute '_report_dir'

### `tests/test_socketio_flow`

- `test_runner_job_and_captcha_round_trip` — socketio.exceptions.ConnectionError: One or more namespaces failed to connect: /runner
- `test_ui_health_schedule_update_reaches_runner` — socketio.exceptions.ConnectionError: One or more namespaces failed to connect: /runner
- `test_ui_health_manual_check_request_reaches_runner` — socketio.exceptions.ConnectionError: One or more namespaces failed to connect: /runner
- `test_ui_health_log_received_is_broadcast_to_web_ui` — socketio.exceptions.ConnectionError: One or more namespaces failed to connect: /ui

### script `verification/test_shared_batch_queue.py`

- `AssertionError` ở `test_shared_batch_queue.py:49`: `assert all(item['type'] == 'assigned' for item in first)` — 10 lệnh `claim` đồng thời của 10 runner trên cùng queue 20 task không trả hết `assigned`. B: pass.

### Web (chạy lại từ đường dẫn thật)

- `scripts/test-schedule-timing.mjs` (và vì thế `npm run test:platform`) — `TypeError [ERR_UNSUPPORTED_RESOLVE_REQUEST]: Failed to resolve module specifier "./services/persistent-state" from "data:text/javascript;base64,…"` (`ERR_INVALID_URL`). Test biên dịch `schedule-timing.ts` thành `data:` URL nhưng module nay import `./services/persistent-state` (`src/run-schedules.ts:1`).
- `scripts/test-annual-reports.mjs` — `AssertionError: reports default to the current year even when crawl settings use a historical year` — `'' !== '2026'`.
- `scripts/test-filter-profiles-ui.mjs` — `locator.waitFor: Timeout 30000ms` chờ `getByLabel('Report / filter profile')`: `<select disabled required aria-label="Report / filter profile">` ẩn.
- `scripts/test-health-page-ui.mjs` — `locator.selectOption: Timeout 30000ms` chờ `getByLabel('Active workers', { exact: true })`.
- `scripts/test-run-schedules-ui.mjs` — `TimeoutError` ở `selectOption`: element "not visible" (58 lần thử).
- `scripts/test-account-settings-ui.mjs` — `locator.fill: strict mode violation: getByRole('dialog', { name: 'Account settings' }).getByLabel('New password', { exact: true }) resolved to 2 elements` (form đổi mật khẩu và form `Reset password` cùng dialog, cùng nhãn).

### Phân loại sơ bộ (giả thuyết, chưa xác minh)

| Nhóm | Dấu hiệu | Test |
| --- | --- | --- |
| Mô hình worker/claim H2 (mặc định 1, không trần 10, tự claim) | `10 != 1`, `ValueError not raised`/`PoolError not raised` (kỳ vọng trần 10 hoặc giới hạn đã bỏ), `0 != 2`/`0 != 3` (số case được giao), `409 Runner was assigned another job or disconnected`, `PREFLIGHT_WAITING`, script assert `assigned` | `test_worker_pool` (4), `test_run_controls` (3), `test_retry_sessions` (9), `test_run_schedules` (phần lớn), `test_queue_retry_checkpoints`, script `shared_batch_queue`, `test_ui_contract` |
| Thay đổi API/hợp đồng khác | `'playwright-2' not found in {}` (`runnerErrors`), `AttributeError … run_diagnostics … 'settings'` (test patch thuộc tính không còn), `KeyError: 'task'`/`'jobId'` | `test_ui_contract`, `test_run_schedules`, `test_queue_retry_checkpoints`, `test_run_controls` |
| Lỗi sẵn có ở B (không đổi) | 401 do thiếu token; `_report_dir` đã xóa ở `287bfe7`; `/runner`, `/ui` không kết nối; `relation … does not exist` | `tests/*`, 3 file migration-snapshot |
| UI/test web | import `./services/persistent-state` trong `data:` URL; nhãn/selector đã đổi | 6 file web ở §5 |
| Chưa rõ | `test_daily_run_finishes_with_next_future_slot` (`datetime … not greater than …`, chênh ~63 giây), `test_headless_checkpoints_…` (`Automatic recovery did not finish`), `test_committed_assignment_is_redelivered…` (`None != 'Fixture delivery failure'`) | `test_run_schedules` |

PLAN §3.1 R9b dự đoán `test_worker_pool.py:41` còn kiểm `playwright-11`. Kết quả: các test đỏ ở `test_worker_pool.py` thất bại tại dòng 38, 50, 85, 97; dòng 41 nằm sau điểm thất bại ở dòng 38 của cùng test nên **dự đoán đó chưa được xác nhận hay bác bỏ**.

## 7. Điều kiện/giới hạn cần Codex chú ý

1. **(§7.1) Lần chạy web đầu tiên không hợp lệ.** Clone nằm dưới đường dẫn 8.3 (`C:\Users\NGHIAN~1\…`); Vite báo `The request id … is outside of Vite serving allow list` nên `test:platform` và 3 UI test ngoài CI đỏ vì môi trường (kết quả: Vite không sẵn sàng / `Settings` link không hiện). Tôi **bỏ** các kết quả đó và chạy lại cùng cây từ đường dẫn dài `C:\Users\nghianc19\…`. Bảng §5 chỉ dùng kết quả chạy lại. Log lần đầu giữ trong `logs\` (các file `web_*`), đánh dấu bằng `SUPERSEDED.txt`.
2. **Mỗi file chạy đúng một lần.** `test_run_controls` ở B đỏ do cách ly test (BF-01); ở H2 nó đỏ 3/5 trong một lần chạy trên DB sạch. Chưa chạy riêng từng test hay lặp ×3 / hoán vị (thuộc T10), nên **chưa tách được** lỗi cách ly khỏi lỗi hành vi mới.
3. **Tính tái lập theo thời gian:** `test_daily_run_finishes_with_next_future_slot` so sánh `datetime` thực; kết quả có thể phụ thuộc giờ chạy (11/10 14:4x UTC).
4. **Không tương đương CI:** chạy trên Windows với Docker Desktop; CI chạy Ubuntu/PostgreSQL service. Test web ngoài CI dùng `PLAYWRIGHT_CHANNEL=chromium`.
5. **Chưa chạy (ngoài bước 1):** lặp BF-01 ×3 và hoán vị (T10); `python -m app.migrate` up/down `0012→0014` trên DB đã có dữ liệu (T16b bước 4); `verification/maker_update_smoke.py` (không phải test, B cũng không chạy); `tools/ui-drift-guard` (Not verified ở B); `docker compose build`; test claim/lease mới (bước 3, chưa viết).
6. **Dọn dẹp:** container `vahan-t16b-pg` và clone trong scratchpad còn tồn tại để Codex kiểm; chưa xóa.

## 8. Bằng chứng

| Thành phần | Vị trí |
| --- | --- |
| Log Python/runner (đã che mật khẩu DB); các file `web_*` ở đây là lần chạy đầu **không hợp lệ** (`SUPERSEDED.txt`) | `C:\Dev\staging\evidence\b8e371c-H2\logs\*.log` |
| Log web chạy lại (hợp lệ) | `…\b8e371c-H2\logs-web-rerun\`, `…\logs-web-platform-files\` |
| Kết quả máy đọc được | `…\b8e371c-H2\results.json`, `results-web.json` (chạy lại), `results-web-platform-files.json`, `env.json` |
| Driver | `…\b8e371c-H2\run_h2.py`, `run_web.py`, `run_web2.py` |
| Baseline B | `C:\Dev\staging\evidence\2bc878e-baseline\` |

## 9. Việc kế tiếp (không làm ở bước này)

- T16b(2): xác định từng test đỏ là test lỗi thời hay lỗi sản phẩm; sửa test, **không skip**.
- T10 (BF-01) chạy sau khi có baseline H2 này.
- Cập nhật `defects.md`: DEF-06 (có số liệu), DEF-07; thêm defect cho web test đỏ (6 file) và script `shared_batch_queue` — **chưa làm**, chờ Codex review báo cáo này.

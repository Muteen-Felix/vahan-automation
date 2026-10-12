# T16b bước (2) — Phân loại test đỏ ở H2 (trước khi sửa)

**Ngày:** 11/10/2026 · **Cây:** `b8e371c` (non-`tmp` ≡ H2 `d6505ef`) · **Đầu vào:** [test-results-H2.md](test-results-H2.md) · **Trạng thái:** phân loại để quyết định sửa test hay mở defect. **Không** sửa code/test, **không** skip, **không** ghi vào `defects.md`.

## 1. Kết luận

| Nhóm | Số mục | Hành động |
| --- | --- | --- |
| **Lỗi thời** (test mã hóa hành vi B đã bị thay có chủ ý bởi H1/H2) | Python 36 mục mới (35 pytest + 1 script) · Web 6 file | Sửa/viết lại test, không skip; giữ nguyên ý đồ kiểm thử |
| **Nghi lỗi sản phẩm** | 2 defect ứng viên + 1 câu hỏi cho dev | Mở defect (đề xuất `DEF-33`, `DEF-34`), Felix quyết severity |
| **Có sẵn từ B** | `tests/` 12 failed + 11 error, 3 file migration-snapshot, BF-01 | Giữ theo kế hoạch cũ (T12, T10, KI-12) |
| **Chưa rõ** | 0 test còn lại chưa phân loại; 1 điểm cần dev xác nhận (Q1) | — |

Điểm quyết định:

1. **35 test pytest + 1 script đỏ mới chỉ xuất hiện ở H2** (`b9dd731`, `30e4429`); cùng file đều xanh ở H1 `dace058`. Test thứ 37 (`test_run_controls::test_pause_and_reduce…`) là BF-01, đỏ từ B. **6 file web đỏ xuất hiện ở H1** (`3907c2d`/`dace058`), không phải H2.
2. **Không test Python nào đỏ vì lỗi sản phẩm trực tiếp** theo bằng chứng chạy lại: 33/36 test của `test_run_schedules` xanh khi khôi phục `run_scheduler.py` của B và mặc định 10; các file còn lại hoặc xanh khi đặt lại mặc định 10 (`run_controls`, `retry_sessions`, `queue_retry`, script), hoặc đỏ vì khái niệm đã bị gỡ (`worker_pool`, `ui_contract`).
3. **Nhưng test đỏ đã làm lộ một lỗi sản phẩm ứng viên (NSP-1, mức cao):** `prepare_run` đưa **mọi** runner idle vào preflight trong khi giới hạn song song chỉ bằng `workerCount`; nếu số runner idle > `workerCount` thì preflight không bao giờ đặt chỗ được và lịch chờ mãi. Tái hiện ở mức `reserve_preflight_runners` (F1) và qua test cô lập; **chưa** tái hiện end-to-end qua `scheduler_tick`.
4. **Kết luận về bằng chứng:** các test sẽ phải viết lại là phần phủ duy nhất cho pause/resume/stop/delete/network-pause trên mô hình runner tự claim. Đến khi viết lại và xanh, **R7, R9, R9b, R10, R11, R12 không có E-CI hợp lệ ở H2**. Việc 33 test xanh trong biến thể B-scheduler chỉ cho thấy phần logic ngoài dispatch chưa bị phá, **không** thay cho kiểm chứng H2.

## 2. Phương pháp và bằng chứng

Mọi lần chạy dùng cùng PostgreSQL 17.7 tạm và các biến môi trường như T16b(1). Biến thể chỉ khác ở thư mục sao chép dưới scratchpad; **repo không bị sửa**. Chênh lệch từng biến thể: `triage/variants.diff`.

| Mã | Thực hiện | Ý nghĩa |
| --- | --- | --- |
| **H1** | Cùng file test chạy trên `dace058` (H1), `diag2.py h1 …` | Xanh ở H1 ⇒ lỗi do H2 (`b9dd731`/`30e4429`) |
| **A0, B1–B3, C1** | `-k` một test, không seed, DB sạch (B1 `daily_next_slot`, B2 `automatic_preflight`, B3 `dates_validation`, C1 `ui_contract`) | Loại trừ lỗi do thứ tự/rò rỉ giữa test |
| **A1/A2** | Sau `app.migrate`, seed `app_settings['docker-worker-pool'] = {desiredCount:10}` rồi chạy file | Kiểm tra phụ thuộc mặc định 10 |
| **A3 (không hợp lệ)** | Seed như A1 cho `test_queue_retry_checkpoints` | **Không có hiệu lực**: `asyncSetUp` `drop_all/create_all` xóa seed; thay bằng V10 |
| **V10** | `worker_pool.DEFAULT_CONCURRENCY = 10` trên bản sao H2 (thay cho seed; chịu được `drop_all`) | Kiểm tra phụ thuộc mặc định 10 |
| **V10+B** | V10 + `app/run_scheduler.py` thay bằng bản B `2bc878e` | Tách nguyên nhân "server đẩy assignment" |
| **V10+repo** | V10 + `BatchQueueRepository.start(max_workers=10)` | Chỉ cho script `test_shared_batch_queue` |
| **F1** | Script riêng gọi `reserve_preflight_runners` với 5 runner idle, `apply_pool(limit)` thay đổi | Kiểm tra NSP-1 |
| **WEB-H1/H1a** | 9 file `test:platform` + 3 UI test ngoài CI trên `dace058` và `3907c2d` | Xác định commit gây đỏ web |
| **ANN** | `test-annual-reports.mjs` thêm một dòng `waitForFunction(select Year ≠ '')` trong bản sao | Kiểm tra race |

Log: `C:\Dev\staging\evidence\b8e371c-H2\triage\` (`out_diag`, `out_diag_h2def10`, `out_diag_h2diag`, `out_diag_h1`, `out_web2_h1`, `out_web2_h1a`, `out_web_h1`); lần chạy gốc ở `…\b8e371c-H2\logs\`.

### Kết quả các lần chạy chẩn đoán

| Mã | Đối tượng | Kết quả | Log |
| --- | --- | --- | --- |
| H1 | `test_run_controls` | 4 passed / **1 failed** (BF-01, giống B) | `out_diag_h1/logs/h1__run_controls.log` |
| H1 | `test_worker_pool` | 7 passed | `h1__worker_pool.log` |
| H1 | `test_ui_contract` | 11 passed | `h1__ui_contract.log` |
| H1 | `test_retry_sessions` | 12 passed | `h1__retry_sessions.log` |
| H1 | `test_queue_retry_checkpoints` | 5 passed | `h1__queue_retry.log` |
| H1 | `test_run_schedules` | 36 passed | `h1__run_schedules.log` |
| H1 | script `test_shared_batch_queue` | exit 0 | `h1__shared_batch_script.log` |
| A0 | `test_retry_sessions -k test_no_data_retry_updates_no_data_and_txt` | 1 passed (cùng test đỏ trong cả file) | `out_diag/logs/A0_retry_sessions_single_noseed.log` |
| A0 | `test_run_controls -k test_five_worker_limit…` | 1 failed (`1 != 5`) ngay khi chạy riêng | `A0b_run_controls_single_noseed.log` |
| A1 | `test_run_controls` + seed 10 | 4 passed / 1 failed (chỉ còn BF-01) | `A1_run_controls_seed10.log` |
| A2 | `test_retry_sessions` + seed 10 | 12 passed | `A2_retry_sessions_seed10.log` |
| V10 | `test_queue_retry_checkpoints` | 5 passed | `out_diag_h2def10/logs/h2def10__queue_retry.log` |
| V10 | `test_retry_sessions` | 12 passed | `h2def10__retry_sessions.log` |
| V10 | `test_run_controls` | 4 passed / 1 failed (BF-01) | `h2def10__run_controls.log` |
| V10 | `test_worker_pool` | 3 passed / **4 failed như cũ** | `h2def10__worker_pool.log` |
| V10 | `test_ui_contract` | 10 passed / **1 failed như cũ** | `h2def10__ui_contract.log` |
| V10+B | `test_run_schedules` | **33 passed** / 3 failed (cap 11 ×2, `run_diagnostics.settings`) | `out_diag_h2diag/logs/h2diag__run_schedules.log` |
| V10+repo | script `test_shared_batch_queue` | exit 0 (1.600 task, 10 worker, 160 claim/worker) | `h2def10__shared_batch_script.log` |
| F1 | `reserve_preflight_runners` | xem §4 | `out_diag/logs/F1_preflight_capacity.log` |
| WEB-H1a (`3907c2d`) | 9 file platform | đỏ: annual-reports, filter-profiles-ui, health-page-ui, run-schedules-ui; **xanh: schedule-timing** | `out_web2_h1a/logs/` |
| WEB-H1 (`dace058`) | 9 file platform + 3 UI | đỏ: thêm schedule-timing; account-settings-ui đỏ; network, permissions xanh | `out_web2_h1/logs/`, `out_web_h1/logs/` |
| ANN | `test-annual-reports` + `waitForFunction` | pass toàn bộ | (bản sao, đã xóa; kết quả ghi trong báo cáo này) |

## 3. Bảng phân loại từng test đỏ

Cột **Đỏ từ**: `H2` = xanh ở `dace058`, đỏ ở `b8e371c`; `B` = đã đỏ ở baseline; `H1` = đỏ từ `3907c2d`/`dace058`.

Mã nhóm: **LT-A** Lỗi thời — fixture dựa mặc định 10 (pool/queue) · **LT-B** Lỗi thời — mô hình bật/tắt worker theo ID `playwright-N` đã bỏ · **LT-C** Lỗi thời — server không còn đẩy assignment (runner tự claim) · **LT-D** Lỗi thời — trần 10 đã bỏ (D-27 = d) · **LT-E** Lỗi thời — diagnostics/ui_contract đổi theo registry runner động · **LT-F** Lỗi thời — UI đổi nhãn/điều khiển, test chưa cập nhật (H1) · **LT-G** Lỗi thời — race trong test (chỉ đợi phần tử, không đợi dữ liệu) · **PRE** Có sẵn từ B — không do H2 · **MT** Điều kiện môi trường/dữ liệu nguồn thiếu — không áp dụng cho release · **NSP** Nghi lỗi sản phẩm — xử lý như defect · **CR** Chưa rõ.

### 3.1 Python — đỏ từ H2

| # | File::test | Lỗi thực tế (rút gọn) | Đỏ từ | Nhóm | Bằng chứng | Hành động đề xuất cho test |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | `test_run_controls::test_five_worker_limit_is_enforced_across_ten_claimants` | AssertionError: 1 != 5 | H2 | LT-A | A0, A1 | giới hạn hiệu dụng = min(`max_workers` của session, pool toàn cục); pool mặc định nay là 1 (B: 10) nên setUp phải đặt pool (`apply_pool(10)`) |
| 2 | `test_run_controls::test_one_worker_can_retry_its_own_failed_case` | KeyError: 'jobId' | H2 | LT-A | A1, V10 | như trên |
| 3 | `test_run_controls::test_pause_and_reduce_workers_preserves_completed_cases` | AssertionError: ValueError not raised | B | PRE | A1, V10, H1 | BF-01 (T10): runner bận còn sót từ test trước; sau khi đặt pool = 10 vẫn đỏ đúng như B |
| 4 | `test_worker_pool::test_limits_one_five_ten_keep_containers_connected` | AssertionError: 10 != 1 | H2 | LT-B | V10, H1 | viết lại theo giới hạn số lượng đồng thời, bỏ kỳ vọng `playwright-N` bị tắt và giá trị 11 bị từ chối |
| 5 | `test_worker_pool::test_shrink_preserves_busy_job_and_can_grow` | AssertionError: PoolError not raised | H2 | LT-B | V10, H1 | thu hẹp chỉ bị chặn khi số worker đang bận > giới hạn mới; dùng 3 worker bận → giới hạn 2 |
| 6 | `test_worker_pool::test_disabled_worker_and_planning_reservations_obey_limit` | AssertionError: ValueError not raised | H2 | LT-B | V10, H1 | kiểm giới hạn bằng số reservation, không bằng ID |
| 7 | `test_worker_pool::test_preflight_reservation_blocks_unsafe_shrink` | AssertionError: PoolError not raised | H2 | LT-B | V10, H1 | như trên |
| 8 | `test_ui_contract::test_disabled_worker_error_is_retained_without_blocking_selected_pool` | AssertionError: 'playwright-2' not found in {} : keep disabled-worker diagnostic | H2 | LT-E | C1, V10, H1 | khái niệm "worker bị tắt" đã bỏ; `ui_contract.evaluate` giờ chỉ giữ lỗi của runner đang `connected` (xem Q1) |
| 9 | `test_retry_sessions::test_delete_and_restore_keep_cases_files_and_monthly_data` | fastapi.exceptions.HTTPException: 409: Runner was assigned another job or disconnected. | H2 | LT-A | A0, A2, V10, H1 | đặt pool trong setUp và giải phóng runner cuối test; xem NSP-2 về thông báo 409 |
| 10 | `test_retry_sessions::test_delete_is_blocked_for_active_job_and_between_batch_cases` | fastapi.exceptions.HTTPException: 409: Runner was assigned another job or disconnected. | H2 | LT-A | A0, A2, V10, H1 | đặt pool trong setUp và giải phóng runner cuối test; xem NSP-2 về thông báo 409 |
| 11 | `test_retry_sessions::test_deleted_session_cannot_accept_retry_until_restored` | AssertionError: 'Restore' not found in 'Runner was assigned another job or disconnected.' | H2 | LT-A | A0, A2, V10, H1 | đặt pool trong setUp và giải phóng runner cuối test; xem NSP-2 về thông báo 409 |
| 12 | `test_retry_sessions::test_distinct_new_cases_with_identical_filters_are_not_merged` | fastapi.exceptions.HTTPException: 409: Runner was assigned another job or disconnected. | H2 | LT-A | A0, A2, V10, H1 | đặt pool trong setUp và giải phóng runner cuối test; xem NSP-2 về thông báo 409 |
| 13 | `test_retry_sessions::test_failed_retry_chain_keeps_one_failure_until_recovered` | fastapi.exceptions.HTTPException: 409: Runner was assigned another job or disconnected. | H2 | LT-A | A0, A2, V10, H1 | đặt pool trong setUp và giải phóng runner cuối test; xem NSP-2 về thông báo 409 |
| 14 | `test_retry_sessions::test_legacy_retries_are_collapsed_and_can_be_retried_again` | fastapi.exceptions.HTTPException: 409: Runner was assigned another job or disconnected. | H2 | LT-A | A0, A2, V10, H1 | đặt pool trong setUp và giải phóng runner cuối test; xem NSP-2 về thông báo 409 |
| 15 | `test_retry_sessions::test_no_data_retry_updates_no_data_and_txt` | fastapi.exceptions.HTTPException: 409: Runner was assigned another job or disconnected. | H2 | LT-A | A0, A2, V10, H1 | đặt pool trong setUp và giải phóng runner cuối test; xem NSP-2 về thông báo 409 |
| 16 | `test_retry_sessions::test_retry_replaces_failure_counts_and_download_without_new_case` | fastapi.exceptions.HTTPException: 409: Runner was assigned another job or disconnected. | H2 | LT-A | A0, A2, V10, H1 | đặt pool trong setUp và giải phóng runner cuối test; xem NSP-2 về thông báo 409 |
| 17 | `test_retry_sessions::test_stopped_retry_continues_same_case` | fastapi.exceptions.HTTPException: 409: Runner was assigned another job or disconnected. | H2 | LT-A | A0, A2, V10, H1 | đặt pool trong setUp và giải phóng runner cuối test; xem NSP-2 về thông báo 409 |
| 18 | `test_queue_retry_checkpoints::test_group_barrier_final_scan_distribution_restart_and_no_data` | KeyError: 'task' | H2 | LT-A | V10, H1 | `start(..., 3)` nhưng pool mặc định 1 → 2/3 claim `waiting`; đặt pool = 3 trong setUp |
| 19 | `test_run_schedules::test_automatic_preflight_records_all_selected_workers_without_ui` | fastapi.exceptions.HTTPException: 409: {'code': 'PREFLIGHT_WAITING', 'message': 'Waiting for all selected workers to be online and idle. No website ch | H2 | LT-A | B2, F1, V10+B | gọi preflight với 2 runner khi pool mặc định 1; đặt pool ≥ 2. **Cùng cơ chế với NSP-1** |
| 20 | `test_run_schedules::test_committed_assignment_is_redelivered_after_socket_failure` | AssertionError: None != 'Fixture delivery failure' | H2 | LT-C | H1 (36 passed), V10+B (33 passed) | thay `scheduler_tick` ⇒ assignment bằng bước mô phỏng runner gọi claim; giữ nguyên ý đồ pause/resume/stop/delete |
| 21 | `test_run_schedules::test_daily_run_finishes_with_next_future_slot` | AssertionError: datetime.datetime(2026, 10, 11, 14, 42, 41, 752389, tzinfo=datetime.timezone.utc) not greater than datetime.datetime(2026, 10, 11, 14, | H2 | LT-C | H1 (36 passed), V10+B (33 passed) | thay `scheduler_tick` ⇒ assignment bằng bước mô phỏng runner gọi claim; giữ nguyên ý đồ pause/resume/stop/delete |
| 22 | `test_run_schedules::test_delete_checks_ownership_and_active_jobs_even_if_status_is_paused` | AssertionError: ValueError not raised | H2 | LT-C | H1 (36 passed), V10+B (33 passed) | thay `scheduler_tick` ⇒ assignment bằng bước mô phỏng runner gọi claim; giữ nguyên ý đồ pause/resume/stop/delete |
| 23 | `test_run_schedules::test_delete_paused_run_discards_queue_and_retains_collected_data` | IndexError: list index out of range | H2 | LT-C | H1 (36 passed), V10+B (33 passed) | thay `scheduler_tick` ⇒ assignment bằng bước mô phỏng runner gọi claim; giữ nguyên ý đồ pause/resume/stop/delete |
| 24 | `test_run_schedules::test_expired_or_revoked_dashboard_session_does_not_stop_dispatch` | AssertionError: 0 != 2 | H2 | LT-C | H1 (36 passed), V10+B (33 passed) | thay `scheduler_tick` ⇒ assignment bằng bước mô phỏng runner gọi claim; giữ nguyên ý đồ pause/resume/stop/delete |
| 25 | `test_run_schedules::test_headless_checkpoints_final_sweep_and_resume_recover_all_failures` | AssertionError: Automatic recovery did not finish | H2 | LT-C | H1 (36 passed), V10+B (33 passed) | thay `scheduler_tick` ⇒ assignment bằng bước mô phỏng runner gọi claim; giữ nguyên ý đồ pause/resume/stop/delete |
| 26 | `test_run_schedules::test_legacy_stopped_run_can_continue_saved_queue` | AssertionError: 0 != 1 | H2 | LT-C | H1 (36 passed), V10+B (33 passed) | thay `scheduler_tick` ⇒ assignment bằng bước mô phỏng runner gọi claim; giữ nguyên ý đồ pause/resume/stop/delete |
| 27 | `test_run_schedules::test_network_outage_requeues_interrupted_case_without_failure_and_resumes` | IndexError: list index out of range | H2 | LT-C | H1 (36 passed), V10+B (33 passed) | thay `scheduler_tick` ⇒ assignment bằng bước mô phỏng runner gọi claim; giữ nguyên ý đồ pause/resume/stop/delete |
| 28 | `test_run_schedules::test_pause_drain_resize_up_and_down_preserves_same_cases` | AssertionError: 0 != 2 : Pausing must not claim the next pending case. | H2 | LT-C | H1 (36 passed), V10+B (33 passed) | thay `scheduler_tick` ⇒ assignment bằng bước mô phỏng runner gọi claim; giữ nguyên ý đồ pause/resume/stop/delete |
| 29 | `test_run_schedules::test_pause_during_preparation_fences_old_plan` | AssertionError: 0 != 3 | H2 | LT-C | H1 (36 passed), V10+B (33 passed) | thay `scheduler_tick` ⇒ assignment bằng bước mô phỏng runner gọi claim; giữ nguyên ý đồ pause/resume/stop/delete |
| 30 | `test_run_schedules::test_resume_check_failure_keeps_session_paused` | AssertionError: 0 != 2 | H2 | LT-C | H1 (36 passed), V10+B (33 passed) | thay `scheduler_tick` ⇒ assignment bằng bước mô phỏng runner gọi claim; giữ nguyên ý đồ pause/resume/stop/delete |
| 31 | `test_run_schedules::test_stop_cancels_active_jobs_and_retains_history` | AssertionError: 0 != 2 | H2 | LT-C | H1 (36 passed), V10+B (33 passed) | thay `scheduler_tick` ⇒ assignment bằng bước mô phỏng runner gọi claim; giữ nguyên ý đồ pause/resume/stop/delete |
| 32 | `test_run_schedules::test_ui_health_block_prevents_any_new_assignment` | AssertionError: 0 != 2 | H2 | LT-C | H1 (36 passed), V10+B (33 passed) | thay `scheduler_tick` ⇒ assignment bằng bước mô phỏng runner gọi claim; giữ nguyên ý đồ pause/resume/stop/delete |
| 33 | `test_run_schedules::test_unattended_dispatch_worker_cap_completion_and_no_data` | AssertionError: 0 != 2 | H2 | LT-C | H1 (36 passed), V10+B (33 passed) | thay `scheduler_tick` ⇒ assignment bằng bước mô phỏng runner gọi claim; giữ nguyên ý đồ pause/resume/stop/delete |
| 34 | `test_run_schedules::test_dates_validation_and_daily_and_monthly_time_zones` | AssertionError: ValidationError not raised | H2 | LT-D | B3, V10+B | bỏ phần `workerCount=11 → ValidationError`; **các assertion múi giờ R7b phía sau bị che** (chưa chạy) |
| 35 | `test_run_schedules::test_pause_epoch_ownership_and_worker_validation` | AssertionError: ValueError not raised | H2 | LT-D | V10+B | bỏ `resume(count=11) → ValueError`; các assertion sau đó bị che |
| 36 | `test_run_schedules::test_diagnostics_show_stuck_step_and_busy_unselected_worker` | AttributeError: module 'app.run_diagnostics' (app\\run_diagnostics.py) does not have the attribute 'settings' | H2 | LT-E | V10+B | `patch('app.run_diagnostics.settings')` — thuộc tính đã bỏ cùng `read_health` (KI-17) |
| 37 | `test_shared_batch_queue (script)::main` | AssertionError tại :49 — 10 claim đồng thời không trả hết `assigned` | H2 | LT-A | V10+repo, H1 | truyền `max_workers=10` vào `start()` (mặc định repo nay là 1) |

Tổng: LT-A = 14, LT-B = 4, LT-C = 14, LT-D = 2, LT-E = 2, PRE = 1 (cộng 37 mục, gồm 36 pytest + 1 script).

### 3.2 Có sẵn từ B / điều kiện môi trường

| File | Số mục | Lỗi | Nhóm | Ghi chú |
| --- | --- | --- | --- | --- |
| `tests/test_api` | 8 failed | `401 Unauthorized` (test không gắn token) | PRE | Như B; theo Phụ lục A: sửa token hoặc xóa theo D-07 (T12, T18) |
| `tests/test_excel` | 11 error | `module 'app.api.excel' has no attribute '_report_dir'` | PRE | Fixture trỏ vào thuộc tính đã xóa ở `287bfe7` (T12) |
| `tests/test_socketio_flow` | 4 failed | `namespaces failed to connect: /runner` / `/ui` | PRE | Thiếu `engine` và xác thực `/ui`; phủ duy nhất cho vòng CAPTCHA (T12) |
| `verification/test_main_live_workbook`, `test_main_migration`, `test_shared_migration` | 3 collection error | `relation "stored_files"/"annual_records"/"main_reports" does not exist` | MT | Cần DB nguồn legacy (`VAHAN_MIGRATION_SOURCE_DATABASE` / `VAHAN_COMPARE_DEPLOYED_*`); import dữ liệu cũ Excluded (D-25), KI-12. Không đổi so với B |

### 3.3 Web — đỏ từ H1, không phải H2

| # | Test | Lỗi thực tế | Đỏ từ | Nhóm | Nguyên nhân (đối chiếu diff) | Hành động đề xuất |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | `test-schedule-timing.mjs (làm test:platform đỏ)` | `ERR_UNSUPPORTED_RESOLVE_REQUEST: ./services/persistent-state` từ `data:` URL | `dace058` | LT-F | `run-schedules.ts:1` thêm `import {persistentState}` (R7b); test biên dịch module thành `data:` URL nên import tương đối không phân giải được | Đổi cách nạp module trong test (stub `persistentState`) — không đổi code sản phẩm |
| 2 | `test-annual-reports.mjs` | `'' !== '2026'` (select Year) | `3907c2d` | LT-G | Assertion chạy khi `select[aria-label=Year]` còn `Loading years…` (value `''`). Thêm một dòng đợi dữ liệu → **toàn bộ test pass ở H2** (ANN) | Thêm `waitFor` dữ liệu năm trong test |
| 3 | `test-filter-profiles-ui.mjs` | `getByLabel('Report / filter profile')` hidden/disabled, timeout 30 s | `3907c2d` | LT-F | Form lịch thu gọn mặc định (`Show form`); test không bấm nút này (`test-health-page-ui` và `test-run-schedules-ui` đã được cập nhật ở `3907c2d`, file này thì chưa) | Bấm `Show form` trước khi chọn profile |
| 4 | `test-health-page-ui.mjs` | `getByLabel('Active workers').selectOption` timeout | `3907c2d` | LT-F | `<select aria-label="Active workers">` 1–10 đổi thành `<input aria-label="Parallel task limit" type="number">` | **Chờ T16c** (sẽ bỏ ô này) rồi cập nhật một lần |
| 5 | `test-run-schedules-ui.mjs` | `selectOption` element "not visible" (58 lần) | `3907c2d` | LT-F | `Active workers` và `Workers for <profile>` (select) đổi thành input số `Parallel task limit` / `Parallel tasks for <profile>` | **Chờ T16c**; viết lại cùng lúc |
| 6 | `test-account-settings-ui.mjs (ngoài CI)` | `strict mode violation: getByLabel('New password') resolved to 2 elements` | H1 (đỏ ở `dace058`; `AccountSettings.tsx` đổi ở `3907c2d`) | LT-F | Dialog nay có thêm form `Reset password` với ô `New password` cùng nhãn; locator không còn duy nhất | Giới hạn locator theo form; cân nhắc đổi nhãn để hợp a11y (đề xuất nhỏ) |

`test-network-ui` và `test-permissions-ui` xanh ở H2 và H1; `test-batch-timing`, `test-session-ui`, `test-navigation-ui`, `test-update-history-ui` xanh.

## 4. Ứng viên lỗi sản phẩm (đề xuất, chưa ghi vào `defects.md`)

### NSP-1 (đề xuất `DEF-33`) — Preflight của lịch chờ mãi khi số runner idle > `workerCount`

- **Cơ chế (đọc code):** `run_scheduler.prepare_run` gọi `apply_pool(workerCount)` rồi lấy `ready` = **mọi** runner ONLINE, rảnh (`run_scheduler.py:158-161`, không còn lọc theo `worker_number ≤ workerCount` như B), rồi `automatic_preflight(value, runner_ids)` → `preflight` → `reserve_preflight_runners(ids)` → `capacity_available(connection, ids)` đòi `|active ∪ ids| ≤ desiredCount` (`worker_pool.py`). Vi phạm ⇒ `PreflightUnavailable('WORKER_BUSY')` ⇒ HTTP 409 `PREFLIGHT_WAITING`; scheduler coi đây là "chờ" (`preflight_waiting`) và thử lại.
- **Tái hiện F1** (H2 không sửa, 5 runner idle; `apply_pool(limit)` rồi đặt chỗ preflight):

| `desiredCount` | Runner đưa vào preflight | Kết quả |
| --- | --- | --- |
| 1 | 1 | đặt chỗ được |
| 1 | 3 | `WORKER_BUSY` — "The worker limit is in use" |
| 2 | 3 | `WORKER_BUSY` |
| 3 | 3 | đặt chỗ được |
| 3 | 5 | `WORKER_BUSY` |
| 5 | 5 | đặt chỗ được |

- **Kịch bản vận hành:** launcher `auto` tạo N runner (R9b), UI mặc định `workerCount = 1` (`DEFAULT_WORKER_CONCURRENCY = 1`, `run-settings.ts`) ⇒ N > 1 và lịch không bao giờ qua bước "UI Health preflight".
- **Mức tin cậy:** Likely — cơ chế đã tái hiện ở tầng repository (F1) và qua test cô lập B2 (`automatic_preflight`, `PREFLIGHT_WAITING`); **chưa** chạy end-to-end qua `scheduler_tick`/lịch thật (không có test nào ở H2 chạy preflight thật với runner > giới hạn).
- **Đề xuất severity:** Major–Critical tùy việc workaround (đặt `workerCount` ≥ số runner) có chấp nhận được không; **Felix quyết**. T16c (§5.8) vốn đặt giới hạn theo runner thực tế nên có thể giải quyết, nhưng cần test chứng minh N > giới hạn không bị kẹt.
- **Việc cần làm:** (a) dev xác nhận ý đồ; (b) viết test đỏ-trước (N runner idle > limit ⇒ preflight chỉ đặt chỗ cho `limit` runner hoặc không đòi capacity cho preflight); (c) không sửa code khi chưa được duyệt.

### NSP-2 (đề xuất `DEF-34`, Minor) — Thông báo 409 sai nguyên nhân khi hết giới hạn song song

- `PostgresJobRepository.assign` trả `None` cho 4 lý do (runner không connected/bận, **hết capacity**, reservation, reconnecting); `POST /api/jobs` luôn trả `409 "Runner was assigned another job or disconnected."` (`api/jobs.py:117-118`).
- **Bằng chứng:** `test_retry_sessions` 9/12 đỏ với đúng thông báo này, nhưng 12/12 xanh khi pool = 10 (A2) và một test cùng file xanh khi chạy riêng (A0): runner được dùng đủ rảnh và đang connected; nguyên nhân là capacity.
- **Ảnh hưởng:** với mặc định 1 của H2, retry thủ công trong lúc có công việc khác chạy sẽ trả thông báo gây hiểu nhầm. Có ở B nhưng H2 làm nhánh capacity dễ gặp hơn.

## 5. Câu hỏi cho dev / Felix

| # | Câu hỏi | Vì sao cần |
| --- | --- | --- |
| Q1 | `ui_contract.evaluate` nay chỉ giữ `runnerErrors` của runner đang `connected`: một runner lỗi DOM rồi ngắt kết nối sẽ làm mất cờ chặn (gate `blocked=false`). Đây là ý đồ? | Quyết định viết lại `test_disabled_worker_error_…` theo hướng nào, hoặc mở defect |
| Q2 | `prepare_run` cố ý đưa mọi runner idle vào preflight (NSP-1) hay chỉ `workerCount` runner? | NSP-1 |
| Q3 | Assignment bị lỡ (job `ASSIGNED`, runner chưa nhận) nay được phục hồi ở nhánh nào của `claim`? Test `committed_assignment_is_redelivered…` mất đối ứng | Test claim/lease ở T16b(3) |
| Q4 | Nên viết lại web test worker-input trước hay sau T16c? Đề xuất: sau T16c | Tránh viết hai lần |

## 6. Thứ tự sửa test đề xuất (chờ duyệt, chưa làm)

1. **Helper dùng chung** cho test Python: đặt pool (`apply_pool(n)`) trong `setUp` và giải phóng runner/lease cuối test (xử lý LT-A + BF-01 cùng chỗ; T10).
2. **LT-B** (`test_worker_pool`, 4) và **LT-D/LT-E** (4 test): viết lại theo mô hình giới hạn theo số lượng; phần 'ValueError cho 11' đổi thành khẳng định chấp nhận (D-27 = d) hoặc xóa kèm lý do.
3. **LT-C** (14 test `run_schedules`): thêm hàm mô phỏng runner claim (`queue.claim`/endpoint claim) sau `scheduler_tick`; không khôi phục code push-dispatch.
4. **Web:** `filter-profiles-ui`, `annual-reports`, `schedule-timing`, `account-settings-ui` sửa ngay; `health-page-ui`, `run-schedules-ui` đợi T16c.
5. Mọi test sửa phải ghi vào manifest (`test-manifest.json`, T13) với lý do; không skip.

## 7. Giới hạn của phân loại

- Phân loại "lỗi thời" dựa trên (i) đọc assertion, (ii) đối chiếu diff `2bc878e..HEAD`, (iii) chạy lại trên biến thể. Biến thể V10+B khôi phục **cả** `run_scheduler.py` của B và mặc định 10; chưa tách riêng đóng góp từng yếu tố cho 14 test LT-C.
- Xanh trong biến thể không chứng minh hành vi H2 đúng; chỉ chứng minh test không phát hiện lỗi sản phẩm khác. Hành vi runner tự claim (`/api/runner/queue/claim`, vòng poll `runner.mjs`) **chưa có test nào** (T16b(3)).
- A3 (seed cho `queue_retry`) không hợp lệ vì `drop_all` trong `asyncSetUp`; kết luận cho file này dựa vào V10.
- Web: mỗi file chạy riêng một lần; `test:platform` chạy tuần tự dừng ở file đầu tiên đỏ.
- Container `vahan-t16b-pg` vẫn chạy (cổng 55432), các clone `h2`, `h1`, `h1a`, `h2diag`, `h2def10` còn trong scratchpad.


# Đợt 2 — Luồng lịch tự động, phục hồi queue và test

Đã hoàn thành phạm vi sửa code và kiểm tra cục bộ. **66/66 file test PASS**, **285 test case Python PASS**, **0 FAIL, 0 SKIP**; hai smoke script bổ sung PASS và build UI PASS. Bảng theo từng file và log nằm cuối báo cáo; số test case chỉ đếm các bộ có JUnit, không cộng số assertion JavaScript hoặc các script kiểm tra trực tiếp.

Đầu đợt ở commit `64c9fc9` (audit Đợt 1 đã commit/push). Trong lúc làm xuất hiện hai commit UI `8a69713` và `f30b704`; HEAD cuối là `f30b704245ff1502472c250fcec940e091743271` trên nhánh `ocr`. Đã chạy lại toàn bộ platform UI và build trên HEAD cuối cộng các thay đổi Đợt 2 trong working tree. Các thay đổi Đợt 2 hiện chưa commit/push. `final-results.json` lưu SHA256 nguồn test và nguồn thay đổi để nhận diện chính xác bản được kiểm tra. Các file và thư mục cá nhân ngoài phạm vi được giữ nguyên.

## Hành vi sản phẩm đã sửa

| Runner kết nối và còn heartbeat | Hành vi lịch kiểm chứng | Case đồng thời lớn nhất | Kết quả |
| --- | --- | ---: | --- |
| 0 | Chờ runner; không compile plan, không preflight, không áp pool và không giao job | 0 | PASS |
| 1 | Dù lịch cũ có `workerCount=9999`, dùng đúng 1 runner | 1 | 9 case duy nhất hoàn tất, PASS |
| 3 | Dù lịch cũ có `workerCount=9999`, dùng đúng 3 runner | 3 | 9 case duy nhất hoàn tất, PASS |

- `connected_workers()`, `sync_worker_capacity()`, `prepare_run()` và `dispatch_run()` trong [run_scheduler.py](../../apps/api-server/app/run_scheduler.py) lấy năng lực từ runner còn heartbeat. Preflight kiểm những runner thực tế được chọn, queue tự điều chỉnh khi kết nối thay đổi. Assignment cũ được drain/recover; không viết lại case hay ranh giới checkpoint khi giảm năng lực.
- `live_worker()` trong [worker_pool.py](../../apps/api-server/app/worker_pool.py) loại runner reconnecting và heartbeat quá hạn. `BatchQueueRepository.claim()` cùng `set_worker_limit()` trong [batch_queue.py](../../apps/api-server/app/repositories/batch_queue.py) giới hạn queue lịch bằng số runner còn hoạt động; không tin cờ SQL `connected=True` khi heartbeat đã hết hạn.
- [AutomaticRunSettings.tsx](../../apps/web-ui/src/components/AutomaticRunSettings.tsx), [api-client.ts](../../apps/web-ui/src/services/api-client.ts) và [run-schedules.ts](../../apps/web-ui/src/run-schedules.ts) bỏ điều khiển số worker khỏi cả create/resume. Test khẳng định form và card lịch không còn ô nhập số worker ở mọi trạng thái. Model [run_schedule.py](../../apps/api-server/app/models/run_schedule.py) nhận tương thích request cũ nhưng loại bỏ giá trị; repository không lưu count mới, không trả count cũ cho UI và bỏ count khi resume. Queue cũ được chuyển về năng lực tự động.
- `_settle()` trong [batch_queue.py](../../apps/api-server/app/repositories/batch_queue.py) khóa job trước khi quyết định lease hết hạn; kết quả đã commit thắng tình huống expiry cạnh tranh. `claim()` thống nhất thứ tự khóa job trước runner và đánh giá expiry trước trả assignment recovered.
- `_change()` trong [postgres.py](../../apps/api-server/app/repositories/postgres.py) chỉ release runner khi lần đầu chuyển sang terminal; ACK terminal gửi muộn không giữ khóa runner của case mới. `_expire_disconnected_runner()` trong [runner_events.py](../../apps/api-server/app/realtime/runner_events.py) không emit payload rỗng khi trạng thái đã được giao dịch kết quả chốt.

Code hiện tại dùng PostgreSQL task claims sau migration 0014. Ghi nhớ Redis của các đợt trước đã được đối chiếu lại và không dùng làm bằng chứng kiến trúc hiện tại.

## Kiểm chứng phục hồi và tính duy nhất

| Tình huống | Bằng chứng và kết quả |
| --- | --- |
| Worker cùng lấy việc | `test_queue_recovery.py`: 12 poll cạnh tranh từ 3 worker qua 27 case; 27 job và 27 lịch sử SQL, ACK trùng không tăng số dòng. PASS |
| Lease hết hạn, socket mất hoặc cờ connected còn true | Tạo attempt mới cho đúng case, filters và retryOf; kết quả NO_DATA muộn qua HTTP bị 409, workbook muộn bị từ chối; chỉ kết quả attempt mới vào lịch sử. PASS |
| Commit kết quả cạnh tranh expiry | Expiry chờ khóa job, đọc lại terminal đã commit, không tạo retry hoặc deadlock. PASS |
| ACK terminal cũ trong lúc runner bị khóa | ACK hoàn thành và runner vẫn giữ jobId case mới. PASS |
| API restart | Subprocess Uvicorn thật, readiness có DB migration head: 3 client Socket.IO/HTTP, kill process rồi restart, reconnect nhận đúng jobId cũ, duplicate result, pause/drain/resume, 9/9 case duy nhất và attempts=1. PASS |
| Pause/resume, đổi số runner thực tế | Bộ lịch 39/39; giữ sessionId/case/progress; tăng/giảm số runner không lấy lại count lưu cũ. PASS |
| Mất mạng | Queue không giao việc khi offline; case bị ngắt trở về pending không tăng failure; tự resume sau phục hồi; pause thủ công không bị auto resume. Network monitor yêu cầu hai probe khỏe. PASS |
| Tải và checkpoint | 1.600 case duy nhất, 10 worker, mỗi worker 160 claim; complete SQL và thứ tự checkpoint PASS trong 135,5 giây. Bộ retry/checkpoint 5/5 PASS. |
| UI smoke hiện hành | Browser đăng nhập, socket dùng token, runner source new/Playwright, nhận jobId và hiển thị tiến trình; hủy đúng job fixture sau kiểm tra. PASS trong lifecycle test. |

## Migration DB 0012 → 0014 lên và xuống

`verification/test_queue_migrations.py`: **2/2 PASS** trên PostgreSQL thật, gồm DB trống và DB có dữ liệu. Chạy `0012 → 0013 → 0014 → 0013 → 0012 → 0014` qua subprocess Alembic.

- 0013 tạo outbox cho đúng task PENDING/PROCESSING của session RUNNING; không enqueue session PAUSED hoặc task terminal. 0014 bỏ outbox; downgrade 0014 khôi phục đúng outbox.
- Giữ nguyên user, auth session, report session, filters/task state, attempts/failures, jobId/payload và settings cũ ở mỗi chiều.
- Khi hạ xuống 0012, cap 27 được clamp về 10 và constraint/default 10 được phục hồi đúng thiết kế cũ. Đây là thay đổi cap dự kiến, không mất case/job.
- Kiểm migration báo cáo cũ trên fixture **tổng hợp có dữ liệu**, 3 manufacturer/30 ô tháng/1 lịch sử: main migration giữ giá trị, ngày và nguồn; shared migration chuẩn hóa scope và filters, giữ dữ liệu; replay workbook không thêm dòng trùng hoặc bản sao SQL file. Không phải workbook sản xuất lịch sử. Log replay vẫn có nhãn `realCase` cũ của script; fixture được tạo tổng hợp.

## Phân biệt test lỗi thời, lỗi sản phẩm và môi trường

| Nhóm | Nguyên nhân và cách xử lý |
| --- | --- |
| Lỗi sản phẩm | Lịch áp `workerCount` cũ; lease bị giữ vô hạn bởi connected=true; race expiry/kết quả và thứ tự khóa job/runner; ACK terminal chạm runner case mới. Sửa code và thêm kiểm tra cạnh tranh, HTTP, restart và dữ liệu SQL. |
| Test lỗi thời | Filter `maxCases` không còn là giới hạn; UI year lấy từ profile; quyền member redirect khi load trang và deny khi hash navigation; schedule create/resume dùng runner tự động; smoke cần auth và runner engine hiện hành. Cập nhật assertion theo hành vi mới, vẫn kiểm SQL/UI/authorization. |
| Fixture thiếu hoặc sai | Mock preflight dùng mã PASS hết hạn sau 5 phút: tạo gate fresh mỗi lần check. Case dài thiếu heartbeat: fixture worker gửi heartbeat như runner thật. Test upload thiếu user khi chạy riêng: khai báo fixture admin trực tiếp, đã pass 8/8 trên DB hoàn toàn mới. Migration/workbook cũ thiếu fixture: tạo dữ liệu tổng hợp không rỗng và kiểm dữ liệu trước/sau. |
| Gián đoạn môi trường | Container test đầu tiên không còn tồn tại ở cuối lượt rộng; 3 worker-pool case báo ConnectionRefused, maker smoke chưa khởi chạy. Dựng container riêng mới; worker pool 7/7 và maker smoke PASS. Giữ log thất bại ban đầu trong `results.json`; kết quả chạy lại xác minh trong `final-results.json`. |

Không thêm skip/xfail hoặc giảm điều kiện kiểm để lấy bảng xanh. JUnit các lượt cuối có 0 failures/errors/skipped. Log cũ được giữ để đối chiếu, không dùng log một lượt FAIL làm kết quả cuối.

## Phạm vi môi trường và cách chạy lại

Windows/Python 3.12/Node 24, PostgreSQL 17 riêng trên localhost:55433, DB có hậu tố `_test`; migration phá schema chỉ cho DB guard `vahan_migration_*_test`. API lifecycle là process/HTTP/Socket.IO thật với worker protocol fixture. Platform UI dùng Chromium với fixture backend; network outage/probe được mô phỏng có kiểm SQL. Hai test live DOM tools kiểm VAHAN nhưng dừng trước CAPTCHA/Apply. Chưa thực hiện acceptance đầy đủ OCR/Apply với 1/3 browser VAHAN thật, và không coi build hoặc fixture là bằng chứng đó. Stack ứng dụng đang chạy không được restart/deploy trong đợt này. Sau khi các lượt cuối hoàn tất, đã dọn container test riêng `codex-round2-db-20261012`; API/web/3 runner/PostgreSQL của stack ứng dụng vẫn báo healthy khi kiểm tra cuối.

Đặt `DATABASE_URL` và cấu hình auth/runner cho PostgreSQL disposable, `VAHAN_ENVIRONMENT=test`, `VAHAN_ALLOW_DATABASE_CLEAR=test-only`; `VAHAN_RESULT_TEST_DATABASE` là tên DB tương ứng. Các verification có guard riêng đọc biến môi trường trong đầu file. Không chạy bằng URL DB sản xuất.

```powershell
# Từ apps/api-server, trên DB test đã migrate
.venv/Scripts/python.exe -m app.migrate
.venv/Scripts/python.exe -m pytest tests --tb=short
.venv/Scripts/python.exe -m pytest verification/test_run_schedules.py --tb=short
.venv/Scripts/python.exe -m pytest verification/test_queue_retry_checkpoints.py --tb=short
.venv/Scripts/python.exe -m pytest verification/test_worker_lifecycle.py --tb=short
# Migration dùng DB vahan_migration_*_test và VAHAN_QUEUE_MIGRATION_TEST_DATABASE
.venv/Scripts/python.exe -m pytest verification/test_queue_migrations.py --tb=short
# Các verification khác chạy từng file với DB fixture riêng như log command đã lưu

# Từ apps/web-ui
npm.cmd run test:platform
node scripts/test-artifact-path.mjs
npm.cmd run build
```

Để kiểm historical migration có dữ liệu, dùng `verification/prepare_report_test_fixtures.py` với PostgreSQL disposable và `VAHAN_FIXTURE_POSTGRES_CONTAINER` của container riêng. Script từ chối tên DB không phải test và DB fixture đã tồn tại. Các biến nguồn/đích cụ thể nằm ở guard đầu từng test và log setup.

## Kết quả cuối theo từng file

| File | Trạng thái | Test case Python | Log |
| --- | --- | ---: | --- |
| `apps/api-server/scripts/test-user-state-codec.py` | PASS | — | [apps__api-server__scripts__test-user-state-codec.py.log](apps__api-server__scripts__test-user-state-codec.py.log) |
| `apps/api-server/tests/test_api.py` | PASS | 15 | [api-core-verified.log](api-core-verified.log) |
| `apps/api-server/tests/test_excel.py` | PASS | 13 | [api-core-verified.log](api-core-verified.log) |
| `apps/api-server/tests/test_queue_recovery.py` | PASS | 6 | [api-core-verified.log](api-core-verified.log) |
| `apps/api-server/tests/test_report_history.py` | PASS | 2 | [api-core-verified.log](api-core-verified.log) |
| `apps/api-server/tests/test_repositories.py` | PASS | 6 | [api-core-verified.log](api-core-verified.log) |
| `apps/api-server/tests/test_runner_queue.py` | PASS | 3 | [api-core-verified.log](api-core-verified.log) |
| `apps/api-server/tests/test_schedule_capacity_api.py` | PASS | 2 | [api-core-verified.log](api-core-verified.log) |
| `apps/api-server/tests/test_socketio_flow.py` | PASS | 3 | [api-core-verified.log](api-core-verified.log) |
| `apps/api-server/tests/test_ui_health_logs.py` | PASS | 5 | [api-core-verified.log](api-core-verified.log) |
| `apps/api-server/tests/test_upload_limits.py` | PASS | 8 | [api-core-verified.log](api-core-verified.log) |
| `apps/api-server/verification/test_account_passwords.py` | PASS | 7 | [apps__api-server__verification__test_account_passwords.py.log](apps__api-server__verification__test_account_passwords.py.log) |
| `apps/api-server/verification/test_annual_reports.py` | PASS | 18 | [apps__api-server__verification__test_annual_reports.py.log](apps__api-server__verification__test_annual_reports.py.log) |
| `apps/api-server/verification/test_captcha_ephemeral.py` | PASS | 8 | [apps__api-server__verification__test_captcha_ephemeral.py.log](apps__api-server__verification__test_captcha_ephemeral.py.log) |
| `apps/api-server/verification/test_captcha_refresh_race.py` | PASS | 5 | [apps__api-server__verification__test_captcha_refresh_race.py.log](apps__api-server__verification__test_captcha_refresh_race.py.log) |
| `apps/api-server/verification/test_filter_profiles.py` | PASS | 8 | [apps__api-server__verification__test_filter_profiles.py.log](apps__api-server__verification__test_filter_profiles.py.log) |
| `apps/api-server/verification/test_main_live_workbook.py` | PASS | — | [legacy-workbook-replay.log](legacy-workbook-replay.log) |
| `apps/api-server/verification/test_main_migration.py` | PASS | — | [legacy-main-migration.log](legacy-main-migration.log) |
| `apps/api-server/verification/test_ocr_platform.py` | PASS | 6 | [apps__api-server__verification__test_ocr_platform.py.log](apps__api-server__verification__test_ocr_platform.py.log) |
| `apps/api-server/verification/test_permissions.py` | PASS | 5 | [apps__api-server__verification__test_permissions.py.log](apps__api-server__verification__test_permissions.py.log) |
| `apps/api-server/verification/test_production_config.py` | PASS | 15 | [apps__api-server__verification__test_production_config.py.log](apps__api-server__verification__test_production_config.py.log) |
| `apps/api-server/verification/test_queue_migrations.py` | PASS | 2 | [apps__api-server__verification__test_queue_migrations.py.log](apps__api-server__verification__test_queue_migrations.py.log) |
| `apps/api-server/verification/test_queue_retry_checkpoints.py` | PASS | 5 | [retry-checkpoints-final.log](retry-checkpoints-final.log) |
| `apps/api-server/verification/test_report_coverage.py` | PASS | 8 | [apps__api-server__verification__test_report_coverage.py.log](apps__api-server__verification__test_report_coverage.py.log) |
| `apps/api-server/verification/test_report_results.py` | PASS | 22 | [apps__api-server__verification__test_report_results.py.log](apps__api-server__verification__test_report_results.py.log) |
| `apps/api-server/verification/test_retry_sessions.py` | PASS | 12 | [apps__api-server__verification__test_retry_sessions.py.log](apps__api-server__verification__test_retry_sessions.py.log) |
| `apps/api-server/verification/test_run_controls.py` | PASS | 5 | [apps__api-server__verification__test_run_controls.py.log](apps__api-server__verification__test_run_controls.py.log) |
| `apps/api-server/verification/test_run_history.py` | PASS | 7 | [apps__api-server__verification__test_run_history.py.log](apps__api-server__verification__test_run_history.py.log) |
| `apps/api-server/verification/test_run_schedules.py` | PASS | 39 | [apps__api-server__verification__test_run_schedules.py.log](apps__api-server__verification__test_run_schedules.py.log) |
| `apps/api-server/verification/test_session_limits.py` | PASS | 8 | [apps__api-server__verification__test_session_limits.py.log](apps__api-server__verification__test_session_limits.py.log) |
| `apps/api-server/verification/test_shared_batch_queue.py` | PASS | — | [apps__api-server__verification__test_shared_batch_queue.py.log](apps__api-server__verification__test_shared_batch_queue.py.log) |
| `apps/api-server/verification/test_shared_migration.py` | PASS | — | [legacy-shared-migration-final.log](legacy-shared-migration-final.log) |
| `apps/api-server/verification/test_ui_contract.py` | PASS | 11 | [apps__api-server__verification__test_ui_contract.py.log](apps__api-server__verification__test_ui_contract.py.log) |
| `apps/api-server/verification/test_update_status.py` | PASS | 3 | [apps__api-server__verification__test_update_status.py.log](apps__api-server__verification__test_update_status.py.log) |
| `apps/api-server/verification/test_worker_lifecycle.py` | PASS | 2 | [apps__api-server__verification__test_worker_lifecycle.py.log](apps__api-server__verification__test_worker_lifecycle.py.log) |
| `apps/api-server/verification/test_worker_pool.py` | PASS | 7 | [worker-pool-final.log](worker-pool-final.log) |
| `apps/browser-runner/test-filter-fill.mjs` | PASS | — | [apps__browser-runner__test-filter-fill.mjs.log](apps__browser-runner__test-filter-fill.mjs.log) |
| `apps/browser-runner/test-health-navigation.mjs` | PASS | — | [apps__browser-runner__test-health-navigation.mjs.log](apps__browser-runner__test-health-navigation.mjs.log) |
| `apps/browser-runner/test-health-trigger.mjs` | PASS | — | [apps__browser-runner__test-health-trigger.mjs.log](apps__browser-runner__test-health-trigger.mjs.log) |
| `apps/browser-runner/test-image-pipe.mjs` | PASS | — | [apps__browser-runner__test-image-pipe.mjs.log](apps__browser-runner__test-image-pipe.mjs.log) |
| `apps/browser-runner/test-job-lifecycle.mjs` | PASS | — | [apps__browser-runner__test-job-lifecycle.mjs.log](apps__browser-runner__test-job-lifecycle.mjs.log) |
| `apps/browser-runner/test-main-report-save.mjs` | PASS | — | [apps__browser-runner__test-main-report-save.mjs.log](apps__browser-runner__test-main-report-save.mjs.log) |
| `apps/browser-runner/test-navigation.mjs` | PASS | — | [apps__browser-runner__test-navigation.mjs.log](apps__browser-runner__test-navigation.mjs.log) |
| `apps/browser-runner/test-options.mjs` | PASS | — | [apps__browser-runner__test-options.mjs.log](apps__browser-runner__test-options.mjs.log) |
| `apps/browser-runner/test-page-recovery.mjs` | PASS | — | [apps__browser-runner__test-page-recovery.mjs.log](apps__browser-runner__test-page-recovery.mjs.log) |
| `apps/browser-runner/test-profile-options.mjs` | PASS | — | [apps__browser-runner__test-profile-options.mjs.log](apps__browser-runner__test-profile-options.mjs.log) |
| `apps/browser-runner/test-results.mjs` | PASS | — | [apps__browser-runner__test-results.mjs.log](apps__browser-runner__test-results.mjs.log) |
| `apps/browser-runner/test-ui-health-contract.mjs` | PASS | — | [apps__browser-runner__test-ui-health-contract.mjs.log](apps__browser-runner__test-ui-health-contract.mjs.log) |
| `apps/web-ui/scripts/test-account-settings-ui.mjs` | PASS | — | [ui-platform-final.log](ui-platform-final.log) |
| `apps/web-ui/scripts/test-annual-reports.mjs` | PASS | — | [ui-platform-final.log](ui-platform-final.log) |
| `apps/web-ui/scripts/test-artifact-path.mjs` | PASS | — | [ui-artifact-path.log](ui-artifact-path.log) |
| `apps/web-ui/scripts/test-batch-timing.mjs` | PASS | — | [ui-platform-final.log](ui-platform-final.log) |
| `apps/web-ui/scripts/test-filter-profiles-ui.mjs` | PASS | — | [ui-platform-final.log](ui-platform-final.log) |
| `apps/web-ui/scripts/test-health-page-ui.mjs` | PASS | — | [ui-platform-final.log](ui-platform-final.log) |
| `apps/web-ui/scripts/test-navigation-ui.mjs` | PASS | — | [ui-platform-final.log](ui-platform-final.log) |
| `apps/web-ui/scripts/test-network-ui.mjs` | PASS | — | [ui-platform-final.log](ui-platform-final.log) |
| `apps/web-ui/scripts/test-permissions-ui.mjs` | PASS | — | [ui-platform-final.log](ui-platform-final.log) |
| `apps/web-ui/scripts/test-platform.mjs` | PASS | — | [ui-platform-final.log](ui-platform-final.log) |
| `apps/web-ui/scripts/test-run-schedules-ui.mjs` | PASS | — | [ui-platform-final.log](ui-platform-final.log) |
| `apps/web-ui/scripts/test-schedule-timing.mjs` | PASS | — | [ui-platform-final.log](ui-platform-final.log) |
| `apps/web-ui/scripts/test-session-ui.mjs` | PASS | — | [ui-platform-final.log](ui-platform-final.log) |
| `apps/web-ui/scripts/test-update-history-ui.mjs` | PASS | — | [ui-platform-final.log](ui-platform-final.log) |
| `scripts/test_deployment_guard.py` | PASS | 12 | [scripts__test_deployment_guard.py.log](scripts__test_deployment_guard.py.log) |
| `scripts/test_worker_capacity.py` | PASS | 7 | [scripts__test_worker_capacity.py.log](scripts__test_worker_capacity.py.log) |
| `tools/ui-drift-guard/test_ui_contract.py` | PASS | — | [tools__ui-drift-guard__test_ui_contract.py.log](tools__ui-drift-guard__test_ui_contract.py.log) |
| `tools/ui-drift-guard/test_ui_diagnostics.py` | PASS | — | [tools__ui-drift-guard__test_ui_diagnostics.py.log](tools__ui-drift-guard__test_ui_diagnostics.py.log) |

Hai smoke bổ sung: [maker-smoke-final.log](maker-smoke-final.log), [worker lifecycle/UI smoke](apps__api-server__verification__test_worker_lifecycle.py.log). Build: [web-build-final.log](web-build-final.log). Kiểm tra độc lập upload: [cold-upload.log](cold-upload.log). Dữ liệu tổng hợp kết quả: [final-results.json](final-results.json); lịch sử lần chạy đầu: [results.json](results.json).

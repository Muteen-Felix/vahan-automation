**Đợt 1 — Trạng thái code ngày 12/10/2026, commit `3ecce961fc345d167e6979b5136d4a79cd642995`.**

Bắt đầu tại c5f69c8 với working tree sạch. Trong lúc chạy xuất hiện commit 3ecce961 về giao diện đăng nhập. Đã chạy lại toàn bộ 14 file test UI và build trên git archive chính xác 3ecce961 (SHA trong ZIP comment). API, runner, scripts, tools và tất cả file test không đổi giữa hai commit; kết quả phần đó được giữ nguyên. GitHub trả HTTP 502 khi kiểm tra remote, nên đây là commit local mới nhất được kiểm chứng.

Đã thực thi đủ 62 file test có trong Git: **55 PASS**, **5 FAIL**, **2 BLOCKED (fixture)**. Thêm hai smoke script: maker_update_smoke.py PASS; smoke-ui.mjs FAIL do giao thức xác thực cũ. Không sửa source/test gốc, không restart stack đang chạy.

Môi trường: Windows, Python 3.12, Node 24.19.0, Chromium 153.0.8010.12 / Playwright 1.63.0. PostgreSQL 17.7 là container riêng `vahan-round1-c5f69c8-db`, port 55433, toàn bộ database có hậu tố _test. UI kiểm tra bằng Vite từ snapshot source; API test qua ASGI/Socket.IO và SQL riêng. Không coi UI fixture hoặc build là bằng chứng end-to-end OCR/Apply trên VAHAN thật. Live smoke DOM tools/ui-drift-guard/test_ui_contract.py đã PASS, dừng trước CAPTCHA/Apply.

**Vì sao `blocked` biến mất khi runner ngắt kết nối?**

`current()` trong [apps/api-server/app/repositories/ui_contract.py](../../apps/api-server/app/repositories/ui_contract.py) lấy connected_ids từ SQL, rồi chỉ dùng runnerErrors của các ID đó để tính active_errors và blocked. `evaluate()` dùng cùng phép lọc khi ghi state. `disconnect()` / `_expire_disconnected_runner()` trong [apps/api-server/app/realtime/runner_events.py](../../apps/api-server/app/realtime/runner_events.py) chuyển runner sang RECONNECTING trước; sau grace mặc định 30 giây, `remove_by_socket()` trong [apps/api-server/app/repositories/postgres.py](../../apps/api-server/app/repositories/postgres.py) ghi connected=False. Trong grace, SQL connected vẫn True nên blocked vẫn True. Sau offline, nếu không còn runner kết nối có lỗi, current() trả blocked=False và lastError=None; runnerErrors vẫn được giữ.

Probe: true trước disconnect → true trong grace → false sau offline; chẩn đoán vẫn tồn tại; reconnect cùng ID → true; PASS mới từ runner đó mới xóa lỗi của nó. Gate PASS cũ cho runner khỏe vẫn được chấp nhận nếu đáp ứng phiên bản/thời hạn và không bị preflight BLOCKED mới hơn thay thế. Vì vậy false không chứng minh DOM của runner lỗi đã được sửa.

`refreshHealth()` trong [apps/web-ui/src/App.tsx](../../apps/web-ui/src/App.tsx) và `websiteCheckBlocked()` trong [apps/web-ui/src/ui-health-alerts.ts](../../apps/web-ui/src/ui-health-alerts.ts) còn kiểm tra latestPreflight.status === BLOCKED. Nếu latestPreflight vẫn BLOCKED, cảnh báo UI có thể còn hiển thị dù cờ blocked=False. Hành vi loại runner offline khỏi blocked đã được test `test_disconnected_worker_error_is_retained_and_reconnect_requires_check` kiểm tra rõ; không phải state bị xóa do lỗi React.

**Vì sao preflight chọn nhiều runner hơn giới hạn lịch?**

`prepare_run()` trong [apps/api-server/app/run_scheduler.py](../../apps/api-server/app/run_scheduler.py) gọi apply_pool(workerCount), nhưng tạo ready từ toàn bộ runner source=new, ONLINE, không có current_job_id; runner_ids không cắt theo workerCount. `worker_enabled()` trong [apps/api-server/app/worker_pool.py](../../apps/api-server/app/worker_pool.py) chỉ yêu cầu ID có giá trị và count >= 1; đây là giới hạn đồng thời, không phải danh sách N runner được bật. `dispatch_run()` cũng dùng toàn bộ ONLINE/BUSY để kiểm tra gate.

`automatic_preflight()` gọi `preflight()` trong [apps/api-server/app/api/ui_health.py](../../apps/api-server/app/api/ui_health.py) cho mọi ID, nhưng Semaphore(min(2, concurrency)) và `reserve_preflight_runners()` trong [apps/api-server/app/repositories/filter_profiles.py](../../apps/api-server/app/repositories/filter_profiles.py) giữ số planning lease đang sử dụng dưới giới hạn. Khi giao task, `BatchQueueRepository.claim()` kiểm tra max_workers của session và capacity_available() của pool.

Probe thực tế: workerCount=1, preflight ba runner, peak planning lease=1, queueMaxWorkers=1, lịch RUNNING. Test `test_automatic_preflight_records_all_selected_workers_without_ui` kiểm tra đúng chính sách này. Đây không phải bằng chứng job vượt concurrency. Tuy nhiên, runner dư có DOM lỗi/không đáp ứng có thể làm lịch nhỏ phải chờ hoặc bị chặn; nếu yêu cầu nghiệp vụ chỉ kiểm tra N runner thì cần đổi chính sách chọn runner ở sản phẩm, không chỉ sửa test.

**Job đã giao nhưng worker mất kết nối được lấy lại ở đâu?**

`_expire_disconnected_runner()` đánh FAILED job sau grace nếu kết nối không trở lại. Với task queue, `BatchQueueRepository._settle()` trong [apps/api-server/app/repositories/batch_queue.py](../../apps/api-server/app/repositories/batch_queue.py) cũng tự phát hiện job chưa terminal: runner mất khỏi SQL, hoặc connected=False và heartbeat cũ hơn grace+15 giây (mặc định 45 giây). Nó ghi FAILED với event worker-lease-expired, release runner, tăng failures và đưa task về PENDING nếu chưa hết lượt retry. Nếu connected=True, nhánh này không hết hạn chỉ vì heartbeat cũ.

`snapshot()`, `settle()` và `claim()` gọi _settle(); `dispatch_run()` gọi snapshot để hòa giải state ngay cả khi dashboard không mở. Đây là phục hồi khi đọc/claim, không phải một Redis sweeper. Worker `consumeQueue()` trong [apps/browser-runner/runner.mjs](../../apps/browser-runner/runner.mjs) tự poll `/api/runner/queue/claim`; `claim_queue_task()` trong [apps/api-server/app/api/batch_queue.py](../../apps/api-server/app/api/batch_queue.py) yêu cầu gate rồi gọi queue.claim(). Claim tạo Job mới từ filters SQL, giữ caseId và retryOfJobId, theo checkpoint/final retry policy. MAX_FAILURES=2 cho vòng đầu/checkpoint; final pass xử lý lượt cuối theo finalTargets.

Probe: job cũ FAILED → task PENDING/failures=1 → worker khác nhận jobId mới, cùng caseId/filters. Nếu chỉ mất response claim và cùng runner vẫn sở hữu job, claim trả lại jobId cũ với recovered=True để không giao trùng. `recover_after_restart()` trong postgres.py giữ các job thuộc task PROCESSING để queue phục hồi; job trực tiếp ngoài queue bị FAILED và cần retry rõ ràng. Code commit hiện tại dùng PostgreSQL claims, không dùng XAUTOCLAIM; Redis container còn chạy không chứng minh source hiện tại dùng Redis.

**Phân loại kết quả lỗi.**

- Test lỗi thời: maxCases=2 phải raise; selector Report year trên form lịch; mong deny sau tải lại pathname dành cho member; smoke-ui.mjs thiếu engine=playwright và token UI. test-platform.mjs fail theo file con và không đại diện một lỗi độc lập.
- Fixture thiếu tính độc lập: test_upload_limits.py chạy riêng thất bại ba case vì chưa tạo test-admin. Suite CI đầy đủ pass cả tám case; cần bổ sung fixture, không quy lỗi cho kiểm tra kích thước Excel.
- Fixture phụ thuộc thời gian: test_run_schedules.py có 35 pass/1 fail ở test_headless_checkpoints_final_sweep_and_resume_recover_all_failures. asyncSetUp() tạo gate một lần; automatic_preflight bị mock luôn trả cùng ID. Gate thật có TTL 5 phút khi fresh=True; test chạy chậm vượt TTL rồi resume báo UI_PREFLIGHT_REQUIRED. Bản diagnostic chạy nguyên các assertion hoàn tất ở tick 21, 23 case, retry DONE. Kết quả này hỗ trợ nguyên nhân fixture/gate cũ, không chứng minh toàn bộ môi trường production đã được kiểm thử.
- Thiếu đầu vào: test_main_migration.py cần schema/snapshot annual_records cũ; test_main_live_workbook.py cần workbook Port Blair lịch sử. Các script đã được chạy và exit 1 trước phần xác minh. test_shared_migration.py pass trên 0 dòng, chưa phải bằng chứng bảo toàn dữ liệu thật.
- Quan sát bổ sung chưa kết luận sản phẩm: bản sao test filter với selector mới có lượt pass, rồi có lượt vấp assert forceBusy khi request options còn đang chuyển trạng thái. Mock dùng một cờ toàn cục thay đổi trước reload; chưa đủ để quy là API giao việc cho runner bận. Source API vẫn khóa và kiểm tra lease/capacity; cần ổn định fixture và theo dõi request đang bay khi sửa test.

Không có lỗi vượt concurrency hoặc mất task được tái hiện trong các kiểm tra đã hoàn tất. Hai chính sách cần quyết định ở sản phẩm là tính blocked chỉ trên runner còn kết nối và preflight toàn bộ pool: test hiện tại đang xác nhận chúng, không kiểm tra một chính sách chặn toàn cục bền vững hoặc chọn đúng N runner.

**Kết quả theo từng file.**

PASS/FAIL là kết quả chạy test gốc; BLOCKED (fixture) giữ exit code lỗi nhưng tách khỏi lỗi sản phẩm. Cột P/F/E/S là pass/fail/error/skip đối với pytest; dấu — là script tự assert, không phải không chạy. Test copy dùng để chẩn đoán không được tính thay cho test gốc.

| File | Kết quả | P/F/E/S | Log | Ghi chú |
|---|---|---|---|---|
| `apps/api-server/scripts/test-user-state-codec.py` | PASS | — | [apps__api-server__scripts__test-user-state-codec.py.log](apps__api-server__scripts__test-user-state-codec.py.log) |  |
| `apps/api-server/tests/test_api.py` | PASS | 15/0/0/0 | [api-full-suite.log](api-full-suite.log) |  |
| `apps/api-server/tests/test_excel.py` | PASS | 13/0/0/0 | [api-full-suite.log](api-full-suite.log) |  |
| `apps/api-server/tests/test_report_history.py` | PASS | 2/0/0/0 | [api-full-suite.log](api-full-suite.log) |  |
| `apps/api-server/tests/test_repositories.py` | PASS | 6/0/0/0 | [api-full-suite.log](api-full-suite.log) |  |
| `apps/api-server/tests/test_runner_queue.py` | PASS | 3/0/0/0 | [api-full-suite.log](api-full-suite.log) |  |
| `apps/api-server/tests/test_socketio_flow.py` | PASS | 3/0/0/0 | [api-full-suite.log](api-full-suite.log) |  |
| `apps/api-server/tests/test_ui_health_logs.py` | PASS | 5/0/0/0 | [api-full-suite.log](api-full-suite.log) |  |
| `apps/api-server/tests/test_upload_limits.py` | PASS | 8/0/0/0 | [api-full-suite.log](api-full-suite.log) | 8 pass trong suite; chạy riêng database sạch: 3 fail vì chưa tạo test-admin (fixture phụ thuộc thứ tự). |
| `apps/api-server/verification/test_account_passwords.py` | PASS | 7/0/0/0 | [apps__api-server__verification__test_account_passwords.py.log](apps__api-server__verification__test_account_passwords.py.log) |  |
| `apps/api-server/verification/test_annual_reports.py` | PASS | 18/0/0/0 | [apps__api-server__verification__test_annual_reports.py.log](apps__api-server__verification__test_annual_reports.py.log) |  |
| `apps/api-server/verification/test_captcha_ephemeral.py` | PASS | 8/0/0/0 | [apps__api-server__verification__test_captcha_ephemeral.py.log](apps__api-server__verification__test_captcha_ephemeral.py.log) |  |
| `apps/api-server/verification/test_captcha_refresh_race.py` | PASS | 5/0/0/0 | [apps__api-server__verification__test_captcha_refresh_race.py.log](apps__api-server__verification__test_captcha_refresh_race.py.log) |  |
| `apps/api-server/verification/test_filter_profiles.py` | FAIL | 7/1/0/0 | [apps__api-server__verification__test_filter_profiles.py.log](apps__api-server__verification__test_filter_profiles.py.log) | 7 pass, 1 fail: kỳ vọng maxCases=2 phải raise; commit c5f69c8 chủ động bỏ giới hạn. |
| `apps/api-server/verification/test_main_live_workbook.py` | BLOCKED (fixture) | — | [apps__api-server__verification__test_main_live_workbook.py.log](apps__api-server__verification__test_main_live_workbook.py.log) | Exit 1: thiếu workbook Port Blair lịch sử trong stored_files; NoResultFound trước khi replay. |
| `apps/api-server/verification/test_main_migration.py` | BLOCKED (fixture) | — | [apps__api-server__verification__test_main_migration.py.log](apps__api-server__verification__test_main_migration.py.log) | Exit 1: thiếu snapshot trước migration với annual_records/annual_datasets; không chứng minh migration lỗi. |
| `apps/api-server/verification/test_ocr_platform.py` | PASS | 6/0/0/0 | [apps__api-server__verification__test_ocr_platform.py.log](apps__api-server__verification__test_ocr_platform.py.log) |  |
| `apps/api-server/verification/test_permissions.py` | PASS | 5/0/0/0 | [apps__api-server__verification__test_permissions.py.log](apps__api-server__verification__test_permissions.py.log) |  |
| `apps/api-server/verification/test_production_config.py` | PASS | 15/0/0/0 | [apps__api-server__verification__test_production_config.py.log](apps__api-server__verification__test_production_config.py.log) |  |
| `apps/api-server/verification/test_queue_retry_checkpoints.py` | PASS | 5/0/0/0 | [apps__api-server__verification__test_queue_retry_checkpoints.py.log](apps__api-server__verification__test_queue_retry_checkpoints.py.log) |  |
| `apps/api-server/verification/test_report_coverage.py` | PASS | 8/0/0/0 | [apps__api-server__verification__test_report_coverage.py.log](apps__api-server__verification__test_report_coverage.py.log) |  |
| `apps/api-server/verification/test_report_results.py` | PASS | 22/0/0/0 | [apps__api-server__verification__test_report_results.py.log](apps__api-server__verification__test_report_results.py.log) |  |
| `apps/api-server/verification/test_retry_sessions.py` | PASS | 12/0/0/0 | [apps__api-server__verification__test_retry_sessions.py.log](apps__api-server__verification__test_retry_sessions.py.log) |  |
| `apps/api-server/verification/test_run_controls.py` | PASS | 5/0/0/0 | [apps__api-server__verification__test_run_controls.py.log](apps__api-server__verification__test_run_controls.py.log) |  |
| `apps/api-server/verification/test_run_history.py` | PASS | 7/0/0/0 | [apps__api-server__verification__test_run_history.py.log](apps__api-server__verification__test_run_history.py.log) |  |
| `apps/api-server/verification/test_run_schedules.py` | FAIL | 35/1/0/0 | [schedule-rerun.log](schedule-rerun.log) | 35 pass, 1 fail: mock preflight trả gate cũ vượt TTL 5 phút; chạy riêng nguyên assertion hoàn tất ở tick 21. |
| `apps/api-server/verification/test_session_limits.py` | PASS | 8/0/0/0 | [apps__api-server__verification__test_session_limits.py.log](apps__api-server__verification__test_session_limits.py.log) |  |
| `apps/api-server/verification/test_shared_batch_queue.py` | PASS | — | [apps__api-server__verification__test_shared_batch_queue.py.log](apps__api-server__verification__test_shared_batch_queue.py.log) |  |
| `apps/api-server/verification/test_shared_migration.py` | PASS | — | [apps__api-server__verification__test_shared_migration.py.log](apps__api-server__verification__test_shared_migration.py.log) | Pass trên DB 0 dòng; chỉ chứng minh script chạy, chưa kiểm chứng migration dữ liệu lịch sử. |
| `apps/api-server/verification/test_ui_contract.py` | PASS | 11/0/0/0 | [apps__api-server__verification__test_ui_contract.py.log](apps__api-server__verification__test_ui_contract.py.log) |  |
| `apps/api-server/verification/test_update_status.py` | PASS | 3/0/0/0 | [apps__api-server__verification__test_update_status.py.log](apps__api-server__verification__test_update_status.py.log) |  |
| `apps/api-server/verification/test_worker_pool.py` | PASS | 7/0/0/0 | [apps__api-server__verification__test_worker_pool.py.log](apps__api-server__verification__test_worker_pool.py.log) |  |
| `apps/browser-runner/test-filter-fill.mjs` | PASS | — | [apps__browser-runner__test-filter-fill.mjs.log](apps__browser-runner__test-filter-fill.mjs.log) |  |
| `apps/browser-runner/test-health-navigation.mjs` | PASS | — | [apps__browser-runner__test-health-navigation.mjs.log](apps__browser-runner__test-health-navigation.mjs.log) |  |
| `apps/browser-runner/test-health-trigger.mjs` | PASS | — | [apps__browser-runner__test-health-trigger.mjs.log](apps__browser-runner__test-health-trigger.mjs.log) |  |
| `apps/browser-runner/test-image-pipe.mjs` | PASS | — | [apps__browser-runner__test-image-pipe.mjs.log](apps__browser-runner__test-image-pipe.mjs.log) |  |
| `apps/browser-runner/test-job-lifecycle.mjs` | PASS | — | [apps__browser-runner__test-job-lifecycle.mjs.log](apps__browser-runner__test-job-lifecycle.mjs.log) |  |
| `apps/browser-runner/test-main-report-save.mjs` | PASS | — | [apps__browser-runner__test-main-report-save.mjs.log](apps__browser-runner__test-main-report-save.mjs.log) |  |
| `apps/browser-runner/test-navigation.mjs` | PASS | — | [apps__browser-runner__test-navigation.mjs.log](apps__browser-runner__test-navigation.mjs.log) |  |
| `apps/browser-runner/test-options.mjs` | PASS | — | [apps__browser-runner__test-options.mjs.log](apps__browser-runner__test-options.mjs.log) |  |
| `apps/browser-runner/test-page-recovery.mjs` | PASS | — | [apps__browser-runner__test-page-recovery.mjs.log](apps__browser-runner__test-page-recovery.mjs.log) |  |
| `apps/browser-runner/test-profile-options.mjs` | PASS | — | [apps__browser-runner__test-profile-options.mjs.log](apps__browser-runner__test-profile-options.mjs.log) |  |
| `apps/browser-runner/test-results.mjs` | PASS | — | [apps__browser-runner__test-results.mjs.log](apps__browser-runner__test-results.mjs.log) |  |
| `apps/browser-runner/test-ui-health-contract.mjs` | PASS | — | [apps__browser-runner__test-ui-health-contract.mjs.log](apps__browser-runner__test-ui-health-contract.mjs.log) |  |
| `apps/web-ui/scripts/test-account-settings-ui.mjs` | PASS | — | [snapshot-apps__web-ui__scripts__test-account-settings-ui.mjs.log](snapshot-apps__web-ui__scripts__test-account-settings-ui.mjs.log) |  |
| `apps/web-ui/scripts/test-annual-reports.mjs` | PASS | — | [snapshot-apps__web-ui__scripts__test-annual-reports.mjs.log](snapshot-apps__web-ui__scripts__test-annual-reports.mjs.log) |  |
| `apps/web-ui/scripts/test-artifact-path.mjs` | PASS | — | [snapshot-apps__web-ui__scripts__test-artifact-path.mjs.log](snapshot-apps__web-ui__scripts__test-artifact-path.mjs.log) |  |
| `apps/web-ui/scripts/test-batch-timing.mjs` | PASS | — | [snapshot-apps__web-ui__scripts__test-batch-timing.mjs.log](snapshot-apps__web-ui__scripts__test-batch-timing.mjs.log) |  |
| `apps/web-ui/scripts/test-filter-profiles-ui.mjs` | FAIL | — | [snapshot-apps__web-ui__scripts__test-filter-profiles-ui.mjs.log](snapshot-apps__web-ui__scripts__test-filter-profiles-ui.mjs.log) | Kỳ vọng input Report year trên form lịch đã bị bỏ. Bản sao chẩn đoán có lượt pass và có lượt vấp race forceBusy; xem ghi chú. |
| `apps/web-ui/scripts/test-health-page-ui.mjs` | PASS | — | [snapshot-apps__web-ui__scripts__test-health-page-ui.mjs.log](snapshot-apps__web-ui__scripts__test-health-page-ui.mjs.log) |  |
| `apps/web-ui/scripts/test-navigation-ui.mjs` | PASS | — | [snapshot-apps__web-ui__scripts__test-navigation-ui.mjs.log](snapshot-apps__web-ui__scripts__test-navigation-ui.mjs.log) |  |
| `apps/web-ui/scripts/test-network-ui.mjs` | PASS | — | [snapshot-apps__web-ui__scripts__test-network-ui.mjs.log](snapshot-apps__web-ui__scripts__test-network-ui.mjs.log) |  |
| `apps/web-ui/scripts/test-permissions-ui.mjs` | FAIL | — | [snapshot-apps__web-ui__scripts__test-permissions-ui.mjs.log](snapshot-apps__web-ui__scripts__test-permissions-ui.mjs.log) | Kỳ vọng trang deny sau tải lại /filters, /settings; code hiện tại chuyển member về Reports. Hash navigation vẫn deny. |
| `apps/web-ui/scripts/test-platform.mjs` | FAIL | — | [snapshot-apps__web-ui__scripts__test-platform.mjs.log](snapshot-apps__web-ui__scripts__test-platform.mjs.log) | Aggregator dừng tại test-filter-profiles-ui.mjs; mọi file con đã được chạy riêng để không bỏ sót. |
| `apps/web-ui/scripts/test-run-schedules-ui.mjs` | PASS | — | [snapshot-apps__web-ui__scripts__test-run-schedules-ui.mjs.log](snapshot-apps__web-ui__scripts__test-run-schedules-ui.mjs.log) |  |
| `apps/web-ui/scripts/test-schedule-timing.mjs` | PASS | — | [snapshot-apps__web-ui__scripts__test-schedule-timing.mjs.log](snapshot-apps__web-ui__scripts__test-schedule-timing.mjs.log) |  |
| `apps/web-ui/scripts/test-session-ui.mjs` | PASS | — | [snapshot-apps__web-ui__scripts__test-session-ui.mjs.log](snapshot-apps__web-ui__scripts__test-session-ui.mjs.log) |  |
| `apps/web-ui/scripts/test-update-history-ui.mjs` | PASS | — | [snapshot-apps__web-ui__scripts__test-update-history-ui.mjs.log](snapshot-apps__web-ui__scripts__test-update-history-ui.mjs.log) |  |
| `scripts/test_deployment_guard.py` | PASS | 12/0/0/0 | [scripts__test_deployment_guard.py.log](scripts__test_deployment_guard.py.log) |  |
| `scripts/test_worker_capacity.py` | PASS | 7/0/0/0 | [scripts__test_worker_capacity.py.log](scripts__test_worker_capacity.py.log) |  |
| `tools/ui-drift-guard/test_ui_contract.py` | PASS | — | [tools__ui-drift-guard__test_ui_contract.py-rerun.log](tools__ui-drift-guard__test_ui_contract.py-rerun.log) | Thiếu Python Playwright ban đầu; cài trong thư mục tạm và chạy lại pass. |
| `tools/ui-drift-guard/test_ui_diagnostics.py` | PASS | — | [tools__ui-drift-guard__test_ui_diagnostics.py-rerun.log](tools__ui-drift-guard__test_ui_diagnostics.py-rerun.log) | Thiếu Python Playwright ban đầu; cài trong thư mục tạm và chạy lại pass. |

Thêm: [maker_update_smoke.py log](apps__api-server__verification__maker_update_smoke.py.log) PASS; [smoke-ui.mjs log](apps__web-ui__scripts__smoke-ui.mjs.log) FAIL; [web build snapshot](snapshot-web-build.log) PASS; [runner syntax](runner-check.log) PASS.

Bằng chứng ba probe: [script](reproduce.py), [log](reproduce.log). Chẩn đoán headless: [script](diagnose-headless.py), [log](diagnose-headless.log). Bản sao filter/permission chỉ nằm trong output audit; test gốc giữ nguyên. `tests/conftest.py` là fixture và `test-scenarios-filter.json` là input, không phải file test thực thi.

Kết quả máy đọc: [final-results.json](final-results.json). Log lần đầu giữ trong results.json; snapshot-ui-results.json là lượt UI trên commit mới. Hai PNG Run History do test ghi đè đã được khôi phục; các thay đổi và artifact đăng nhập khác của workspace được giữ nguyên.

# Rà soát và sửa lỗi Đợt 1–5

Ghi chú lịch sử (merge 2026-10-13): 51 file log được dẫn trong báo cáo gốc không có trong repo; các bản tổng hợp JSON vẫn nằm ở `docs/evidence/round1-5/`. Giới hạn lượt OCR được mô tả bên dưới đã bị gỡ khỏi code sau lần kiểm này.

Ngày kiểm: 2026-10-12. Code nền: `87bb34d2a3f86d2fbc7eb6783b47b219e690acbe`.
Bản sửa hiện là thay đổi local, chưa commit/push. Các bài DB và cài gói dùng
project/database riêng; không nâng cấp hay restart stack đang sử dụng.

## Lỗi được xác nhận và sửa

**R5-UIH-001 — lỗi sản phẩm.** `current()` và `evaluate()` trong
`apps/api-server/app/repositories/ui_contract.py` lọc lỗi theo runner đang
kết nối. Sau `_expire_disconnected_runner()` ở `app/realtime/runner_events.py`
gọi `PostgresRunnerRegistry.remove_by_socket()`, lỗi DOM vẫn còn trong SQL
nhưng `blocked` trở thành false. Bản sửa tính trạng thái chặn từ toàn bộ lỗi
chưa được xác minh đã sửa. Disconnect/reconnect không xóa lỗi; kết quả tốt từ
runner khác không xóa lỗi; kết quả tốt từ chính runner lỗi mới xóa lỗi đó.

**Test kỳ vọng cũ.**
`test_disconnected_worker_error_is_retained_and_reconnect_requires_check()`
trong `verification/test_ui_contract.py` từng mong bỏ chặn khi offline.
Đã sửa assertion theo hành vi mới và kiểm thêm đọc lại SQL sau dispose engine.
Không skip/xfail. Kiểm thêm cùng hành vi bằng API production đã build, chạy
DB role hạn chế trong `scripts/test_container_security.py`; CI đang chạy file
này nên regression được kiểm trên image trong pipeline.

**Thiếu kiểm tra trong CI.** `scripts/test-user-state-codec.py` đã pass local
và được bổ sung vào native job của `.github/workflows/platform.yml`. Workflow
vẫn áp dụng cho `ocr`, `release`, `release/**`, `main`, PR và manual dispatch.
Chưa có CI remote chạy bản sửa local này.

## Đối chiếu từng đợt

| Đợt | Chức năng và nơi xử lý | Bằng chứng |
|---|---|---|
| 1 | UI Health được sửa như trên. Preflight kiểm pool runner được chọn trong `api/ui_health.py:preflight()`; kiểm DOM và giới hạn case là hai việc riêng. | SQL contract regression, production API regression, disconnect thật trong gói cài. |
| 2 | `run_scheduler.py:prepare_run()` chờ runner; `connected_workers()` dùng pool đang kết nối. `BatchQueueRepository.claim()` dùng số live runner khi `automaticWorkers=True`, không dùng số worker lớn lịch cũ. `_settle()` thu hồi job mất heartbeat; commit kết quả ở `repositories/report_results.py:commit_report_result()` bảo vệ kết quả muộn. | Lịch 0/1/3 runner, queue đồng thời, lease, restart, pause/resume, mạng, retry và migration có dữ liệu. |
| 3 | Timezone, ETA, Run History admin, retry giữ case, sample mặc định tắt, export xác nhận và toàn bộ dòng khớp, route đã gỡ. | Test SQL/UI; gói cài kiểm export 1.000 dòng và route 404. |
| 4 | Nginx/login, origin allowlist, CSP, production docs, readiness ngoài Docker, role DML cài mới/nâng cấp. OCR chung toàn hệ thống tại `reserve_ocr_start()` và lỗi job/web tại `begin_ocr()`. | Core OCR limiter, runtime security, hash locks, image digest, scan và SBOM. |
| 5 | Link tài liệu, launcher gói offline, Chromium sandbox/Tesseract thật, UI thật, API restart và backup/restore. | Gói thử từ code nền cộng đúng ba file sửa, manifest ghi rõ override chưa commit. |

## Phạm vi bằng chứng và mục còn mở

- Scan mới: **236 HIGH/CRITICAL chưa có vendor fix**; 0 HIGH/CRITICAL có
  bản vá, 0 lỗi scan. Đây vẫn là phát hiện bảo mật mở, không gọi scan sạch.
- Bài đo ETA đã có ở `outputs/audit-round3/eta-measurement.json`: 100 case
  hoàn tất trong 45 phút 21 giây, peak 3, 101 attempts do recovery; dùng
  worker protocol tổng hợp với đồng hồ/HTTP/Socket.IO/SQL thật. Median sai số
  361,6 giây, p90 614,3 giây; sau 20 case median 320 giây. Đây là bằng chứng
  trước lần rà soát này, không phải benchmark 100 case Chrome/OCR live mới.
- Gói lần này không chạy lại thu thập một case live (`--live-case` không bật).
  Bằng chứng live đã có trong [báo cáo Đợt 5](round5-review-evidence.md).
- Chưa kiểm nâng cấp dữ liệu production, toàn bộ State/RTO, các hệ điều hành
  khác trên host này, LAN/TLS/HA và kiểm chứng nghiệp vụ độc lập dữ liệu VAHAN.
- Lệnh thử runner ban đầu gõ sai tên file seccomp (exit 125) là lỗi lệnh kiểm,
  không phải lỗi sản phẩm. Lệnh sửa dùng `docker/seccomp_profile.json` đã pass;
  cả log lỗi lẫn log chạy lại được giữ.

Log đầy đủ, lệnh chạy, source/image hashes và kết quả theo bộ nằm trong
`diagnostics/round1-5-audit/`. Các file trong `outputs/` và ba thay đổi UI có
sẵn được giữ nguyên; gói thử mới loại những thay đổi UI đó để kiểm đúng phạm vi.

## Kết quả chạy lại

**276 pytest DB pass**, 24 bước DB pass; 25 bước native/check/build pass; **55/55 kiểm tra gói pass**, exit 0. Không skip/xfail.

Gói mới chạy 2026-10-12T14:55:36.459985+00:00 đến 2026-10-12T15:01:18.585559+00:00 (UTC). Manifest ghi SHA nền và hash ba override chưa commit; không coi SHA nền là commit đã chứa bản sửa.

- [Tổng kết máy đọc](evidence/round1-5/summary.json).
- [Manifest gói và override](evidence/round1-5/package-manifest.json).
- [55 kiểm tra gói cài](evidence/round1-5/installed-results.json).
- [Disconnect thật: trước/sau đều blocked=true](evidence/round1-5/installed-ui-health-disconnect-finding.json).
- Security và regression production API (log g?c kh?ng c? trong repo).
- Chromium/OCR thật (log g?c kh?ng c? trong repo).
- [Scan/SBOM summary](evidence/round1-5/scan-summary.json); SBOM và finding đầy đủ giữ tại `diagnostics/round1-5-audit/sbom/`.

### DB theo file/bộ

| File/bộ | Kết quả | Log |
|---|---|---|
| `python -m pytest tests` | 106 pass | Log (log g?c kh?ng c? trong repo) |
| `python -m pytest verification/test_permissions.py` | 5 pass | Log (log g?c kh?ng c? trong repo) |
| `python ../../scripts/test_runtime_role_lifecycle.py` | PASS | Log (log g?c kh?ng c? trong repo) |
| `python -m pytest verification/test_account_passwords.py` | 7 pass | Log (log g?c kh?ng c? trong repo) |
| `python -m pytest verification/test_report_results.py` | 22 pass | Log (log g?c kh?ng c? trong repo) |
| `python -m pytest verification/test_annual_reports.py` | 19 pass | Log (log g?c kh?ng c? trong repo) |
| `python -m pytest verification/test_filter_profiles.py` | 8 pass | Log (log g?c kh?ng c? trong repo) |
| `python -m pytest verification/test_ui_contract.py` | 11 pass | Log (log g?c kh?ng c? trong repo) |
| `python -m pytest verification/test_run_controls.py` | 5 pass | Log (log g?c kh?ng c? trong repo) |
| `python -m pytest verification/test_update_status.py` | 3 pass | Log (log g?c kh?ng c? trong repo) |
| `python -m pytest verification/test_worker_pool.py` | 7 pass | Log (log g?c kh?ng c? trong repo) |
| `python -m pytest verification/test_session_limits.py` | 8 pass | Log (log g?c kh?ng c? trong repo) |
| `python -m pytest verification/test_retry_sessions.py` | 12 pass | Log (log g?c kh?ng c? trong repo) |
| `python -m pytest verification/test_report_coverage.py` | 8 pass | Log (log g?c kh?ng c? trong repo) |
| `python -m pytest verification/test_run_schedules.py` | 39 pass | Log (log g?c kh?ng c? trong repo) |
| `python -m pytest verification/test_queue_retry_checkpoints.py` | 5 pass | Log (log g?c kh?ng c? trong repo) |
| `python -m pytest verification/test_run_history.py` | 7 pass | Log (log g?c kh?ng c? trong repo) |
| `python -m pytest verification/test_worker_lifecycle.py` | 2 pass | Log (log g?c kh?ng c? trong repo) |
| `python -m pytest verification/test_queue_migrations.py` | 2 pass | Log (log g?c kh?ng c? trong repo) |
| `python verification/test_shared_batch_queue.py` | PASS | Log (log g?c kh?ng c? trong repo) |
| `python verification/prepare_report_test_fixtures.py` | PASS | Log (log g?c kh?ng c? trong repo) |
| `python verification/test_main_migration.py` | PASS | Log (log g?c kh?ng c? trong repo) |
| `python verification/test_shared_migration.py` | PASS | Log (log g?c kh?ng c? trong repo) |
| `python verification/test_main_live_workbook.py` | PASS | Log (log g?c kh?ng c? trong repo) |

Core `pytest tests` gồm tất cả các file dưới đây; cả bộ 106 pass, không có fail/skip:

| File | Kết quả |
|---|---|
| `test_annual_schedule_rollover.py` | PASS |
| `test_api.py` | PASS |
| `test_excel.py` | PASS |
| `test_ocr_rate_limit.py` | PASS |
| `test_queue_recovery.py` | PASS |
| `test_report_history.py` | PASS |
| `test_repositories.py` | PASS |
| `test_retired_features.py` | PASS |
| `test_runner_queue.py` | PASS |
| `test_schedule_capacity_api.py` | PASS |
| `test_socketio_flow.py` | PASS |
| `test_time_zones.py` | PASS |
| `test_ui_health_logs.py` | PASS |
| `test_upload_limits.py` | PASS |

### Native và browser runner theo file/bộ

| File/bộ | Kết quả | Log |
|---|---|---|
| `docs` | PASS | Log (log g?c kh?ng c? trong repo) |
| `test_ocr_platform.py` | PASS | Log (log g?c kh?ng c? trong repo) |
| `test_captcha_ephemeral.py` | PASS | Log (log g?c kh?ng c? trong repo) |
| `test_captcha_refresh_race.py` | PASS | Log (log g?c kh?ng c? trong repo) |
| `test_production_config.py` | PASS | Log (log g?c kh?ng c? trong repo) |
| `test_deployment_guard.py` | PASS | Log (log g?c kh?ng c? trong repo) |
| `test_worker_capacity.py` | PASS | Log (log g?c kh?ng c? trong repo) |
| `test_container_scan.py` | PASS | Log (log g?c kh?ng c? trong repo) |
| `ui-diagnostics` | PASS | Log (log g?c kh?ng c? trong repo) |
| `test-filter-fill.mjs` | PASS | Log (log g?c kh?ng c? trong repo) |
| `test-health-navigation.mjs` | PASS | Log (log g?c kh?ng c? trong repo) |
| `test-health-trigger.mjs` | PASS | Log (log g?c kh?ng c? trong repo) |
| `test-image-pipe.mjs` | PASS | Log (log g?c kh?ng c? trong repo) |
| `test-job-lifecycle.mjs` | PASS | Log (log g?c kh?ng c? trong repo) |
| `test-main-report-save.mjs` | PASS | Log (log g?c kh?ng c? trong repo) |
| `test-navigation.mjs` | PASS | Log (log g?c kh?ng c? trong repo) |
| `test-ocr-rate-limit.mjs` | PASS | Log (log g?c kh?ng c? trong repo) |
| `test-options.mjs` | PASS | Log (log g?c kh?ng c? trong repo) |
| `test-page-recovery.mjs` | PASS | Log (log g?c kh?ng c? trong repo) |
| `test-profile-options.mjs` | PASS | Log (log g?c kh?ng c? trong repo) |
| `test-results.mjs` | PASS | Log (log g?c kh?ng c? trong repo) |
| `test-ui-health-contract.mjs` | PASS | Log (log g?c kh?ng c? trong repo) |
| `web-check` | PASS | Log (log g?c kh?ng c? trong repo) |
| `web-build` | PASS | Log (log g?c kh?ng c? trong repo) |
| `web-test-platform` | PASS | Log (log g?c kh?ng c? trong repo) |

Web platform bao gồm 13 file; local dùng UI đang có, gói cài dùng fixture/code sạch tương ứng gói:

| File | Local / gói cài |
|---|---|
| `test-batch-timing.mjs` | PASS / PASS |
| `test-schedule-timing.mjs` | PASS / PASS |
| `test-time-zones.mjs` | PASS / PASS |
| `test-session-ui.mjs` | PASS / PASS |
| `test-annual-reports.mjs` | PASS / PASS |
| `test-filter-profiles-ui.mjs` | PASS / PASS |
| `test-health-page-ui.mjs` | PASS / PASS |
| `test-navigation-ui.mjs` | PASS / PASS |
| `test-run-schedules-ui.mjs` | PASS / PASS |
| `test-update-history-ui.mjs` | PASS / PASS |
| `test-account-settings-ui.mjs` | PASS / PASS |
| `test-network-ui.mjs` | PASS / PASS |
| `test-permissions-ui.mjs` | PASS / PASS |

Các lệnh bổ sung đều exit 0: `python scripts/test_container_security.py`, chạy lại với `--no-build` để kiểm regression mới; `python scripts/scan_container_images.py --output-dir diagnostics/round1-5-audit/sbom --ca-cert docker/certs/vingroup-enterprise-ca.crt`; `python apps/api-server/scripts/test-user-state-codec.py`; `docker run --rm --init --shm-size=1g --security-opt seccomp=docker/seccomp_profile.json --entrypoint node vahan-security-test/runner:round4 test-container-runtime.mjs`.

Lệnh harness: `python diagnostics/round1-5-audit/run-native.py`, `python diagnostics/round1-5-audit/run-database-ci.py`, `python diagnostics/round1-5-audit/package-working-fix.py`. Các bản harness đã lưu cùng log trong `docs/evidence/round1-5/`; chạy từ thư mục repo. Harness gói cần thư mục đích mới khi chạy lại, vì không ghi đè artifact hiện có.

# T15b / D-35 Q1 = A — migration dừng khi lịch Daily còn session (E-local, DB dùng một lần)

- ngày: 2026-10-15
- source: working tree trên `b9c33786e565` (HEAD lúc chạy) + thay đổi của commit chứa file này; Python 3.12.10, PostgreSQL 17.11 (image chính thức pin digest) trong container dùng một lần, cổng ngẫu nhiên, tmpfs. **Không** dùng project/volume `vahan-automation`.
- loại bằng chứng: **E-local**. Chưa có E-CI. Không chạy trên DB thật.
- quyết định áp dụng (Felix, PLAN §5.11): Q-A = **B** (revision bảo vệ chèn trước `0015`, thân `0015` không đổi), Q-B = **strict** (mọi `sessionId` không rỗng đều chặn, `status` không tham gia).

## Thay đổi

| File | Nội dung |
| --- | --- |
| `apps/api-server/migrations/versions/0014a_daily_schedule_guard.py` (mới) | `upgrade()` chỉ SELECT; nếu có `automatic-report-schedule:*` với `repeat='daily'` và `COALESCE(value->>'sessionId','') <> ''` thì `RuntimeError` liệt kê ID/owner/tên/status (không `definition`). `downgrade()` no-op |
| `apps/api-server/migrations/versions/0015_remove_daily_schedules.py` | `down_revision` → `0014a_daily_schedule_guard`; docstring; **thân không đổi** |
| `scripts/deployment_guard.py` | hằng số `DAILY_BLOCKING_SQL` (cùng text với migration), khóa `blockingDailySchedules`, thông báo mô tả cả `PAUSED` |
| `apps/api-server/verification/test_daily_schedule_removal.py`, `scripts/test_deployment_guard.py` | test mới (xem dưới) |
| `docs/release/INSTALL.md` §7, `deploy.md`, `docs/release/ops/runbook.md`, `docs/run-schedules.md`, `docs/runbook.md` | bỏ chỉ dẫn "Pause" cho Daily; ghi hệ quả Stop/Delete; mô tả migration dừng |

## Kết quả

| # | Lệnh (cwd `apps/api-server`, biến môi trường như job `database-integration`) | Kết quả |
| --- | --- | --- |
| 1 | Test mới trên **chuỗi migration cũ** (`0015` của `HEAD`, bỏ `0014a`) — đỏ-trước | 3 failed / 3 passed: ba test abort/parity/remediation đỏ (migration cũ **xóa** Daily có session). Với `sessionId=0` migration cũ còn **crash** (`operator does not exist: character varying = integer` ở `preserve_history`) |
| 2 | `VAHAN_DAILY_MIGRATION_TEST_DATABASE=vahan_migration_daily_test python -m pytest verification/test_daily_schedule_removal.py -v` (chuỗi mới) | **6 passed** (51 s) |
| 3 | `python -m unittest discover -s ../../scripts -p test_deployment_guard.py` | **8 tests OK** (thêm 3: khóa Daily, thiếu khóa mới fail-closed, điều kiện không phụ thuộc `status`) |
| 4 | `python -m app.migrate` trên DB rỗng | exit 0, đi qua `0014a` → `0015` → `0016` |
| 5 | `verification/test_state_gate_migration.py`, `verification/test_queue_migrations.py` | passed (3 + 2): test dùng `0015`/`0014` không bị ảnh hưởng |
| 6 | `python scripts/check-test-registration.py --require-history`; `python scripts/check-doc-links.py` | 93/93, 0 problem; 81 link, 0 missing |

## DB không đổi khi migration dừng (`abort-run.json`)

Fixture: fixture cũ (5 session, 20 job/task; Daily `COMPLETED` không session, Daily `PAUSED`/`RUNNING` có session) + 20 Daily có `sessionId` ở mọi status (`PREPARING…COMPLETED_WITH_ERRORS`, `ERROR`, `ARCHIVED`, `running`, `''`, `null`, thiếu khóa) và `sessionId` lạ (`' '`, `0`, `false`, `[]`, `'x'`).

| Mục | Trước | Sau |
| --- | --- | --- |
| Exit code của `alembic upgrade 0015` | — | **1** |
| ID lịch bị chặn trong thông báo | 22 mong đợi | **22, khớp đúng tập mong đợi** (`idsMatch: true`) |
| Hash nội dung **mọi bảng** (25 bảng; mỗi bảng SHA-256 của `row_to_json` đã sắp xếp; 12 ký tự đầu trong JSON) | — | giống hệt (`digestUnchanged: true`), gồm `app_settings` và `alembic_version` |
| `alembic_version` | `0014_postgresql_task_claims` | `0014_postgresql_task_claims` |
| Số dòng `app_settings` / `jobs` / `batch_queue_tasks` / `users` | 28 / 20 / 20 / 1 | giống hệt |
| Số lịch Daily | 23 | 23 (kể cả Daily `COMPLETED` không session: **tất cả hoặc không gì**) |
| Dòng `migration-audit:*` mới | — | 0 |
| Rò `definition` trong thông báo | — | không |

Vì `0014a` chỉ SELECT trước mọi ghi, không có gì để hoàn tác; bằng chứng là trạng thái cuối giống hệt.

## Sau khi gỡ (`test_operator_remediation_then_upgrade_succeeds`)

Daily `PAUSED`/`RUNNING` có session ⇒ abort; mô phỏng Stop trên bản cũ (`status=STOPPED`, `sessionId=null`) ⇒ nâng cấp xong, `deleted 3 Daily schedule(s)`, `alembic_version = 0015`, `users`/`report_sessions`/`batch_queue_*`/`jobs` không đổi, 0 Daily còn lại.

## Chính sách khi không dừng (`test_daily_schedule_without_a_session...`)

Daily **không** có `sessionId` (null/`''`/thiếu khóa) ở mọi status (`STOPPED`, `COMPLETED`, `COMPLETED_WITH_ERRORS`, `WAITING`, `PAUSED`, `RUNNING`, `ERROR`, `WEIRD`, `null`) ⇒ bị xóa; Once/Monthly/dòng không phải object/`batch-retry-policy`/`report-run-history` có sẵn **byte-identical**; tên Run History của Daily có `lastSessionId` được giữ; audit `count` đúng, `hadActiveSession` đều `false`, không có `definition`. Chạy lại `upgrade head` là no-op; downgrade không khôi phục lịch, audit cộng dồn khi nâng cấp lại.

## Parity guard ↔ migration (`test_release_guard_sql_and_migration_block_exactly_the_same_schedules`)

Cùng một DB: `DAILY_BLOCKING_SQL` đếm 22; `deployment_guard.QUERY` trả `blockingDailySchedules = 22`; migration dừng với đúng 22 ID đó; các hàng không chặn (Daily `sessionId` null/`''`/thiếu cùng `status` null/thiếu, Once/Monthly có session) không bị đếm. Text SQL của guard nằm nguyên văn trong file migration (test kiểm).

## Giới hạn (Not verified)

- E-CI trên commit này (chưa push).
- Hành vi Compose khi `migrate` thoát ≠ 0 giữa nâng cấp thật (container cũ/mới) — chỉ kiểm ở mức Alembic/DB.
- Thao tác Resume/Stop/Delete trên UI bản cũ thật. Tên "Unnamed filter" sau Stop chỉ suy ra từ code (`stop_scheduled_run` đặt `sessionId=None`, không đặt `lastSessionId`).
- DB bền vững thật: `alembic_version` của DB live/UAT/máy khác chưa đọc. `0014a` chỉ bảo vệ DB chưa áp dụng `0015`.
- Chỉ nhìn dòng lịch: queue vẫn `RUNNING` khi lịch ghi `STOPPED`/`COMPLETED` không bị chặn.

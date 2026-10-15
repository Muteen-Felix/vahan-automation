# T15b / D-35 — bỏ Daily và xóa lịch Daily đã lưu (E-local, DB dùng một lần)

- ngày: 2026-10-15
- source: `e46e39e627fac5e0e8ad5f36ca22e51e61f3e40a` (branch `release/pre-go-live`), working tree không sửa code
- loại bằng chứng: **E-local** (không phải E-CI, không phải D3). Chưa có bằng chứng CI cho commit này.
- môi trường: PostgreSQL `17.11` (image chính thức, ID `sha256:3645570c…3826`) trong container dùng một lần, cổng ngẫu nhiên trên `127.0.0.1`, dữ liệu trong tmpfs, DB `vahan_api_test`, `vahan_migration_daily_test`, `vahan_schedule_platform_test`; Python 3.12.10 (`apps/api-server/.venv`). **Không** dùng project/volume `vahan-automation`; container đã xóa sau khi chạy. Không chạy migration trên dữ liệu thật.

## Lệnh và kết quả

| # | Lệnh (cwd `apps/api-server`, biến môi trường như job `database-integration`) | Kết quả |
| --- | --- | --- |
| 1 | `python -m app.migrate` (DB `vahan_api_test`, rỗng) | exit 0; log: `0015_remove_daily_schedules: deleted 0 Daily schedule(s); kept 0 Once/Monthly schedule(s); ids=[]` |
| 2 | `python -m pytest tests/test_annual_schedule_rollover.py -v` | **5 passed** (gồm `test_new_schedules_allow_once_and_monthly_but_not_daily`: `repeat='daily'` bị `RunScheduleCreate` từ chối) |
| 3 | `VAHAN_DAILY_MIGRATION_TEST_DATABASE=vahan_migration_daily_test python -m pytest verification/test_daily_schedule_removal.py -v` | **3 passed** (15,6 s) |
| 4 | `VAHAN_SCHEDULE_TEST_DATABASE=vahan_schedule_platform_test python -m pytest verification/test_run_schedules.py -v` | **40 passed** (268,5 s) |
| 5 | script dùng một lần (không commit) dựng lại fixture của lệnh 3, `alembic upgrade 0015`, in ID + số dòng | xem bảng dưới; JSON nguyên văn: `before-after.json` |

## ID và số lượng trước/sau (lệnh 5; dữ liệu giả lập, DB dùng một lần)

Schedule (key `automatic-report-schedule:<id>` trong `app_settings`):

| id | repeat | status | profileName | Trước | Sau |
| --- | --- | --- | --- | --- | --- |
| `33b6477c-ed6d-40e6-98c6-cb0e335511b9` | daily | COMPLETED | Daily finished | có | **xóa** |
| `450a9138-a195-4305-8ae8-baf4a5892b44` | daily | RUNNING (có `sessionId`) | Daily running | có | **xóa** |
| `cc47755d-22e7-4a91-80fd-ae04b92ecf4a` | daily | PAUSED (có `sessionId`) | Daily paused | có | **xóa** |
| `c58d8041-eb56-445b-988d-126c0ed10fe2` | monthly | WAITING | Monthly schedule | có | giữ nguyên |
| `68138e99-b861-42e2-86e8-4fe9e6898435` | once | COMPLETED | Once schedule | có | giữ nguyên |
| `odd-non-object` | (giá trị không phải object) | — | — | có | giữ nguyên |

Số dòng bảng:

| Bảng | Trước | Sau |
| --- | --- | --- |
| `users` | 1 | 1 |
| `report_sessions` | 5 | 5 |
| `batch_queue_sessions` | 5 | 5 |
| `batch_queue_tasks` | 20 | 20 |
| `jobs` | 20 | 20 |
| `app_settings` | 8 | 9 (−3 lịch Daily, +3 `report-run-history:<session>`, +1 audit `migration-audit:0015_remove_daily_schedules`) |

Ghi chú: `report-run-history:*` sau migration = 4 key (3 key mới cho Daily có `sessionId`/`lastSessionId` + 1 key có sẵn của Once). Audit: `count 3`, `keptNonDailySchedules 3`, `hadActiveSession` = `false` (COMPLETED) / `true` (RUNNING, PAUSED); không chứa `definition` (test kiểm).

Điều đã chứng minh (test 3, assert trong code): chỉ ba dòng Daily bị xóa; Once/Monthly/dòng không phải object và các key `batch-retry-policy:*`, `report-run-history:*` có sẵn **giống hệt** trước/sau; `users`, `report_sessions`, `batch_queue_*`, `jobs` không đổi (so toàn bộ `SELECT *`); Run History vẫn trả đúng tên bộ lọc của 3 session Daily; DB rỗng hoặc chỉ Once/Monthly ⇒ không đổi và không ghi audit; chạy lại `upgrade head` là no-op; downgrade không khôi phục lịch và giữ audit; Daily khôi phục từ backup cũ rồi nâng cấp lại ⇒ audit cộng dồn (`count` +1).

## ⚠️ Lệch với giả định của PLAN §5.9.2 / §5.10 (cần Felix xác nhận)

- PLAN §5.9.2 Q1 đề xuất phương án **A**: migration **abort** khi Daily đang chạy. Code ở BASE_SHA hiện thực phương án **B**: **xóa** dòng lịch Daily kể cả khi có `sessionId` đang hoạt động; session/queue được giữ và "chạy xong mà không có lịch điều khiển" (docstring `0015_remove_daily_schedules.py`; test `test_only_daily_rows_are_deleted_and_history_names_survive` khẳng định 3 dòng Daily gồm RUNNING bị xóa). Phù hợp chữ D-35 ("xóa toàn bộ lịch Daily đã lưu") nhưng **không** có abort. Tôi không tìm thấy bản ghi Felix chọn B cho Q1/Q2 trong PLAN.md.
- Hệ quả vận hành: nâng cấp lúc có Daily đang chạy/PAUSED sẽ để lại session mồ côi (không resume được qua lịch). Cách giảm: pause/stop trước khi nâng cấp (T45b `--check-release`) — chưa kiểm chứng trong đợt này.
- Không đổi code; ghi nhận để Felix quyết (giữ B, hoặc mở việc đổi sang A).

## Chưa kiểm chứng

- UI không còn lựa chọn/nhãn Daily: UI test `test-run-schedules-ui.mjs` nằm trong `npm run test:platform` (pass, xem `T16-export-e46e39e627fa.md`), nhưng không có assert riêng về nhãn Daily được ghi ở đây (`grep -in daily` trong file test rỗng).
- Upgrade từ DB ở `0012` có dữ liệu lên `0015`: test dùng `0014` → `0015`; chuỗi `0012→0014` do `test_queue_migrations.py`, không chạy trong đợt này.
- CI trên commit chứa file này: Not verified (chưa push).

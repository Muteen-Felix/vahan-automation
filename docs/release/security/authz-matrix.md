# Authz matrix — hiện trạng (T52a, bản nháp; S8 Deferred nên không cam kết S8-1)

Nguồn: `apps/api-server/app/main.py` (middleware `require_ui_authentication`), `app/access.py`, `app/api/*.py`. Đọc source ngày 13/10/2026;
**chưa kiểm bằng test từng endpoint** — ô "Kiểm" ghi test nào đang chứng minh.

## Lớp xác thực (theo thứ tự middleware)

| Nhóm đường dẫn | Ẩn danh | Runner token + header runner | Member | Admin | Kiểm |
| --- | --- | --- | --- | --- | --- |
| `/api/health`, `/api/ready`, `/api/auth/status`, `/api/auth/login` | cho phép | cho phép | cho phép | cho phép | `release-smoke.py`; login có `limit_req` nginx |
| `/api/ui-health/schedule`, `/api/ui-health/run-now`, `/api/maker-updates*` | 404 | 404 | 404 | 404 | `tests/test_api.py` (đường dẫn gỡ), `tests/test_retired_features.py` (job `update*` bị từ chối) |
| Allowlist runner: `GET /api/ui-health/contract`, `POST /api/ui-health/logs`, `POST /api/jobs/{id}/(main-report\|report-result\|artifacts)`, `GET\|PUT /api/runner-state/*`, `POST /api/runner-logs`, `POST /api/runner/queue/claim`, `POST /api/runner/ocr/start` | 401 | cho phép nếu token khớp | theo bảng dưới | theo bảng dưới | `tests/test_api.py`, `tests/test_runner_queue.py` |
| Allowlist member (chỉ đọc/xuất): `GET /api/auth/me`, `/api/user-state`, `/api/network/status`, `/api/annual-reports`, `/api/annual-reports/history`, `/api/annual-reports/export`, `/api/annual-reports/update-status`; `POST /api/auth/logout`, `/api/auth/activity`, `/api/auth/password`, `/api/annual-reports/coverage` | 401 | — | cho phép | cho phép | `verification/test_permissions.py`, `test-permissions-ui.mjs` |
| Mọi `/api/*` còn lại | 401 | 401 (ngoài allowlist) | **403** | cho phép (một số handler lọc theo owner) | `test_permissions.py` |
| Chỉ admin ở tầng handler (`require_admin`): `/api/users*`, `/api/audit`, `/api/run-schedules*`, `GET /api/annual-reports/run-history` | 401 | 401 | 403 | cho phép | `test_permissions.py`, `test_run_history.py`, `release-smoke.py` |

## Socket.IO

| Namespace | Xác thực | Ghi chú |
| --- | --- | --- |
| `/runner` | `token` runner chung + `runnerId` tự khai | **KI-14:** người giữ token mạo danh được runner ID khác (S8 Deferred) |
| `/ui` | access token phiên | Origin allowlist theo `VAHAN_API_SOCKETIO_CORS_ORIGINS` (production từ chối `*`) |

## Giới hạn đã biết (không cam kết)

- Một token runner chung, ID tự khai: API không gắn yêu cầu HTTP với socket/runner cụ thể (KI-14, Major, chưa là accepted risk — D-20).
- Header `X-VAHAN-RUNNER-ID` chỉ chặn khi lệch `job.runner_id`; header do chính bên gọi khai.
- Token UI lưu `localStorage` (KI-03).
- Mọi `POST/PUT/PATCH/DELETE` được ghi audit (`http.mutation`), trừ `/api/runner-logs` và `/api/runner-state/*`.

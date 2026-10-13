# API của bản thử

API production không công bố `/docs`, `/redoc` hoặc `/openapi.json`.
Danh sách dưới đây là chỉ dẫn vận hành, không thay schema Pydantic trong source.
Dashboard/nginx cùng origin; HTTP API dùng Bearer session. Runner dùng token
riêng và identity; token UI không thay quyền runner.

| Nhóm | Endpoint chính | Quyền |
| --- | --- | --- |
| Sức khỏe | `GET /api/health`, `GET /api/ready` | Public |
| Login/session | `POST /api/auth/login`, `GET /api/auth/me`, `POST /api/auth/activity`, `POST /api/auth/logout` | Session; login public |
| Password | `POST /api/auth/password` | Chính chủ |
| Tài khoản | `/api/users`, `/api/users/{username}`, `/api/users/{username}/password` | Admin |
| Báo cáo | `GET /api/annual-reports`, `/api/annual-reports/export`, `/api/annual-reports/history` | Tài khoản đăng nhập |
| Run History | `GET /api/annual-reports/run-history` | Admin |
| Profile | `/api/filter-profiles`, `/{id}`, `/options`, `/makers`, `/{id}/preview` | Admin |
| Lịch | `/api/run-schedules`, `/{id}/pause`, `/{id}/resume`, `/{id}/stop`, `/time-zone` | Admin |
| Hàng đợi | `/api/batch-queue/sessions` và các thao tác session | Admin |
| Worker | `GET /api/runners`, `/api/worker-pool` | Admin |
| UI Health | `/api/ui-health/status`, `/preflight`, `/logs`, `/reports/{file}/download` | Admin; runner có quyền gửi log |
| Bắt đầu OCR CAPTCHA | `POST /api/runner/ocr/start` | Runner token và identity/job/challenge hợp lệ |

Export nhận `year`, `dataset`, `state`, `rto`; không phân trang khi export.
Không lọc State/RTO phải có `confirmAll=true`; thiếu xác nhận trả 409.
Response có `X-Report-Row-Count` và workbook đầy đủ.

Login rate-limit nằm ở nginx; kiểm từ cổng web. HTTP/Socket.IO origin cần có
trong allowlist. Session có absolute/idle deadline; polling không làm mới idle.
Chi tiết queue/lease ở [hướng dẫn lịch](run-schedules.md),
[retry](batch-error-recovery.md) và [UI Health](ui-health-sql.md).

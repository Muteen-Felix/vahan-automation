# SQL, migration và worker

PostgreSQL giữ business state: tài khoản/session, profile, lịch, queue/task/job,
case identity, browser state mã hóa, dữ liệu báo cáo và quyền runner cho OCR.
Service `postgres` chạy trực tiếp image PostgreSQL chính thức 17.11-bookworm,
pin digest trong `compose.yaml` (xem `docs/release/pins.md`); không tự build. Provisioning chạy qua service `migrate` bằng
DB owner; runtime API dùng role DML riêng, không sở hữu schema hay quyền DDL.

Worker Playwright/Chromium dùng Socket.IO `/runner` và HTTP runner token;
dashboard dùng `/ui` với session. Một API scheduler trên host đọc SQL và
phối hợp runner. Không giả định nhiều replica API được hỗ trợ bởi gói này.

Backup/restore, encryption key và project/volume được mô tả trong
[runbook](runbook.md). Kiểm fresh/upgrade DB role và migration nằm trong
[bằng chứng Đợt 4](round4-security-validation.md).

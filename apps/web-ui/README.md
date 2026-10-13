# VAHAN Dashboard

React/TypeScript/Vite. Docker build static assets; Nginx proxy API/Socket.IO
cùng origin với CSP/headers và login throttle. `VITE_API_URL` để trống trong Docker.

Admin quản lý profile, lịch, Run History, UI Health và tài khoản. Member chỉ
xem Exported Reports. Báo cáo có search State/RTO, phân trang 100 và export mọi
dòng khớp. Export all cần xác nhận. Cài mới không nạp mẫu; lịch không nhập worker.

Retry giữ identity case/session, không tăng case count. Pause/resume, ETA và
network/error banners hiển thị theo trạng thái API/SQL. Ứng dụng không giới hạn
số lần bắt đầu OCR tự động.

```bash
npm ci
npm run check
npm run build
npm run test:platform
```

`test:platform` dùng fixtures trên Vite. Bộ kiểm gói chạy cùng script trên
assets production Nginx; hai phạm vi này không chứng minh report VAHAN live.
Đặt `UI_TEST_ARTIFACT_DIR` để ảnh Run History đi vào diagnostics thay `outputs/`.

Xem [README gốc](../../README.md), [hướng dẫn cài](../../docs/deployment.md),
[runbook](../../docs/runbook.md) và [bằng chứng Đợt 5](../../docs/round5-review-evidence.md).

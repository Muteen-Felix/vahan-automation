# Smoke test (SMOKE)

## Healthcheck kỳ vọng (từ `compose.yaml`)

| Service | Kiểm | Trạng thái |
| --- | --- | --- |
| `postgres` | `pg_isready -U vahan -d vahan` | healthy |
| `migrate` | one-shot | `Exited (0)` |
| `api` | `GET /api/ready` | healthy |
| `web` | `GET /` | healthy |
| `runner` ×N | `GET :3001/health` | healthy |

Tổng: postgres + api + web + N runner `healthy` và `migrate` thoát 0. N = số bản sao (`--workers` / launcher).

## Chạy

```powershell
$env:VAHAN_SMOKE_ADMIN_PASSWORD = '<mật khẩu admin>'
py -3 scripts/release-smoke.py --base-url http://127.0.0.1:5173 --admin-user admin --min-runners <N> `
    --compose-project <project> --require-compose-checks --output smoke.json
```

## Các kiểm tra (exit 0 chỉ khi tất cả đạt)

1. `GET /api/health` → 200 `ok`.
2. `GET /api/ready` → 200, `storage = postgresql`.
3. Web `/` → 200.
4. Đăng nhập admin nhận access token.
5. ≥ N runner `ONLINE` (chờ tối đa 120 giây).
6. Member tạm: đăng nhập được, nhưng 403 ở `/api/annual-reports/run-history`, `/api/users`, `/api/audit`; admin đọc được run-history; member bị vô hiệu hóa sau test.
7. `migrate` đã thoát 0 (cần `--compose-project`).
8. API kết nối bằng role DML-only (không superuser/createdb/createrole/CREATE schema) (cần `--compose-project`).

Smoke **không** chứng minh VAHAN, CAPTCHA hay tải báo cáo hoạt động; dùng `qa/e2e-checklist.md`.
Mật khẩu chỉ đọc từ biến môi trường và không được in ra.

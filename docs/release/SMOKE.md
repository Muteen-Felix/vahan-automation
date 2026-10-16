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

## Kiểm runtime image đã cài (sau khi cài từ gói)

Chạy trên stack vừa cài, không build lại; ghi image ID để đối chiếu `manifest.imageIds`.

```powershell
docker inspect --format "{{.Name}} {{.Image}}" (docker compose --env-file .docker.env ps -q api web runner)   # ID = manifest.imageIds
docker compose --env-file .docker.env exec -T runner node test-container-runtime.mjs                          # Chromium sandbox + Tesseract thật, exit 0
(Invoke-WebRequest http://127.0.0.1:5173/ -UseBasicParsing).Headers['Server']                                  # đúng `nginx`, không kèm số phiên bản
```
Mật khẩu chỉ đọc từ biến môi trường và không được in ra.

## Kiểm gói tự động (T32) và preflight VAHAN (D3) là hai kết quả riêng

`scripts/test-review-package.py` kiểm gói offline (nạp image, cài, backup/restore, test runner/UI). Mặc định nó **không gọi VAHAN**;
preflight D3 được ghi `NOT_RUN` trong `results.json` (`d3.livePreflight.status`) và **không** được tính là Pass.
Chỉ khi chạy với `--vahan-preflight` thì preflight mới chạy; kết quả nằm ở `d3-live-preflight.json` và mục `d3`, tách khỏi `checks`.

Chạy script này trên **Docker daemon riêng, ban đầu không có image, container hoặc volume**; chọn daemon bằng
`DOCKER_HOST` hoặc `DOCKER_CONTEXT` trước khi chạy. Script từ chối daemon đã có dữ liệu và không tự xóa tài nguyên.
Chỉ tạo thư mục/project Compose mới trên daemon đang dùng chưa chứng minh được cài offline: image có sẵn có thể che lỗi
reference bị mất khi `docker save`/`docker load`. Sau load, mọi reference trong manifest (kể cả PostgreSQL pin digest) phải inspect được.

| Exit status | Ý nghĩa |
| --- | --- |
| `0` | Kiểm gói đạt; D3 `NOT_RUN` hoặc `PASS` (xem `d3Status`, không suy ra D3 đạt từ exit 0) |
| `1` | Kiểm gói lỗi (kể cả khi D3 được yêu cầu) |
| `2` | Kiểm gói đạt nhưng D3 được yêu cầu mà không đạt (R6 giữ Not verified) |

CI xanh và kiểm gói đạt **không thay thế** D3 trên VAHAN thật.

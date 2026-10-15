# Tham chiếu cấu hình (T26, C5.1)

Nguồn: `compose.yaml`, `scripts/setup-docker.py`, `scripts/run-docker.py`. Mọi biến Compose đọc qua `--env-file .docker.env`.
`<generate>` = `python scripts/setup-docker.py` tự sinh, **không ghi đè khóa đã có**. Không biến nào dưới đây có giá trị thật trong tài liệu này.

| Biến | Bắt buộc | Mặc định | Ràng buộc / ghi chú |
| --- | --- | --- | --- |
| `POSTGRES_PASSWORD` | Có | `<generate>` (48 hex) | Mật khẩu owner `vahan` (chỉ service `migrate` dùng). |
| `DB_APP_USERNAME` | Không | `vahan_app` | Role runtime của API (DML, không DDL — S12). |
| `DB_APP_PASSWORD` | Có | `<generate>` (48 hex) | ≥ 24 ký tự. Thiếu trong `.docker.env` cũ → `setup-docker.py` bổ sung, **không đổi khóa cũ**. |
| `VAHAN_UI_AUTH_USERNAME` | Không | `admin` | Tên admin bootstrap. |
| `VAHAN_UI_AUTH_PASSWORD` | Có | `<generate>` | Mật khẩu admin bootstrap (đổi sau lần đăng nhập đầu; ≥ 12 ký tự). |
| `VAHAN_UI_AUTH_TOKEN_SECRET` | Có | `<generate>` (96 hex) | ≥ 32 ký tự; ký token phiên. Đổi → mọi phiên hết hiệu lực. |
| `VAHAN_API_RUNNER_TOKEN` | Có | `<generate>` | ≥ 24 ký tự, khác `change-me`; chung cho mọi runner (KI-14). |
| `VAHAN_BROWSER_STATE_KEY` | Có | `<generate>` | 32 byte base64url; mã hóa browser state. **Mất khóa = mất state đã mã hóa**; sao lưu cùng DB. |
| `API_PORT`, `WEB_PORT` | Không | `8000`, `5173` | Cổng publish trên host. |
| `API_BIND_ADDRESS`, `WEB_BIND_ADDRESS` | Không | `127.0.0.1` | Đặt `0.0.0.0` chỉ sau reverse proxy HTTPS (KI-05). |
| `VAHAN_IMAGE_NAMESPACE`, `VAHAN_IMAGE_TAG` | Không | `vahan-automation`, `local` | Tên/tag 3 image ứng dụng. Image PostgreSQL **không** dùng hai biến này (pin digest, `docs/release/pins.md`). |
| `VAHAN_VCS_REF` | Không | (không đặt = `unknown`) | Chỉ lúc **build**: SHA commit ghi vào nhãn `org.opencontainers.image.revision` của 3 image ứng dụng (T29). `scripts/run-docker.py` đặt từ `git rev-parse HEAD`; `build-review-package.py` đặt = SHA của gói và từ chối nhãn khác; CI đặt = `github.sha`. Nhãn là khai báo, không phải provenance. Image đã `docker load` không đọc biến này lúc chạy. |
| `VAHAN_WORKER_REPLICAS` | Không | `auto` | `auto` = launcher chọn theo CPU/RAM (`--assess-only`), hoặc số nguyên dương (`--workers N`). Không có trần cứng (D-27 = d, KI-19); giới hạn song song mặc định 20 (D-34). |
| `VAHAN_API_CORS_ORIGINS` | Không | `VAHAN_ALLOWED_ORIGINS` rồi `http://localhost:${WEB_PORT},http://127.0.0.1:${WEB_PORT}` | Danh sách origin; production từ chối `*`. |
| `VAHAN_API_SOCKETIO_CORS_ORIGINS` | Không | như CORS ở trên | Cùng quy tắc. |
| `VAHAN_ALLOWED_ORIGINS` | Không | — | Nguồn mặc định cho hai biến CORS. |

Đặt cứng trong `compose.yaml` (không cấu hình qua `.docker.env`): `VAHAN_ENVIRONMENT=production`, `VAHAN_API_URL=http://api:8000`,
`VAHAN_URL=https://analytics.parivahan.gov.in/analytics/vahanpublicreport?lang=en`, `VAHAN_API_RUNNER_HEALTH_CHECKS=true`.

`scripts/test_config_template.py` kiểm template liệt kê mọi biến `${NAME:?…}` / `${NAME:-…}` của `compose.yaml`.

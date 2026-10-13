# Security review — bản nháp (T52a)

Phạm vi: những gì code/cấu hình ở repo thể hiện tại 13/10/2026. **Không** phải xác nhận của Security; accepted risk chỉ do Felix ký ở RG5 (D-20).
Nhãn: *Verified* (đã chạy), *Likely* (đọc source), *Not verified*.

| Mục | Trạng thái | Bằng chứng / ghi chú |
| --- | --- | --- |
| S1 — không log OCR thô; không quota OCR | Likely | `runner.mjs` không còn `OCR raw output` / `Auto-OCR result`; không limiter (D-18). Test: `tests/test_ocr_unlimited.py` (chưa chạy ở HEAD) |
| S3 — chống brute-force login | Likely | `limit_req` nginx cho `/api/auth/login` (`docker/nginx.conf`); bộ đếm DB Deferred (KI-22) |
| S5 — CORS Socket.IO | Likely | production từ chối `*` (`config.py`); `verification/test_production_config.py` |
| S6 — header bảo mật | Likely | `docker/security-headers.conf`; `scripts/test_container_security.py` kiểm CSP/nosniff/DENY trên stack thật |
| S7 — `/docs`, `/openapi.json` | Likely | tắt khi `VAHAN_ENVIRONMENT=production` (`main.py`); test trên stack thật |
| S8 — runner token riêng | **Deferred** | KI-14 |
| S9 — supply chain | Một phần | lock có hash (`requirements.lock`), base image pin digest; PostgreSQL = image chính thức pin digest (D-33, `pins.md`). Scan image chính thức: 25 finding HIGH/CRITICAL có bản vá, đều ở `gosu` (Go stdlib 1.24.6) — `evidence/T21a-postgres-official-scan/`. **Felix chấp nhận ngoại lệ hẹp (D-36, 13/10/2026; KI-25)**: gắn đúng digest, file, package; phần còn lại của policy giữ nguyên |
| S10 — hardening container | **Deferred** | KI-21 |
| S12 — tách quyền DB | Likely | service `migrate` + role `DB_APP_USERNAME` DML-only; `scripts/test_runtime_role_lifecycle.py` |
| O1 — monitoring tối thiểu | Một phần | `/api/ready` kiểm revision migration; probe + cảnh báo do vận hành sở hữu (`ops/runbook.md`) |

## Rủi ro còn lại

| Rủi ro | KI | Mức (D-03) |
| --- | --- | --- |
| CAPTCHA auto-solve, không có đường nhập tay; VAHAN đổi kiểu chữ có thể làm job lỗi hàng loạt | KI-02 | Major |
| Token UI trong `localStorage` | KI-03 | Major |
| Một token runner chung, ID tự khai | KI-14 | Major |
| Container chưa hardening | KI-21 | Major |
| Brute-force chậm/phân tán không bị chặn bởi nginx | KI-22 | Major |
| Không có trần cứng số runner/giới hạn song song | KI-19 | Minor |
| `gosu` (Go stdlib 1.24.6) trong image PostgreSQL chính thức | KI-25 | Minor (đề xuất) |
| Stack không tự cấp TLS | KI-05 | Major |

## Cơ chế CA tùy chỉnh

`docker/certs/*.crt` được nhúng vào image api/runner lúc build; **bản release phải build với thư mục này chỉ có `.gitkeep`, `README.md`**
(manifest `custom_ca_files: []`). Nơi nhận cần CA riêng nằm ngoài 1.0 (D-24 = A, KI-15).

## Dữ liệu nhạy cảm

Evidence/config snapshot chỉ ghi giá trị của khóa `plain: true` đã duyệt; mọi khóa khác chỉ `<set>`/`<unset>` (`scripts/config-snapshot.py`).
Backup chứa `.docker.env` và khóa mã hóa — kiểm soát truy cập.

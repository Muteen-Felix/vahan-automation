# T32 / T28b / T52a — build thử, cài thử từ gói, config snapshot và smoke trên `e46e39e627fa` (E-local, trial)

- ngày: 2026-10-15 (UTC 04:55–05:03)
- commit nguồn của gói: `e46e39e627fac5e0e8ad5f36ca22e51e61f3e40a` (BASE_SHA, branch `release/pre-go-live`). **Đây là trial, không phải artifact cuối.** Gói mới, không dùng lại gói của `f1e07f8a93a1`/`8865cecb0d01`.
- gói: `scripts/build-review-package.py --ref e46e39e627fa… --output-dir outputs/trial-e46e39e627fa --with-images`; manifest + sha256 + ID image: `../T32-package-manifest-e46e39e627fa.json` và bảng ở `../T32-not-run-e46e39e627fa.md` (phần "Cập nhật sau khi người dùng giải phóng RAM"). Gói thô (`images.tar` ~731 MiB, `source.zip`) **không** nằm trong repo.
- máy: Windows 11 + Docker Desktop/WSL2 (amd64), **máy dev**, không phải máy/VM sạch riêng (D-12 phương án B). Stack `vahan-automation` do người dùng dừng trước khi chạy (container `Exited`, volume `vahan-automation_postgres_data` còn nguyên; không bị đụng/không bị tạo lại bởi các lệnh dưới).
- **T32 (gói) và D3 (preflight VAHAN thật) là hai kết quả riêng.** D3 trong lần này = **NOT_RUN**. CI xanh và T32 không thay D3.

## Kết quả

| # | Việc | Lệnh / cách chạy | Kết quả |
| --- | --- | --- | --- |
| 1 | Cài theo INSTALL.md §2–§5 vào project tạm `vahan-rg1-95d3817faa`, cổng ngẫu nhiên, `--workers 1`, volume tạm | trình điều khiển dùng một lần (không commit): kiểm sha256 `source.zip`/`images.tar`, giải nén, `scripts/setup-docker.py`, đặt `VAHAN_IMAGE_NAMESPACE`/`TAG` + cổng, `docker image load`, so ID image, `scripts/run-docker.py --no-build --workers 1`, `compose ps`, snapshot, smoke, migrate lần hai, `down --volumes` | 8/8 bước exit 0; ID 4 image sau `load` **khớp** manifest; 4 container healthy (postgres, api, web, runner) và `migrate` Exited (0) — `results-install.json` |
| 2 | **T28b** `scripts/config-snapshot.py --env-file .docker.env --out … --image-ids` (bản trong gói) | chạy trên project thử | exit 0; 54 khóa, 15 plain, 0 `reviewErrors`; `docker_certs_sha256: none`; `composeFiles: [compose.yaml]`; kèm 4 ID image — `config-snapshot-e46e39e627fa.json`. **Quét:** 6 giá trị secret của env thử, 0 lần xuất hiện trong file; mọi khóa nhạy cảm là `<set>` |
| 3 | **T27** `scripts/release-smoke.py … --min-runners 1 --compose-project … --require-compose-checks` | chạy trên project thử | exit 0, **14 passed / 0 failed / 0 skipped** (health, ready postgresql, web, login, runner ONLINE, member 403 ở `run-history`/`users`/`audit`, admin đọc `run-history`, `migrate` exit 0, API dùng role DML-only S12) — `smoke.json` |
| 4 | INSTALL §7 bước 7: `docker compose run --rm migrate` lần hai | project thử | exit 0 |
| 5 | Kiểm gói offline `scripts/test-review-package.py --package-dir outputs/trial-e46e39e627fa --output-dir …` (không cờ D3) | project `vahan-review-b6957cc28b26` (+ `-restore`) | **54/54 pass**, `outcome = PACKAGE_PASS_D3_NOT_RUN`, exit 0, 5 phút 42 giây — `results-offline.json` (`driverScriptSha256` `b50da63c…2943e`) |

Nội dung kiểm gói (5): nạp image (ID khớp), launcher `--no-build`, readiness, route docs/cũ 404, đăng nhập, DB mặc định rỗng, CRUD profile + lịch Monthly (hai múi giờ), quyền member, restart API giữ phiên/state, import 1.000 dòng synthetic + Excel đủ 1.000 dòng, backup + restore vào project tách biệt (custom dump, binary dump, SQL dump, role runtime), Chromium sandbox + Tesseract thật, 13 test runner, 13 test UI trên bản build, kiểm fail-closed khi runner ngắt kết nối (dữ liệu **synthetic**, nhãn trong tên).

Dọn: cả 3 project tạm đã `down --volumes`; sau chạy `docker ps -a`/`volume ls` không còn container hay volume `vahan-rg1-*`/`vahan-review-*`; thư mục cài đặt tạm (chứa `.docker.env` thử) đã xóa (`installDirRemoved: true`). Còn lại: 3 tag `vahan-review/{api,runner,web}:e46e39e627fa`, `outputs/trial-e46e39e627fa/` (không commit).

## T52a — sai lệch giữa INSTALL.md trong gói và thực tế

INSTALL.md trong gói (sha256 `991a1441…363ecd`, = bản ở BASE_SHA):

1. **Câu về `/docs` còn lỗi thời.** §8 ghi "`/docs`, `/redoc`, `/openapi.json` bị tắt ở production", trong khi D3 ghi `/api/docs`, `/api/openapi.json`, `/api/redoc` → 404 (admin)/401 (không token) và `/docs`, `/openapi.json`, `/redoc` ở gốc web trả shell SPA 200 (quyết định S7). Bản sửa đã có **ở working tree của Felix (chưa commit)** — gói BASE_SHA chưa chứa nó. Test gói (`production-docs-disabled`) PASS.
2. Lần này **không** làm theo từng lệnh PowerShell bằng tay: trình điều khiển Python tái hiện các bước (dùng `python`, không `py -3`; cổng ngẫu nhiên thay `5173/8000`; `--workers 1` thay `<N>`; project `vahan-rg1-*`). Các điểm sau của INSTALL.md **chưa** được kiểm: `Get-FileHash`/`Expand-Archive` PowerShell, cổng mặc định, `--workers` mặc định `auto`, `stop`/`start` lại (§6), nâng cấp tại chỗ có dữ liệu (§7 bước 1–6).
3. INSTALL §4 yêu cầu sửa tay `VAHAN_IMAGE_NAMESPACE`/`VAHAN_IMAGE_TAG` trong `.docker.env`; nếu bỏ qua, compose dùng tag mặc định `local` (`compose.yaml`), không phải tag của gói (chưa thử bỏ bước này). Không phải lỗi, chỉ là bước dễ quên (T52a ghi nhớ cho TEST-ACCOUNTS/INSTALL).

## Điều kết luận được và không được

- [Fact] Gói dựng từ BASE_SHA cài được vào project/volume tạm, mọi kiểm gói và smoke ở trên pass trên máy dev này.
- [Fact] `config-snapshot-e46e39e627fa.json` mô tả môi trường **thử** của gói này. **Không** thể dùng làm snapshot/fingerprint cho build `fa04898` đã chạy D3 (ledger D3 giữ "chưa ghi"; `D3-ledger-reconciliation-e46e39e627fa.md` §1 vẫn đúng).
- **Không** kết luận: D3 trên VAHAN thật; thu thập báo cáo/CAPTCHA/một case thật; `--workers > 1`; nâng cấp tại chỗ; nền tảng khác; mạng đích thay TLS; image có nhãn revision (cả 3 image app `revisionLabel: null`, T29/RG3).
- Giới hạn: `release-smoke` và test gói chạy với dữ liệu giả lập; chạy song song không có stack live (đã dừng) nên không phản ánh áp lực RAM thật khi cùng chạy.
- CI trên commit chứa file này: Not verified (chưa push).

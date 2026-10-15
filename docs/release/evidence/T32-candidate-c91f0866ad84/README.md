# T32 / T28b / T52a — build thử và cài thử từ gói của candidate F `c91f0866ad84` (E-local, trial)

- ngày: 2026-10-15 (UTC 07:09–07:24)
- candidate F: `c91f0866ad841bc438c0b2e1d62e23c01a4d17f0` — SHA **đã qua CI** (6/6 job xanh, `../CI-c91f0866ad84.md`; mức job, theo ảnh của Felix). Gói dựng từ đúng SHA này bằng `git archive` trong **worktree sạch** của F (script của F, ngoài working tree của Felix). Không dùng lại gói của `e46e39e627fa`/`f1e07f8a93a1`.
- loại bằng chứng: **E-local, trial** — không phải D3 (preflight VAHAN thật **NOT_RUN**), không thay E-CI.
- máy: Windows 11 + Docker Desktop/WSL2 (amd64), máy dev; stack `vahan-automation` do Felix dừng trước khi chạy (không bị đụng). Không phải máy/VM sạch riêng (D-12 phương án B).

## Gói

| File | sha256 (khớp `manifest.files`) |
| --- | --- |
| `vahan-c91f0866ad84-source.zip` | `6f2dbe79d41db903c6fee5404f5153c8ae17632001401543c86d4d8c0ee535df` |
| `vahan-c91f0866ad84-images.tar` | `3b340d19038b3b4ca309ad9df7f09871f4d4a788e0745a4aaed06943cee1ee61` |

Gói thô (`images.tar` ~729 MiB) ở `outputs/candidate-c91f0866ad84/`, **không** nằm trong repo; manifest: `package-manifest.json`.

| Image | Nguồn | ID | Platform | Nhãn `org.opencontainers.image.revision` |
| --- | --- | --- | --- | --- |
| `vahan-review/api:c91f0866ad84` | tự build | `sha256:bb05114b0fe5…` | linux/amd64 | **`c91f0866ad841bc438c0b2e1d62e23c01a4d17f0`** |
| `vahan-review/runner:c91f0866ad84` | tự build | `sha256:51f4cfabc3a0…` | linux/amd64 | **`c91f0866ad841bc438c0b2e1d62e23c01a4d17f0`** |
| `vahan-review/web:c91f0866ad84` | tự build | `sha256:334dee447287…` | linux/amd64 | **`c91f0866ad841bc438c0b2e1d62e23c01a4d17f0`** |
| `docker.io/library/postgres:17.11-bookworm@sha256:3645570c…3826` | upstream, pin digest | `sha256:3645570cccdf…` | linux/amd64 | null (upstream) |

`build-review-package.py` (bản T29) từ chối gói nếu nhãn của image ứng dụng khác SHA; lần chạy này exit 0. Nhãn là **khai báo lúc build**, không phải provenance (`docs/release/pins.md`).

## Kết quả

| # | Việc | Kết quả |
| --- | --- | --- |
| 1 | Build gói: `build-review-package.py --ref c91f0866… --with-images` (từ worktree sạch của F) | exit 0; 3 image ứng dụng có nhãn = F |
| 2 | Cài theo INSTALL.md §2–§5 vào project tạm `vahan-rg1-6e804bee0d`, cổng ngẫu nhiên, `--workers 1`, volume tạm | 8/8 bước exit 0; ID 4 image sau `docker load` **khớp** manifest; `migrate` Exited (0) — `results-install.json` |
| 3 | **T28b** `config-snapshot.py --env-file … --image-ids` (bản trong gói) | exit 0; 54 khóa, 15 plain, 0 `reviewErrors`; 6 giá trị secret của env thử: 0 lần xuất hiện; kèm 4 ID image — `config-snapshot-c91f0866ad84.json` |
| 4 | **T27** `release-smoke.py … --require-compose-checks` | **14 passed / 0 failed / 0 skipped** — `smoke.json` |
| 5 | `docker compose run --rm migrate` lần hai | exit 0 |
| 6 | `test-review-package.py --package-dir outputs/candidate-c91f0866ad84` (không cờ D3) | **54/54 pass**, `PACKAGE_PASS_D3_NOT_RUN`, exit 0, 6 phút 6 giây — `results-offline.json` (`driverScriptSha256` `b50da63c…2943e`) |

Dọn: 3 project tạm đã `down --volumes` (0 container/volume `vahan-rg1-*`/`vahan-review-*` còn lại); thư mục cài tạm (có `.docker.env` thử) đã xóa; worktree dựng gói đã gỡ. Còn lại: 3 tag `vahan-review/{api,runner,web}:c91f0866ad84` và `outputs/candidate-c91f0866ad84/` (không commit).

Ghi chú vận hành: lần đầu chạy `test-review-package.py` bằng script **trong worktree** thất bại ở `real-installed-dashboard` (worktree không có `node_modules` của Playwright) — lỗi môi trường chạy test, không phải lỗi sản phẩm. Chạy lại bằng script ở working tree chính, đã kiểm chứng `git diff --name-only F HEAD -- apps scripts compose.yaml docker` rỗng (cùng nội dung với F; `driverScriptSha256` của kết quả `b50da63c…`).

## Điều kết luận được và không được

- [Fact] Gói dựng từ SHA đã qua CI cài được vào project/volume tạm; ID image khớp manifest; smoke 14/14; kiểm gói offline 54/54; snapshot không chứa giá trị secret.
- [Fact] 3 image ứng dụng mang nhãn revision = F; migration `0014a`/`0015`/`0016` chạy xong khi cài mới (`migrate` Exited 0).
- **Không** kết luận: D3 (preflight/thu thập VAHAN thật, R-rows); nâng cấp tại chỗ từ bản cũ có dữ liệu (INSTALL §7 bước 1–6); `--workers > 1`; Compose khi `migrate` thoát ≠ 0; nền tảng khác Windows; digest/bytes image trùng với bản sẽ giao (nhãn không chứng minh điều đó).
- `config-snapshot-c91f0866ad84.json` mô tả môi trường **thử** của gói này, **chưa** phải snapshot của stack chạy D3. Để ghi vào ledger D3, snapshot và fingerprint phải lấy từ chính stack đã chạy D3 trên candidate F.
- Giới hạn: máy dev, một runner, dữ liệu giả lập; E-CI chỉ ở mức job.

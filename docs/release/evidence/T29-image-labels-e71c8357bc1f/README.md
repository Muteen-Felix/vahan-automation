# T29 — nhãn revision/version cho 3 image ứng dụng (E-local, DB/stack dùng một lần)

- ngày: 2026-10-15
- source: working tree trên `e71c8357bc1fafebae11eb1130bd7e9e91401d38` + thay đổi của commit T29 chứa file này
- loại bằng chứng: **E-local** (không phải E-CI; chưa push). Nhãn là **khai báo lúc build**, không chứng minh bytes/digest image (xem `docs/release/pins.md`).
- quyết định áp dụng (Felix, PLAN §5.11 Q-C): `VERSION` lấy từ `VAHAN_IMAGE_TAG`; `unknown` chấp nhận ở đường dev, fail-closed ở đường release; không thêm `source`/`created`. §5.11.6 thay `PLAN_T29.md` về `defects.md` (không sửa) và cây sạch (áp cho candidate F).

## Thay đổi

| File | Nội dung |
| --- | --- |
| `apps/api-server/Dockerfile`, `apps/browser-runner/Dockerfile`, `apps/web-ui/Dockerfile` | `ARG VCS_REF=unknown`, `ARG VERSION=unknown`, `LABEL org.opencontainers.image.revision=$VCS_REF org.opencontainers.image.version=$VERSION` ở cuối stage cuối (sau mọi `COPY`/`RUN`, không phá cache) |
| `compose.yaml` | `build.args` của `api`, `runner`, `web`: `VCS_REF: ${VAHAN_VCS_REF:-unknown}`, `VERSION: ${VAHAN_IMAGE_TAG:-unknown}` |
| `scripts/run-docker.py` | trước `compose build`, đặt `VAHAN_VCS_REF` từ `git rev-parse HEAD` nếu chưa có (đường dev) |
| `scripts/build-review-package.py` | truyền `VAHAN_VCS_REF=<sha>` vào lệnh build; **từ chối** (exit ≠ 0) nếu nhãn của một image ứng dụng khác SHA — đường release fail-closed |
| `scripts/test_container_security.py` + `.github/workflows/platform.yml` | **đường CI**: job `container-build` truyền `VAHAN_VCS_REF: ${{ github.sha }}`; test từ chối chạy nếu biến khác `git rev-parse HEAD`, đưa biến vào env-file của `docker compose build`, rồi assert nhãn revision/version của `vahan-security-test/{api,runner,web}:round4` |
| `scripts/test_image_labels.py` (mới) + `scripts/test-manifest.json` + `platform.yml` | 7 test tĩnh; đăng ký `ci`/`workflow-run` |
| `docs/release/pins.md` | cập nhật trạng thái nhãn |

Không sửa `defects.md` (file đang modified của Felix). DEF-27: nên chuyển sang "đã làm ở E-local, chờ E-CI và candidate F" khi Felix commit file đó.

## Kết quả

| # | Lệnh | Kết quả |
| --- | --- | --- |
| 1 | `python -m unittest discover -s ../../scripts -p test_image_labels.py` (cwd `apps/api-server`) | **7 tests OK** |
| 2 | `python scripts/check-test-registration.py --require-history` | 94 file, 94 mục, **0 problem** |
| 3 | `python -m ruff check --config pyproject.toml ../../scripts ../../tools tests verification scripts` (đúng lệnh của workflow) | All checks passed |
| 4 | `docker compose --env-file <env tạm> config --format json` | `build.args` của api/runner/web = `VCS_REF` (SHA) và `VERSION` (tag); postgres không có `build` |
| 5 | `python scripts/test_container_security.py` (đường của job `container-build`; build thật 3 image, project `vahan-security-<hex>` dùng một lần) | exit 0 ("Container security checks passed…"); **đã assert** nhãn revision = `HEAD` và version = `round4` cho 3 image |
| 6 | `docker image inspect` sau lệnh 5 | api, runner, web: revision `e71c8357bc1fafebae11eb1130bd7e9e91401d38`, version `round4`; image PostgreSQL upstream: **không có** nhãn revision |
| 7 | Đối chứng âm tính: `docker compose build web` với env-file **không** có `VAHAN_VCS_REF` | nhãn revision = `unknown` (đường dev vẫn build được); image thử đã xóa |

Image `vahan-security-test/{api,runner,web}:round4` do lệnh 5 tạo vẫn còn trên máy (cùng tên với CI); không có container/volume `vahan-security-*`/`vahan-label-*` nào còn lại.

## Giới hạn (Not verified)

- E-CI: job `container-build` chưa chạy trên commit này (chưa push). `github.sha` ở `pull_request` là merge commit; evidence release chỉ dùng run từ `push`.
- Đường **release** (`build-review-package.py` từ chối nhãn sai) mới kiểm bằng đọc code + test tĩnh, **chưa** chạy gói thật (cần candidate F).
- Nhãn không phải provenance: không chứng minh image build từ đúng SHA. Image ID đổi theo SHA kể cả commit chỉ sửa `docs/**` (nhãn nằm trong config image) — chỉ build một lần ở candidate F.
- Image D3 đã chạy (`fa04898`) không có nhãn; D3 phải chạy lại trên candidate F.
- Lệnh 5 chạy với working tree có thay đổi chưa commit của T29 nhưng nhãn là `HEAD`; bằng chứng cuối cùng phải lấy từ CI trên commit đã push.

## Cập nhật sau CI run #23 trên `f43ede1` (2026-10-15)

- **Đỏ:** 3 job `Source and browser tests` (ubuntu, windows, macos), cùng một lỗi ở step "Install and test API": `scripts/test_config_template.py::test_template_and_reference_cover_all_compose_variables` — `VAHAN_VCS_REF` (biến mới trong `compose.yaml`) thiếu ở `docs/release/config/config-template.env` (T26). Nguyên nhân do T29; lỗi sót của tác giả: bộ test này không nằm trong danh sách đã chạy local trước khi push.
- **Xanh trên cùng SHA:** `PostgreSQL verification (Ubuntu)`, `Test registration (Ubuntu)`, **`Linux container packaging (Ubuntu)`** — job sau chạy `test_container_security.py` với `VAHAN_VCS_REF: ${{ github.sha }}`, tức assert nhãn revision/version của 3 image đã **xanh ở E-CI** trên `f43ede1`.
- **Sửa:** khai báo `VAHAN_VCS_REF` trong `config-template.env` (dòng comment) và `config-reference.md`.
- **Kiểm local sau sửa** (đúng các lệnh của job `native-tests`): `test_config_template` 2 OK; toàn bộ danh sách `unittest` trong step "Install and test API", `test_ui_diagnostics.py`, `test-user-state-codec.py`, ruff (lệnh của workflow), `npm run check` + 11 script test của runner, `npm run check`/`build` của dashboard — đều pass. `npm run test:platform` đã pass trước đó (web-ui không đổi).
- E-CI cho commit sửa: Not verified (chờ push).

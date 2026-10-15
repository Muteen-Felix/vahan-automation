# D3 / T24b — đối chiếu báo cáo `D3-2026-10-14.md` với từng ledger `R*.md` (candidate `e46e39e627fa`)

- ngày: 2026-10-15
- BASE_SHA: `e46e39e627fac5e0e8ad5f36ca22e51e61f3e40a`; SHA do ledger khai báo: `fa048989f008ef30bf575e7cbf73b0c661e7019c` (trừ R1 và R8-eta)
- phạm vi: **chỉ đối chiếu và chạy `evidence-check.py`**. Không sửa ledger `R*.md` (untracked, của Felix; Q2 = A), không sửa báo cáo D3, không nâng trạng thái nào. Kết quả "Not verified" giữ nguyên.
- nguồn đã đọc: `docs/release/evidence/D3-2026-10-14.md` (tracked), 19 ledger `docs/release/evidence/R*.md` (working tree), `docs/release/path-map.json`.

## 1. SHA, snapshot, fingerprint — chỉ ghi khi có bằng chứng

| Trường | Hiện trạng trong 19 ledger | Bằng chứng có thể dùng | Kết luận |
| --- | --- | --- | --- |
| `sha` = `fa04898…` | 17 ledger (R2–R15, R17 và R8-vahan-d3) | Chỉ lời người duyệt "stack dựng từ `fa04898`" + thời điểm tạo image (~2026-10-14 10:26Z) sau commit (09:53Z). Image **không có** nhãn `org.opencontainers.image.revision`; `runner-3` khác digest `runner-1/2` (`sha256:d8c95f93…` vs `a9bed16a…`) | **Khai báo, chưa kiểm chứng độc lập.** Giữ `build: Not verified` như ledger đã ghi |
| `sha` R1 | `Not verified` | không có kết quả Pass đầy đủ trên build mới | đúng; `evidence-check` ⇒ Reopened (đúng ý) |
| `sha` R8-eta | `8865cecb…` (synthetic) | `R8-eta.md` + `R8-eta/*.json` | giữ; là bằng chứng E-local synthetic, **không** thay D3 R8 |
| `config-snapshot` | `chưa ghi` (mọi ledger) | không có file snapshot nào cho build đã chạy D3; T32/T28b cho BASE_SHA **Not run** (`T32-not-run-e46e39e627fa.md`) | **không ghi**; không thể dựng hồi tố |
| `build-fingerprint` | `chưa ghi` (mọi ledger) | không có | **không ghi** |

Ngoài ra: header ledger dùng `- config-snapshot:`/`- build-fingerprint:`, trong khi `path-map.json` (`ledger_header`) và `evidence-check.py` đọc `- snapshot:`/`- fingerprint:`. Hiện hai trường đều "chưa ghi" nên chưa gây sai kết quả, nhưng khi có file thật phải dùng đúng tên khóa mà checker đọc (hoặc sửa checker/tài liệu cho khớp).

## 2. Đối chiếu từng dòng

| Row | Ledger `result` | Báo cáo D3 (build mới `fa04898`) | Khớp? | Khoảng trống / lưu ý |
| --- | --- | --- | --- | --- |
| R1 | Pass một phần (health/ready) | O1 Pass (đợt 6). Đăng nhập + restart giữ dữ liệu: Pass ở build **cũ** (đợt 1) | Khớp, nhưng ledger **thiếu** | Báo cáo mục "R7/R7b — build mới" có restart API trên build mới (03:45:44Z): danh sách lịch trước/sau giống hệt, phiên admin còn hợp lệ — ledger R1 ghi "restart chỉ đo ở build cũ". Chưa có jobs/profiles/history trước-sau ở build mới. Đề xuất ghi chú, không đổi `Pass một phần` |
| R2 | Pass (người duyệt, bằng lời) | Pass (người duyệt) + phần Claude đo ở build cũ | Khớp | Không log/ảnh; idle 60 phút và admin logout chỉ bằng lời |
| R3 | Pass (đợt 4) | Pass: 36 State, 14 RTO A&N; preview 3/14/196 case | Khớp | — |
| R4 | Pass (đóng 2026-10-15) | Pass; "tải file" ghi **trùng R5** theo quyết định của người duyệt | Khớp | Không có file Excel/screenshot theo lượt ở build mới ⇒ SHA file sau khôi phục chỉ kiểm ở build cũ |
| R5 | Pass (người duyệt, UI) | Bảng đợt 1 (build cũ) còn dòng **"Hộp thoại xác nhận trên UI: Not run"**; đợt 6 ghi Pass bằng lời | Khớp (dòng cũ đã bị thay thế) | Bằng chứng build mới = lời nói. E-local T16 (`T16-export-e46e39e627fa.md`) bổ sung ở tầng test, **không** thay D3 |
| R6 | Pass phần cốt lõi; KI-27 | Pass (10:31–10:48Z); defect "một runner lỗi khóa cả đội" ⇒ KI-27 Deferred | Khớp | Báo cáo còn câu "KI-27 … chưa commit" đã lỗi thời (KI-26/27 ở `e46e39e`); ledger R6 đã ghi chú |
| R7 | Pass | Pass (Once chạy đúng giờ, 3/3 case) | Khớp | — |
| R7b | Pass | Monthly + Daily 422 + restart giữ lịch Pass; múi giờ ≠ `Asia/Ho_Chi_Minh` chỉ ở build cũ | Khớp | `Asia/Kolkata` ở build mới: Not verified (ledger đã ghi) |
| R8 (VAHAN) | Pass theo **tiêu chí mới**; theo tiêu chí cũ Not verified | Lượt `3b1937e0…`: 82,9 phút, 1676 case; 50–75%: median 7,6% (≤ 25%) / max 71,4%; 75–100%: median 2,7% (≤ 15%) / max 8,1%; 3 mẫu offline tính vào sai số | Khớp | Số liệu ledger = báo cáo. Hai lượt trước (đợt 5) ghi "Not verified — gián đoạn" theo tiêu chí cũ; không dùng. ETA tính lại bằng port JS, không phải `remainingMs` trên UI (giới hạn đã nêu). **`PLAN.md` D-28 chưa sửa** (file của Felix) |
| R8 (synthetic) | (không có dòng `result`) | báo cáo: "số liệu hiện có là synthetic (`R8-eta.md`)" | Khớp | `sha: 8865cecb`; Reopened vì runtime + global đã đổi |
| R9, R9b | Pass (đợt 4) | maxWorkers 1/3/5 ⇒ đồng thời tối đa 1/3/3; pause/resume | Khớp | `maxWorkers=5` chỉ chạy 3 vì có 3 runner (giới hạn hiệu dụng) |
| R10 | Pass | Pass (tắt/xóa lịch khi lượt đang chạy) | Khớp | — |
| R11 | Pass | Pass (kill `runner-2` giữa lượt) | Khớp | Phát hiện: runner thay thế không tham gia lượt đang chạy; `runner-1` không tự khởi động lại — chưa có KI/defect tương ứng trong ledger |
| R12 | Pass | Pass (chặn DNS, tự tiếp tục sau ~12 s) | Khớp | — |
| R13, R15 | Pass | `POST /api/jobs` + `updateKind`… ⇒ 422 ×6; `/api/maker-updates`, `/ui-health/schedule`, `/run-now` ⇒ 404 | Khớp | Ledger R15 còn dòng đợt 6 "(một phần)…chưa thử 422" — đã được dòng 02:29Z thay thế |
| R14 | Pass (mẫu nhỏ) | Pass (log không có chuỗi OCR thô; không job kẹt `WAITING_CAPTCHA`) | Khớp | Mẫu nhỏ (~9 request ở đợt 3; ≥ hàng trăm case ở đợt 4) |
| R16 | **không có ledger** | **không có trong báo cáo** | — | Row `R16` có trong `path-map.json` (Phụ lục D: giao thức cần người đối chiếu độc lập). Không tính vào D3 |
| R17 | Pass (người duyệt) | Pass: một lượt một dòng, retry không thêm dòng (đo ở build mới); member 403 (build cũ) | Khớp | Lưu ý báo cáo: `batch-queue/sessions/{id}.status` vẫn `RUNNING` khi mọi case đã xong, và "Unnamed filter" khi session tạo qua API — chưa kiểm UI |

Mục S3/S5/S6/S7/O1 trong báo cáo không có ledger `R*` (không có row tương ứng trong `path-map.json`); S7 đã được chấp nhận (người duyệt 2026-10-15), checklist E2E #15 đã sửa kỳ vọng ở working tree của Felix.

## 3. `evidence-check.py` (nguyên văn tóm tắt; exit code 1 = có Reopened)

`python scripts/evidence-check.py --to e46e39e627fac5e0e8ad5f36ca22e51e61f3e40a` ⇒ `ledgers 19, valid 0, reopened 19`:

| Ledger | sha | Lý do Reopened |
| --- | --- | --- |
| R1 | — | `ledger has no full 40-hex sha` |
| R2–R7b, R8-vahan-d3, R9, R9b, R10–R15, R17 (17 ledger) | `fa048989…` | `global-impact path changed: apps/api-server/pyproject.toml`; `…/requirements-dev.lock`. Kèm `buildWorkflowChanged: true` + note "E-CI phải chạy lại trên commit đích" (không phải lý do Reopened) |
| R8-eta (synthetic) | `8865cecb…` | global: migration `0016`, `pyproject.toml`, `requirements-dev.lock`, `apps/browser-runner/package.json`, `runner.mjs`; runtime path chưa ánh xạ: `apps/browser-runner/health-cookie-recovery.mjs` |

Kiểm tra công cụ: `python -m unittest scripts/test_evidence_check.py` ⇒ 31 test OK. `evidence-check.py --from fa048989… --to fa048989…` ⇒ 19/19 Valid (đường lành mạnh của checker).

### Phân tích (không đổi verdict)

- Từ `fa04898` đến BASE_SHA, các file dưới `apps/` thay đổi chỉ gồm test (`apps/api-server/tests`, `verification`), `pyproject.toml`, `requirements-dev.lock` (`git diff --name-only fa04898 HEAD`, Verified). **Không** có `app/*`, migration hay `runner.mjs` đổi.
- Hai file global đổi chỉ thêm `ruff` (dev dependency + cấu hình `[tool.ruff.lint]`), commit `1f6da24`. Image api cài `requirements.lock`, không phải `requirements-dev.lock` (`apps/api-server/Dockerfile:7-8`). **[Likely]** image api không đổi nội dung runtime vì hai file này; **Not verified** (không build, T32 Not run).
- Nhưng `path-map.json` phân loại cả hai là `global_impact` ⇒ **Reopened là đúng theo quy tắc hiện hành** (ghi chú trong `PLAN_T29.md`: "quyết định #19 = A"). Muốn đổi phải đổi `path-map.json` (Felix quyết; không nằm trong phạm vi lần này).

## 4. Đề xuất chỉnh ledger (CHƯA áp dụng — Felix tự áp nếu đồng ý)

1. **R1**: thêm một dòng ghi nhận restart API trên build mới (03:45:44Z, lịch trước/sau giống hệt) nhưng giữ nhãn "chỉ một phần".
2. **Mọi ledger đợt 4–6**: thêm dòng "sha khai báo bởi người duyệt; không có nhãn revision; xem `D3-ledger-reconciliation-e46e39e627fa.md` §1". Không đổi `sha`.
3. **R11**: bổ sung hai quan sát chưa thành defect/KI: runner thay thế không tham gia lượt đang chạy; runner bị `docker kill` không tự khởi động lại (không restart policy).
4. **Tên khóa** `config-snapshot`/`build-fingerprint` ↔ `snapshot`/`fingerprint` (xem §1).
5. **`PLAN.md` D-28**: cập nhật tiêu chí mới (mất mạng VAHAN tính vào sai số; điều kiện còn lại giữ nguyên).

## 5. Việc còn mở để dòng D3 đạt cho candidate

- Build candidate F có nhãn revision (T29 / `PLAN_T29.md`) và chạy lại D3 trên đúng build đó, kèm `config-snapshot` + `build-fingerprint` (cần T32 chạy được).
- E-CI cho commit candidate (cần Felix push).

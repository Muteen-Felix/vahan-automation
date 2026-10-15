# T16 — Export Excel: xác nhận khi lọc, đủ mọi dòng khớp, kể cả > 100 dòng (E-local)

- ngày: 2026-10-15
- source: `e46e39e627fac5e0e8ad5f36ca22e51e61f3e40a` (working tree không sửa code/test)
- loại bằng chứng: **E-local**. Không phải E-CI, không phải D3 (D3 R5 trên VAHAN thật là xác nhận bằng lời của người duyệt, xem `D3-ledger-reconciliation-e46e39e627fa.md`).
- môi trường: PostgreSQL 17.11 dùng một lần (như `T15b-daily-removal-e46e39e627fa/README.md`), DB `vahan_results_platform_annual_test`; Node v22.23.3, Playwright Chromium có sẵn của `apps/browser-runner`.

## Lệnh

| # | Lệnh | Kết quả |
| --- | --- | --- |
| 1 | `VAHAN_RESULT_TEST_DATABASE=vahan_results_platform_annual_test python -m pytest verification/test_annual_reports.py -v` (cwd `apps/api-server`) | **21 passed** (15,7 s) |
| 2 | `npm run check` (cwd `apps/web-ui`; `tsc -b`) | exit 0 |
| 3 | `npm run test:platform` (cwd `apps/web-ui`; gồm `scripts/test-annual-reports.mjs`) | exit 0, 13 file test; dòng "Annual reports UI: … exports and responsive layout passed." (1 phút 56 giây) |

Không thêm/sửa test: sau khi đọc test và source, các ca yêu cầu đã có (xem bảng).

## Export có lọc State/RTO (kết quả riêng)

| Yêu cầu | Bằng chứng (đã chạy, pass) |
| --- | --- |
| Có hộp thoại xác nhận khi lọc; Hủy ⇒ không gửi request | UI `test-annual-reports.mjs:11-14` (`exportFiltered`): hộp thoại khớp `/matching the State\/RTO filters/`, `dismiss()` ⇒ `exportRequests.length` không đổi. Source `AnnualReports.tsx:73-75` (`window.confirm` luôn chạy, chỉ đổi chữ khi `hasSearch`) |
| Chấp nhận ⇒ request mang đúng `state`/`rto`/`year`/`dataset`, **không** `offset`/`limit`, **không** `confirmAll` | UI `:15-26`; ba lần lọc: `andaman` (200 dòng khớp trên fixture 1.000 dòng), `andaman`+`AN1`, `AN1` |
| Nút bị khóa khi chờ lọc áp dụng hoặc lọc không có dòng | UI `:150`, `:165-168` (`isDisabled`) |
| Xuất **đủ** mọi dòng khớp, vượt 100 dòng | pytest `test_export_one_thousand_rows_and_every_state_rto_match_across_pages`: dữ liệu 1.000 dòng (450 + 150 + 250 + 150); lọc `ASSAM` ⇒ **600** dòng, `AS27` ⇒ **450**, `assam`+`UDALGURI` ⇒ **450**; mỗi trường hợp: `X-Report-Row-Count` = số dòng khớp = số dòng workbook (mở bằng openpyxl), tập maker khớp, STT 1…N, 100 dòng đầu = trang 1 của màn hình |
| Đọc lại từng trang so với export | pytest `test_every_page_of_one_thousand_rows_matches_the_export_row_for_row` |
| Lọc khớp 151 dòng, tên thật/null/0, ô bắt đầu `=` lưu dạng chuỗi | pytest `test_export_filtered_reads_all_pages_real_name_null_zero_and_safe_text`, `test_spreadsheet_formula_prefixes_are_exported_as_text` |

## Export all (kết quả riêng)

| Yêu cầu | Bằng chứng (đã chạy, pass) |
| --- | --- |
| Có hộp thoại xác nhận; Hủy ⇒ không tải | UI `:170-173`: thông điệp khớp `/Export all 1,000 manufacturer rows.*2026/`; sau Hủy `exportRequests.length` vẫn 3 |
| Chấp nhận ⇒ `state=''`, `rto=''`, `year=2026`, `confirmAll=true`, không phân trang | UI `:174-184` |
| API từ chối khi không lọc và không `confirmAll` | pytest cùng test 1.000 dòng: `confirm_all=False` ⇒ `HTTPException 409`; `test_export_all_requires_confirmation_and_respects_shared_scope_and_year` |
| Xuất đủ **1.000** dòng | pytest 1.000 dòng: `confirm_all=True` ⇒ `X-Report-Row-Count` = 1000 = số dòng workbook (`:332-333` của test khác cũng kiểm `'1000'`) |
| HTTP: auth, xác nhận, trả nhị phân Excel | pytest `test_http_export_auth_confirmation_and_binary_excel_response` |

## Giới hạn (Not verified)

- UI test dùng **fixture API** (`page.route`), tải về là `workbook-download-fixture`: **không** mở file Excel thật qua UI. Số dòng thật của file chỉ được kiểm ở tầng API/workbook (pytest).
- Chưa kiểm export trên dữ liệu VAHAN thật/trên gói đã cài (T32 không chạy được: xem `T32-not-run-e46e39e627fa.md`). D3 R5 (UI thật) = xác nhận bằng lời, không kèm ảnh/log.
- CI trên commit chứa file này: Not verified (chưa push).
- DEF-09/DEF-35 trong `defects.md` (file đang sửa dở của Felix): đủ căn cứ để chuyển trạng thái "chờ test" sang E-local pass; **tôi không sửa** file đó (Q2 = A).

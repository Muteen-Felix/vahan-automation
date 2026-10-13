# Đợt 5 — bằng chứng trước duyệt

> Kết quả dưới đây là bằng chứng lịch sử của gói Đợt 5. Lỗi UI Health được
> sửa trong [lần rà soát Đợt 1–5](round1-5-audit.md); log cũ được giữ nguyên.

Đã hoàn tất thu thập bằng chứng, **chưa phải phê duyệt go-live**. Bộ kiểm đầy
đủ trả exit **1**: **55/56 kiểm tra pass**, một defect sản phẩm được tái hiện
và giữ mở. Không skip/xfail để đổi kết quả. Không sửa sản phẩm ngoài phạm vi.

## Commit và gói đã kiểm

Source/package SHA: **`e40a402987426666a41ce1201ee25ac0ff98b02e`**.
Commit này gồm công cụ đóng gói, hướng dẫn cài/runbook, test runtime và UI cài
thật. Commit bàn giao tiếp theo chỉ bổ sung báo cáo/log, không đổi runtime đã
kiểm. Xem `git rev-parse HEAD` để lấy SHA bàn giao cuối cùng.

- [Manifest với SHA-256 và ID của cả bốn image](evidence/round5/package-manifest.json).
- [Build log thật, build process exit 0](evidence/round5/package-build.txt).
- [Toàn bộ 56 kết quả/lệnh/exit code](evidence/round5/results.json).

| Artifact | SHA-256 |
| --- | --- |
| `vahan-e40a40298742-source.zip` | `da97ec4eb424a42881a37f4628b2437dcbb89ea26507b7d90422bf1732454975` |
| `vahan-e40a40298742-images.tar` | `f002ea2148605bd1b1ac44c9f5ca9c1391480e275a22bf639f367de9e9b8306e` |

Source zip 748 KB xấp xỉ, image tar 766 MB xấp xỉ; manifest có hash để đối
chiếu chính xác. Đã kiểm 312 entry trong source archive: không chứa `outputs/`,
secrets, Git metadata hoặc CA riêng. Package không lấy thay đổi chưa commit.

## Lệnh và môi trường

```powershell
python scripts/check-doc-links.py
python scripts/build-review-package.py --ref e40a402987426666a41ce1201ee25ac0ff98b02e --with-images --output-dir diagnostics/round5-package-reviewed
python scripts/test-review-package.py --package-dir diagnostics/round5-package-reviewed --output-dir diagnostics/round5-install-reviewed --live-case
```

Thư mục output phải mới; không ghi đè gói/bằng chứng có sẵn. Test bắt đầu
**2026-10-12 14:17:43 UTC**, kết thúc **14:22:57 UTC**; log giữ timestamp UTC.
Host Windows: Python 3.12.10, Node 24.19.0, Docker Compose 5.5.1, Docker Desktop
Linux containers. Runner image dùng Node 22, Chromium **153.0.8010.12**, UID
**1000**, sandbox bật, Tesseract thật qua stdin. Browser UI host dùng Chrome.

Script load image tar, xác minh từng image ID, giải nén source vào thư mục mới
và chạy launcher thật `--no-build --workers 1`. Hai project disposable
`vahan-review-2d456f37b8d2` và suffix `-restore` có DB/volume/secrets riêng.
Chỉ hai project đó được dọn; không deploy/restart stack đang dùng.
Không sửa/xóa file trong `outputs/`.

## Kết quả trên bản build

| Chức năng | Kết quả và phạm vi | Bằng chứng |
| --- | --- | --- |
| Cài từ image/source gói | Load, kiểm image ID, launcher, migration và API/web/runner healthy | [Launcher](evidence/round5/fresh-install-launcher.txt), [container status](evidence/round5/final-container-status.txt) |
| Readiness, docs, route cũ | API/nginx ngoài Docker hoạt động; API docs production và route đã gỡ 404 | [Results](evidence/round5/results.json) |
| Auth/phân quyền/tài khoản | Login thật; member chỉ reports, history/schedules/users/profiles 403; admin đổi role được | [UI thật](evidence/round5/real-installed-dashboard.txt), [Results](evidence/round5/results.json) |
| Profile/lịch/time zone | CRUD/revision 1→2, lịch tháng Việt Nam/Ấn Độ, `workerCount=999` bị bỏ qua | [Results](evidence/round5/results.json) |
| Session/state/API restart | Token/state tiếp tục hợp lệ sau restart API của project thử | [Restart](evidence/round5/api-restart.txt), [Results](evidence/round5/results.json) |
| Dữ liệu mặc định | Cài mới không có report/dataset mẫu; fixture nhập sau có nhãn SYNTHETIC | [Results](evidence/round5/results.json) |
| Excel 1.000 dòng | API xuất đủ 1.000 dòng cho all/State/RTO/combined, đọc XML workbook kiểm 1.003 dòng gồm 3 header; UI cancel/accept confirmation và download thật | [UI thật](evidence/round5/real-installed-dashboard.txt), [Results](evidence/round5/results.json) |
| Backup/restore | Dump/hash/pg_restore thật; 1.000 reports tổng hợp, member/state phục hồi; API lifespan mở bằng role DML-only | [Restore](evidence/round5/restored-api-lifespan-and-data.txt) |
| Chromium/OCR | Browser thực chạy non-root, sandbox bật; Tesseract nhận đúng chữ tổng hợp từ screenshot qua stdin; không log chữ OCR thô | [Runtime](evidence/round5/chromium-sandbox-and-real-tesseract.txt) |
| Runner DOM/flow | 13 script chạy trong runner image: filters/options/contract/navigation/recovery/results/lifecycle/main-report-save/OCR guard | [Results](evidence/round5/results.json) |
| UI chức năng | 13 nhóm test trên assets production Nginx: ETA, zone, session, reports, profile, health, navigation, schedules, history/sample, accounts, outage, permissions | [Results](evidence/round5/results.json) |
| VAHAN preflight | DOM thật qua runner/API, HTTP 200, allowed=true, không bypass TLS | [Preflight](evidence/round5/live-preflight.json) |
| VAHAN case thật | Assam/BARPETA–AS15, 2026, ACTIVE_COMPLIANT, Maker/Month Wise; COMPLETED, 1 Apply, 104 rows/1.040 month values commit SQL | [Case thật](evidence/round5/live-single-case.json), [runtime logs](evidence/round5/runtime-logs.txt) |
| UI Health disconnect | **FAIL**: sau grace, blocked true→false, diagnostic vẫn được giữ | [Defect thật](evidence/round5/ui-health-disconnect-finding.json) |

Case thật: job `4ae20822-18e1-4a30-a767-cc9c08bf5e61`, session
`83eb9dab-6a6f-4020-9e52-336abaa4bc72`. SQL commit lúc
`2026-10-12T14:22:22.430630Z`, checksum workbook
`6912144ab555ef4f5faa4bb35b7ca26c1e901ea544855c648e6ac061b4266222`.
Không warning/conflict/duplicate/invalid cell trong lần nhập đó. Kết quả
single-case không đại diện mọi State/RTO hay độ chính xác OCR dài hạn.

Các test UI có route/socket fixtures chỉ xác nhận chức năng trên **build thật**;
không biến dữ liệu fixture thành dữ liệu VAHAN thật. Script
`test-installed-dashboard.mjs` dùng API/session/SQL thật, không mock. Ba nhóm
timing/time-zone kiểm module tính toán, không phải render browser. 1.000 dòng
thử Excel là dữ liệu tổng hợp có nhãn; 104 dòng case thật là kết quả VAHAN.

Ảnh giao diện thực với dữ liệu tổng hợp:
[desktop](evidence/round5/ui-screenshots/installed-reports-1440.png),
[mobile](evidence/round5/ui-screenshots/installed-reports-390.png).

## Defect còn mở

| ID | Trạng thái | Chi tiết/nguồn |
| --- | --- | --- |
| R5-UIH-001 | Sản phẩm, tái hiện được, chưa sửa | `current()` ở `apps/api-server/app/repositories/ui_contract.py` lọc `runnerErrors` theo runner `connected=True`. Sau grace disconnect, runner rời pool SQL và `blocked` mất dù lỗi vẫn tồn tại. `_expire_disconnected_runner()` ở `app/realtime/runner_events.py` và `PostgresRunnerRegistry.remove_by_socket()` là đường disconnect. Đã báo trước khi tiếp tục; Round 5 không sửa logic. |
| R4-SEC-001 | Phát hiện bảo mật chưa đóng | Scan Đợt 4 ghi 236 HIGH/CRITICAL chưa có vendor fix, xem [báo cáo Đợt 4](round4-security-validation.md). Không gọi scan sạch. Số này là bằng chứng Đợt 4, không phải scan local mới của package Đợt 5. CI sẽ scan image build trên commit được push. |

R5-UIH-001 được kiểm bằng diagnostic DOM **cố ý không hợp lệ, có nhãn
SYNTHETIC**, gửi qua HTTP runner token trong DB thử; dừng runner thật, chờ hết
grace đến khi runner rời API pool, rồi đọc trạng thái lại. Diagnostic không
mất trong SQL; cờ UI mất. Đây không phải lỗi do VAHAN đổi form.

Các lỗi trong lần chạy harness trước (URL history thiếu prefix, lookup header
phân biệt hoa/thường, hash-only navigation khác document reload, đọc blocked
trước khi grace hết) đã sửa **trong test/tài liệu** và chạy lại toàn bộ. Không
quy các lỗi harness này thành defect sản phẩm, không skip test.

## Chưa kiểm trên gói này

- Run 100 case/30 phút và sai số ETA thực tế; không lặp lại bằng chứng Đợt 3
  thành kết quả của gói mới. ETA/pause/stall ở đây có fixture, một case live.
- Concurrency lịch 0/1/3 runner, lease expiry, late result và mất mạng trong
  lúc case VAHAN thật đang chạy. Test Đợt 2–4/CI có phạm vi riêng; không chứng
  minh các tình huống đó đã diễn ra trong case live Đợt 5.
- Đầy đủ mọi tổ hợp State/RTO/year/profile, tỷ lệ OCR dài hạn, retry/pause/resume
  trong một run VAHAN thật dài. Single-case thành công không đủ để kết luận.
- Upgrade từ dữ liệu production thật và restore với browser login state thật;
  drill ở đây dùng DB mới/dữ liệu tổng hợp. Migration 0012→0014 và role upgrade
  có bằng chứng Đợt 4, không diễn tập trên DB production trong Đợt 5.
- Cài package trên máy Windows thứ hai, Linux/macOS hoặc kiến trúc ARM64.
  Image bundle hiện được build/test trên Docker Linux amd64 tại host này.
- CA/proxy công ty, public TLS/reverse proxy/LAN, load/HA và kịch bản disaster
  recovery production. Navigation stock image tại thời điểm test đã pass;
  không suy ra mọi mạng đều tin cùng certificate chain.
- Đối chiếu nghiệp vụ từng số với báo cáo nguồn độc lập; đã kiểm parse/SQL
  commit và counts, chưa có audit nghiệp vụ độc lập của 104 dòng VAHAN.

Các mục này được công bố cho vòng duyệt tiếp theo, không được đánh dấu pass.
Hướng dẫn sử dụng nằm ở [cài đặt](deployment.md) và [runbook](runbook.md).

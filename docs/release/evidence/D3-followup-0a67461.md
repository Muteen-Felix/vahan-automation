# Bổ sung checklist sau D3 — 17/10/2026

Candidate giữ nguyên: `0a6746187e820efd23e2e8e96f37eb3aa1efcba6`, version `1.0.0`.
Manifest SHA-256: `53692e7e05f587595628a37fa338ce1508f79847b07ff09d051feeb51591a3c4`.
Images TAR SHA-256: `9d2a1004d2dad762cc087c705590692eb5aaee49ebc7f498c5ae267811a45cc4`.

Đây là kiểm tra bổ sung **sau D3**, không phải chạy lại D3 hoặc sửa ledger đã niêm phong.
Source ZIP, manifest và images TAR được đối chiếu checksum, không sửa/rebuild.
Docker Desktop được khởi động lại; các container staging D3 cũ không còn ở thời điểm kiểm tra.
Các phép thử mới dùng image ID bất biến của gói trong môi trường tạm, DB dùng tmpfs riêng;
không chạy workload VAHAN thật hoặc dùng volume dữ liệu cũ.

Bản tóm tắt đã rà soát được đưa lên Git: [D3-followup-0a67461-summary.json](D3-followup-0a67461-summary.json).
Theo yêu cầu tiếp theo ngày 17/10/2026, evidence mới được đưa lên Git cùng gói release qua Git LFS.
Chi tiết phạm vi công bố và các thư mục cũ đã xóa: [PUBLICATION.md](../../../outputs/followup-0a67461-20261017/PUBLICATION.md).

## Checklist trong ảnh

| Mục | Kết quả và giới hạn | Bằng chứng |
| --- | --- | --- |
| 3 — Snapshot/fingerprint | Snapshot mới từ cấu hình staging lưu lại khớp cấu hình snapshot 16/10; 3 runner. Fingerprint mới đo trực tiếp đúng image gói. Không coi đây là snapshot runtime lịch sử khi container D3 còn chạy. | [snapshot-provenance.json](../../../outputs/followup-0a67461-20261017/snapshot-provenance.json), [build-fingerprint.json](../../../outputs/followup-0a67461-20261017/build-fingerprint.json) |
| 4 — DEF-22/27/32 | Nhãn revision/version và platform của 3 image app khớp gói. Chromium chạy sandbox bằng non-root với seccomp gói; Tesseract nhận đúng ảnh chữ synthetic. nginx thực tế trả `Server: nginx`, có `server_tokens off` và CSP. Có phát hiện font từ xa bị CSP chặn trong gói gốc; xem bên dưới. | [identity.json](../../../outputs/followup-0a67461-20261017/identity.json), [container-runtime.json](../../../outputs/followup-0a67461-20261017/container-runtime.json), [nginx-runtime.json](../../../outputs/followup-0a67461-20261017/nginx-runtime.json) |
| 5 — DEF-15 | Ba test DB PASS: lịch lưu `9999` chỉ dùng 1/3 worker thực; test bổ sung pause, lưu `2³¹−1`, resume vẫn dùng 2 runner, cùng session, hoàn tất 3 case không trùng/mất. Test mới mount ngoài image; code API vẫn là image gốc. | [def15-unittest.log](../../../outputs/followup-0a67461-20261017/def15-unittest.log), [def15.json](../../../outputs/followup-0a67461-20261017/def15.json) |
| 6 — DEF-24/25/26 | Bổ sung quy trình cảnh báo, xác nhận lỗi, escalation và đóng sự cố. So lock/image kiểm hash lock nhúng, marker nền tảng Python và toàn bộ package production Python/npm API/runner; không lệch. Pin PostgreSQL khớp Compose, manifest, image ID và linux/amd64. | [Runbook](../ops/runbook.md), [công cụ](../../../scripts/compare-lock-image.py), [lock-image.json](../../../outputs/followup-0a67461-20261017/lock-image.json), [identity.json](../../../outputs/followup-0a67461-20261017/identity.json) |
| 7 — DEF-17 | Release đã có commit `cf21031`. Bổ sung `.secrets/` và commit riêng `7d488b5` trên `fix/system`; `git check-ignore .secrets/probe` khớp. | [.gitignore](../../../.gitignore) |
| 8 — R8 cũ | Đánh dấu SUPERSEDED cho release F, dẫn sang báo cáo VAHAN thật. Giữ nguyên số liệu synthetic để tra cứu lịch sử. | [R8-eta.md](R8-eta.md), [D3 R8 mới](../../../outputs/D3-0a6746187e82-20261016T093436Z/R8-ETA.md) |

## Phát hiện CSP và bản sửa source

Image web gốc có CSS import Google Fonts từ `fonts.googleapis.com`, trong khi CSP chỉ cho style cùng origin.
Trình duyệt ghi nhận một `style-src-elem` violation cho URL này; ô mật khẩu vẫn hiển thị nhờ font fallback.
Không mở rộng CSP. Checkout `fix/system` bỏ import font từ xa; `npm.cmd run build` PASS.
Build mới được mount read-only qua đúng image nginx để kiểm độc lập: trang đăng nhập render và không còn CSP violation.
Đây là **bản sửa trong source/build hiện tại, chưa đóng gói hoặc triển khai**; artifact `0a67461` vẫn giữ phát hiện font cũ.
Không tuyên bố gói cũ đã được sửa hoặc mọi CSP violation của nó đã biến mất.

Bằng chứng source mới: [web-source-fix.json](../../../outputs/followup-0a67461-20261017/web-source-fix.json).
API fixture dùng role DB hạn chế và tài khoản thử, môi trường test; luồng đăng nhập trên production staging
vẫn tham chiếu [D3 gốc](../../../outputs/D3-0a6746187e82-20261016T093436Z/REPORT.md).

## Kiểm chứng và lưu evidence

- Self-test công cụ: **5 PASS**; đã đăng ký manifest/workflow. Tại thời điểm kiểm local chưa có kết quả CI cho thay đổi mới.
  Self-test hiện phủ parsing/diff; chưa phủ đầy đủ các nhánh lỗi của CLI.
- Test DEF-15 trên image API release và PostgreSQL tạm: **3 PASS**.
- UI TypeScript/Vite production build: **PASS**. Probe mới chỉ kiểm trang đăng nhập;
  chưa chạy lại toàn bộ login, export và Run History trên bản sửa.
- Checker đăng ký test: **96 file, 0 vấn đề**; kiểm liên kết và `git diff --check` PASS.
- Giữ các lần harness lỗi trong ledger: thiếu backend, một lần không ghi log unittest;
  lần kiểm zero-CSP trên gói gốc phát hiện font bị chặn. Không dùng các lần này làm PASS.
  Kiểm chức năng nginx sau đó chỉ cho phép đúng observation font đã nêu; source mới được kiểm riêng với zero-CSP.
- Môi trường tạm được dọn sau mỗi lượt: [cleanup.json](../../../outputs/followup-0a67461-20261017/cleanup.json).

[checklist.json](../../../outputs/followup-0a67461-20261017/checklist.json),
[source-validation.json](../../../outputs/followup-0a67461-20261017/source-validation.json).
Evidence thô, export, screenshot và harness của lượt mới được công bố theo yêu cầu người dùng;
các candidate cũ đã xóa, không đưa lên Git. Gói release và evidence niêm phong giữ nguyên checksum.
Không thay severity hoặc tự đóng các dòng triage lịch sử chỉ dựa vào sửa tài liệu.

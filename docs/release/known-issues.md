# Known issues — Release 1.0 (T01, bản đầu RG0)

Nguồn: `PLAN.md` r26 §3.5, §3.3 (hệ quả D-02/D-18), §3.4, §11, Phụ lục I. Ngày lập: 11/10/2026; cập nhật 12/10/2026 (r26, đối chiếu HEAD `b210529`; chưa chạy test/build). Owner mọi dòng: **Felix** (D-16).

**Quy tắc đọc.**
- *Severity (D-03)* = Felix đã chốt "theo đề xuất §3.5"; KI-02 = Major và KI-19 = Minor chốt 11/10. Dòng **KI-21…KI-24 là KI mới** sinh từ mục Deferred/Excluded: Felix chốt 12/10 theo đề xuất (KI-21 Major, KI-22 Major, KI-24 Minor; KI-23 là scope) và duyệt toàn bộ mức đề xuất cùng ngày. Chốt severity không phải accepted risk.
- **Chưa KI nào là accepted risk.** D-20 chốt quy trình: Felix duyệt từng KI Major/Minor tại RG5. "Không chặn theo §1.5" chỉ nghĩa là severity Major/Minor không tự chặn release, không phải đã chấp nhận rủi ro.
- Blocker/Critical bắt buộc sửa và chặn release. Không KI nào dưới đây đề xuất mức đó.
- **Hiện trạng vs dự kiến.** Biện pháp bù hoặc hành vi do task chưa Done (T16c, T17, T18, T19a…g, T21a…) được ghi là **dự kiến**; ở thời điểm lập (11/10) các task này **chưa triển khai**; ở HEAD `b210529` (12/10) một phần code đã có (S3, S5, S6, S7, phần O1) nhưng **chưa có test/kiểm chứng**, nên các KI giữ mô tả "dự kiến" cho tới khi task Done. KI chỉ có hiệu lực theo mô tả "sau task X" khi task đó Done và đã kiểm trên artifact; task không hoàn tất thì KI phải được viết lại ở lần cập nhật kế tiếp (RG1, RG5).
- Số ID: KI-20 đã bị rút ở r15 và không dùng lại; KI mới bắt đầu từ KI-21.
- Nhãn bằng chứng giữ nguyên của PLAN; dòng "đọc lại 11/10" là mình đọc source ở phiên T01. Không test/build sản phẩm nào được chạy.

## Tóm tắt

| Nhóm | KI |
| --- | --- |
| Đang áp dụng, severity đã chốt (D-03) | KI-01…KI-07, KI-11, KI-12, KI-14…KI-19 (15 dòng) |
| Có điều kiện, hiện **không áp dụng** | KI-08 (chỉ nếu mở lại D-05), KI-09 (không áp dụng: D-07 = A gỡ nốt, Felix chốt 12/10) |
| Không áp dụng | KI-10 (D-04 = A từ 12/10), KI-13 (D-01 = A) |
| **Mới, Felix đã triage 12/10** | KI-21 (Major), KI-22 (Major), KI-23 (scope), KI-24 (Minor) |
| Blocker / Critical | 0 |

## 1. Known issues đang áp dụng

| ID | Vấn đề | Impact | Severity | Workaround | Owner | Chặn release? |
| --- | --- | --- | --- | --- | --- | --- |
| KI-01 | Maker Update không có trong 1.0 (R13 Excluded). **Hiện trạng:** router `/api/maker-updates*` còn mount (`api/__init__.py:13,30`). **Dự kiến sau T17:** gỡ router + schema từ chối `update*` (D-06 = A) | Không cập nhật gia tăng; phát hiện Maker/RTO mới phải chạy lại đầy đủ | — (scope) | Chạy lại theo lịch / thủ công | Felix | Không |
| KI-02 | CAPTCHA auto-solve, không có đường nhập tay (R14) | Security/Legal có thể phản đối; VAHAN đổi kiểu chữ có thể làm mọi job lỗi tới khi cập nhật OCR. **Hiện trạng:** chưa có giới hạn, OCR sai độ dài có thể refresh liên tục. **Dự kiến sau T19f (D-18):** hết hạn mức 20 lần/10 phút thì job `FAILED` và web hiện chi tiết lỗi. Hạn mức tính chung mọi runner dùng cùng DB nên một job có thể thất bại vì lượt của job khác | **Major** (Felix chốt 11/10) | Báo lỗi cho người dùng; sửa OCR rồi retry theo queue | Felix | Không theo §1.5; accepted risk chờ D-20 |
| KI-03 | Token UI lưu `localStorage` | XSS lấy được token trong TTL 12 giờ | Major (D-03) | TTL ngắn hiện có; HEAD có `docker/security-headers.conf:1-4` nhưng CSP chỉ gồm `frame-ancestors`/`object-src`/`base-uri` (không `script-src`) nên chưa giảm rủi ro XSS lấy token; T19c chưa kiểm chứng | Felix | Không nếu Felix chấp nhận (D-20) |
| KI-04 | Chỉ kiểm chứng runtime trên Docker Desktop/Windows (WSL 10 GB, engine 9,7 GiB); Ubuntu chỉ có build image trong CI | Hành vi seccomp/cgroup và hiệu năng nhiều runner trên production chưa biết | Major (D-03) | Vận hành chạy lại smoke trên host đích | Felix | Không |
| KI-05 | Stack không tự cấp TLS | Cần reverse proxy HTTPS | Major (D-03) | `WEB_BIND_ADDRESS=127.0.0.1` + proxy (`docs/deployment.md` đã xóa ở `95aa029`; cần ghi lại ở INSTALL, T52a) | Felix | Không |
| KI-06 | Chưa có monitoring/alerting đầy đủ (phần còn lại của O1). **Hiện trạng (HEAD 12/10):** `/api/ready` kiểm revision migration (`health.py:23-33`); chưa có probe ngoài stack và runbook. **Dự kiến sau T19g:** probe `/api/ready` + runbook tối thiểu | Sự cố phát hiện muộn | Major (D-03) | Dự kiến: probe + runbook (T19g); hiện chưa có | Felix | Không theo §1.5; cần D-20 nếu để lại |
| KI-07 | Một API process, không HA. H2: restart API giữ case `PROCESSING`; runner mất heartbeat quá hạn thì case được retry từ filter đã lưu (ở B: job bị `FAILED` ngay) — **hành vi mới, chưa có test** (xem DEF-06) | Gián đoạn khi API restart; chưa có bằng chứng 0 mất/0 trùng | Minor (D-03) | Retry tự động theo lease | Felix | Không |
| KI-11 | `/api/ready` không có timeout DB (HEAD `health.py:23-33`: lỗi DB trả 503 nhưng không có timeout riêng) | Healthcheck treo khi DB treo | Minor (D-03) | Healthcheck timeout 5 s của Compose | Felix | Không |
| KI-12 | `tools/ui-drift-guard` không chạy trong CI; 3 file test migration-snapshot không áp dụng | CI không phát hiện drift DOM | Minor (D-03) | UI Health preflight | Felix | Không |
| KI-14 | Runner dùng **một token chung** và **tự khai ID** (`X-VAHAN-RUNNER-ID`, socket auth `runnerId`); API không gắn yêu cầu HTTP với runner cụ thể (Verified: `main.py:_runner_auth_is_allowed`, `security.py:runner_token_matches`, `realtime/runner_events.py:_registration`, `api/batch_queue.py:134`). **Cập nhật theo D-02: S8 Deferred** — không có S8-1 (kiểm nhất quán runner–job–kết nối) và không có S8-2 (credential riêng từng runner); `authz-matrix.md` chỉ ghi hiện trạng. Route runner-auth mới của D-18 (cấp lượt OCR, **dự kiến** ở T19f, chưa có) sẽ dùng chung token này | Người giữ token đặt được header bất kỳ → mạo danh runner khác: claim case, nộp kết quả cho job của runner khác. **Không còn** kiểm lệch ID–job không chủ đích | Major (D-03) | Bảo vệ token: mạng Docker nội bộ, `API_BIND_ADDRESS=127.0.0.1` | Felix | Không chặn theo §1.5; accepted risk: D-20 (chưa) |
| KI-15 | Image không tin CA nội bộ của nơi nhận; CA chỉ thêm được lúc build (`docker/certs/`) | Mạng nơi nhận thay chứng chỉ TLS → runner/API không gọi được VAHAN | Major (D-03) | **D-24 = A:** prerequisite — chỉ hỗ trợ mạng không thay chứng chỉ TLS tới `analytics.parivahan.gov.in`; ghi ở INSTALL/release notes; nơi nhận cần CA nằm ngoài 1.0 | Felix | Không theo §1.5; cần D-20 nếu để lại |
| KI-16 | "Last data saved" trong Coverage cố định GMT+7 (`ReportCoverage.tsx` `formatSavedAt`) dù lịch có thể dùng giờ Ấn Độ (R7b) | Hiển thị lệch múi giờ | Minor (D-03) | Đọc nhãn "GMT+7" | Felix | Không |
| KI-17 | Diagnostics không còn gọi `/health` của runner; `browserReady` chỉ phản ánh socket đang kết nối; `VAHAN_API_RUNNER_HEALTH_CHECKS` còn trong compose nhưng không còn tác dụng (Likely) | Chẩn đoán worker kém chi tiết hơn B | Minor (D-03) | Log runner + healthcheck Compose | Felix | Không |
| KI-18 | Số runner chỉ chọn lúc khởi động (launcher); không tự tăng/giảm khi đang chạy (autoscale ngoài 1.0) | Không tận dụng tài nguyên dư, không tự giảm khi thiếu RAM | Minor (D-03) | `run-vahan-rpa --workers N` rồi khởi động lại khi rảnh | Felix | Không |
| KI-19 | Không có trần cứng cho giới hạn song song/số runner (D-27 = d). Launcher `auto` tính theo CPU/RAM nhưng `--workers N` nhận mọi số nguyên dương; API điều khiển pool thủ công vẫn tồn tại. HEAD: ô khi tạo lịch đã bỏ, còn ô theo từng lịch (`AutomaticRunSettings.tsx:198-201`) — bỏ nốt theo T16c (§5.8); **mặc định giới hạn song song đổi thành 20** (`worker_pool.py:11`) — Felix chốt giữ 12/10 (D-34); launcher `auto` chọn số runner theo CPU/RAM (tối đa 20); lịch dùng runner thực tế và không áp số lớn đã lưu (T16c); giá trị lớn đã lưu cần tính lại khi chạy | Operator override quá cao có thể khiến VAHAN chặn IP / CAPTCHA lỗi nhiều hơn / cạn RAM; giá trị ≥ 2³¹ có thể gây 500 ở DB thay vì 422 (Likely, T16b ghi kết quả thực tế) | **Minor** (Felix chốt 11/10) | Dùng launcher `auto`; theo dõi `docker stats`, case/phút và tỷ lệ lỗi theo N (R9b) | Felix | Không theo §1.5; accepted risk chờ D-20 |

## 2. Có điều kiện / không áp dụng

| ID | Trạng thái | Điều kiện để áp dụng |
| --- | --- | --- |
| KI-08 | Không áp dụng — D-05 = A (ETA nằm trong 1.0, không có quy tắc tự hoãn) | Chỉ khi Felix mở lại D-05 sau khi T15 không đạt: "ETA chưa hiển thị", Minor (D-03) |
| KI-09 | Không áp dụng — D-07 = A (gỡ hết API legacy; Felix chốt 12/10) | Chỉ nếu Felix mở lại D-07 sang B: "API legacy còn tồn tại", Minor, workaround "route yêu cầu token" |
| KI-10 | Không áp dụng từ 12/10 — D-04 = A: UI và API có export đủ mọi bản ghi khớp bộ lọc State/RTO (ID không dùng lại) | Chỉ nếu Felix đổi D-04 về B: "Không export theo tìm kiếm", Minor (D-03) |
| KI-13 | Không áp dụng — D-01 = A (lock có hash, scan, SBOM bắt buộc) | — |

## 3. KI mới — Felix đã triage 12/10 (theo đề xuất)

Các dòng này sinh từ mục Deferred/Excluded theo PLAN §3.3 "Hệ quả theo nhánh D-02": Deferred **không** tự là accepted risk, phải có KI đã triage ở T01 trước RG0/RG1.

| ID | Vấn đề | Impact | Severity (Felix chốt 12/10) | Workaround | Owner | Chặn release? | Nguồn |
| --- | --- | --- | --- | --- | --- | --- | --- |
| KI-21 | **Container chưa hardening** (S10 Deferred). **Hiện trạng (đọc lại `compose.yaml` 11/10):** service `runner` chỉ có `security_opt: seccomp=./docker/seccomp_profile.json` (`compose.yaml:71` ở HEAD `b210529`; thêm log giới hạn 10 MB × 5); không có `cap_drop`, `no-new-privileges`, giới hạn RAM/CPU/pids. Chờ công ty cấp tài nguyên | Một runner bị khai thác hoặc lỗi nặng có thể chiếm tài nguyên host; bề mặt container rộng hơn mức tối thiểu | **Major** (Felix chốt 12/10) — khớp định nghĩa §1.5 "thiếu hardening có biện pháp bù" | Đang có: seccomp profile của runner, `USER node` (`apps/browser-runner/Dockerfile:26`); bind `127.0.0.1` (mô tả ở `docs/deployment.md`, đã xóa ở `95aa029`; ghi lại ở INSTALL, T52a); theo dõi `docker stats` | Felix | Không theo §1.5; cần D-20 nếu để lại | D-02 (S10), PLAN §3.3 |
| KI-22 | **Chống brute-force login chỉ ở tầng nginx; bộ đếm DB theo tài khoản/IP Deferred.** **Hiện trạng (HEAD `b210529`, 12/10):** `docker/nginx.conf:1,10-13` có `limit_req` cho `/api/auth/login` (10 req/phút/IP, burst 10, 429) — chưa có test hay kiểm chứng (DEF-20); T19a chưa Done. Không khóa theo tài khoản, không phát hiện tấn công phân tán nhiều IP | Sau khi kiểm chứng: chỉ còn rủi ro brute-force chậm/phân tán. Trước đó: chưa biết `limit_req` hoạt động đúng sau proxy | **Major** (Felix chốt 12/10) — thiếu hardening có biện pháp bù | Mật khẩu ≥ 12 ký tự, bind nội bộ/proxy; rate limit nginx | Felix | Không theo §1.5; cần D-20 nếu để lại | D-02 (S3), PLAN §3.3, Phụ lục C (S3-ii) |
| KI-23 | **Import dữ liệu cũ không thuộc 1.0** (D-25 = B): `app/import_legacy.py`, `scripts/export-legacy-history.py` còn trong source nhưng không có quy trình, không có test, README/docs hiện không còn hướng dẫn import (đọc lại 11/10); không file test/script nào tham chiếu hai file này | Không có đường chính thức đưa dữ liệu cũ vào bản mới | — (scope, như KI-01; Felix xác nhận 12/10) | Chạy lại thu thập; hoặc dùng script nội bộ ngoài hỗ trợ | Felix | Không | D-25 |
| KI-24 | **API legacy bị gỡ (D-07 = A, R15).** **Hiện trạng (HEAD `b210529`, 12/10): gỡ một phần** — `upload-excel` và `PUT /api/ui-health/schedule` đã gỡ; `GET /api/ui-health/schedule` (`ui_health.py:43-49`) và `POST /api/ui-health/run-now` (`ui_health.py:66-100`) **còn** và có test giữ lại (`tests/test_api.py:51,54`) — D-07 = A (Felix chốt 12/10) yêu cầu gỡ nốt ở T18. Caller trong repo: không có (PLAN §11.1). Client ngoài repo, nếu có, không kiểm được bằng code | Với route đã gỡ: client ngoài repo (nếu có) lỗi 404 sau nâng cấp. Với route còn: không ảnh hưởng | **Minor** (Felix chốt 12/10) | Dùng luồng hiện hành (queue/lịch qua UI, `/main-report`); Felix đã xác nhận không còn dùng | Felix | Không | D-07, T02 |

## 4. Việc còn mở (dev / Felix)

| # | Cần | Ai |
| --- | --- | --- |
| 1 | ~~Quyết severity KI-21, KI-22, KI-24 và xác nhận KI-23 là "scope"~~ — **xong 12/10** (Felix: Major, Major, Minor; KI-23 = scope) | Felix |
| 2 | T02: ghi câu trả lời kèm ngày — caller nội bộ của `upload-excel`, `ui-health/schedule`, `ui-health/run-now` (quyết định KI-09/KI-24). Bằng chứng caller nội bộ đã có (PLAN §11.1, 12/10) — đủ cho RG0; trả lời bằng lời của dev để T02 Done. Câu export có `state`/`rto` đã đọc ở source 12/10 (D-04 = A), chỉ cần dev xác nhận ý đồ, không chặn RG0. Bằng chứng caller trong repo: PLAN §11.1 (12/10); phần ngoài repo không xác minh được bằng code | dev |
| 3 | ~~Xác nhận đã đọc lại cột "Severity" KI-01…KI-19~~ — **xong 12/10:** Felix duyệt toàn bộ mức đề xuất | Felix |
| 4 | Accepted risk từng KI Major/Minor: **chưa quyết**, làm ở RG5 (D-20) | Felix |
| 5 | Cập nhật KI cuối tại RG5 (C6.3): thêm/bỏ KI theo kết quả T16b, T19f, T30, T33 (vd. KI-19 ghi kết quả ≥ 2³¹; KI-07 sau test restart) | Felix |
| 6 | ~~Quyết định cho hai route legacy còn lại~~ — **xong 12/10:** D-07 = A gỡ nốt; code ở T18 | dev |
| 7 | ~~Xác nhận lần cuối các mức KI-21/22/24~~ — **xong 12/10** | Felix |
| 8 | Thực hiện D-31…D-34 (R17 Run History, S12 tách quyền DB, image PostgreSQL chính thức pin digest, mặc định 20 + runner thực tế) và cập nhật KI-19 sau T16c | dev |

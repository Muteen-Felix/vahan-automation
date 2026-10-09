# Bộ test case toàn hệ thống VAHAN — nghiệm thu doanh nghiệp

## 1. Hồ sơ và phạm vi đánh giá

| Thuộc tính | Giá trị |
| --- | --- |
| Mã tài liệu / phiên bản | VAHAN-QA-SYSTEM-001 / 1.1 |
| Ngày lập | 08/10/2026, giờ Việt Nam UTC+07:00 |
| Đối tượng | Checkout `/Users/mac/Desktop/vahan-automation`; FastAPI/Socket.IO, React, Playwright/Chromium, PostgreSQL, Nginx, document processor và công cụ vận hành |
| Snapshot source | HEAD `2bc878e` và working tree tại lúc lập tài liệu; SHA-256 tổng hợp `32a774db44990b793b06dc99c38411267cab561f5aa054692d2c68811b350210` trên 167 file source/config công khai; có thay đổi chưa commit |
| Số lượng | **340 test case gốc**, 28 nhóm; **84 thao tác HTTP `/api`**, **17 sự kiện Socket.IO đầu vào**; có thêm biến thể bắt buộc theo ma trận |
| Trạng thái thực thi | **Toàn bộ test case trong tài liệu: NOT RUN.** Công việc này đọc source/tài liệu/harness và kiểm tra tính nhất quán tài liệu; không chạy batch, pentest, load, migration, restore hoặc fault injection trên hệ thống thật |
| Ý nghĩa “bao phủ toàn hệ thống” | Bao phủ thành phần, giao diện, ranh giới tin cậy và rủi ro được phát hiện trong snapshot; API/parameter/state matrix mở rộng thành run instances. Không suy ra mọi tổ hợp vô hạn hoặc mọi lỗi ngoài thực tế đã được kiểm tra |
| Đầu ra khi nghiệm thu | Run report theo release, test-instance results, dữ liệu đối soát, log/trace đã che secret, defects, số đo SLO/RPO/RTO và biên bản ký duyệt |

### Chuẩn tham chiếu và phương pháp

| Cơ sở | Cách áp dụng trong bộ test |
| --- | --- |
| [ISTQB CTFL v4.0.1](https://istqb.org/wp-content/uploads/2024/11/ISTQB_CTFL_Syllabus_v4.0.1.pdf) | Phân vùng tương đương, giá trị biên, bảng quyết định và chuyển trạng thái; ưu tiên theo tác động/rủi ro |
| [OWASP ASVS 5.0.0](https://owasp.org/www-project-application-security-verification-standard/) | Tham chiếu các nhóm kiểm soát xác thực, session, quyền, xử lý input/file, dữ liệu, cấu hình và logging |
| [OWASP WSTG v4.2](https://wstg.owasp.org/v4.2/) | Tham chiếu kiểm thử web/security theo phiên bản; kiểm tra quyền bằng request thực tế, không chỉ dựa vào UI |
| Quy tắc nghiệp vụ VAHAN | Độ đúng từng case/filter/cell, dữ liệu bền vững, lineage retry, gate trước Apply, no-data có xác nhận và khả năng đối soát toàn State/RTO |

Đây là thiết kế kiểm thử có truy vết theo source, không phải chứng nhận tuân thủ toàn bộ ASVS/ISO hoặc báo cáo PASS. Nếu doanh nghiệp cần một mức ASVS cụ thể, AppSec phải lập mapping từng yêu cầu áp dụng và ký bằng chứng riêng.

### Căn cứ và các quyết định cần chốt

| Mã | Snapshot/khác biệt phát hiện | Cách đưa vào test |
| --- | --- | --- |
| BL-01 | Source có cookie/CSRF, MFA, tenant deployment guard, rate limit và document service mới; không xác minh chúng đã deploy live | Test cả happy/negative/recovery; cần kiểm tra trên release hiện tại |
| BL-02 | Cùng deployment có kho báo cáo dùng chung và hai role admin/user; chưa phải shared SaaS có tenant membership/RLS đầy đủ | `P-TENANT`: một DB/deployment mỗi tenant là baseline; thử A/B hai deployment. Chọn shared DB thì TC-ACL-011 là gate bổ sung bắt buộc |
| BL-03 | `AnnualReports.tsx` còn mở UpdateHistory; README có câu nói đã bỏ | Kiểm thử UI đang có và API cũ; Product quyết định giữ/gỡ rồi cập nhật baseline, không tự bỏ khỏi coverage |
| BL-04 | UI hiện chỉ Export all khi search rỗng; API export vẫn hỗ trợ State/RTO | TC-REP-004 và TC-REP-005 kiểm tra riêng hai contract; không giả định UI có nút export filtered |
| BL-05 | Normal import cập nhật newer `observed_at` và giữ provenance; một số README còn mô tả giữ nguyên giá trị cũ | TC-DATA-006, TC-DATA-007, TC-DATA-008 theo source hiện tại; Product/DBA xác nhận chính sách stale/equal-time và replacement |
| BL-06 | ETA helper đã tính nhưng thẻ lịch chưa render ETA; Maker Update có primitives nhưng chưa thấy orchestrator hoàn chỉnh | TC-SCH-018 và TC-MKR-012/TC-E2E-007 ghi `GAP`; không đánh dấu hoàn thành vì chỉ có hàm backend |
| BL-07 | CAPTCHA/validation có event tương thích; dashboard không có panel ảnh/entry hoàn chỉnh. Tài liệu mô tả các flow chưa thống nhất | CAP kiểm thử trạng thái/privacy và quy trình validation hợp lệ đã duyệt; không dùng bypass để đạt test |
| BL-08 | README nhắc result timeout 5s; `runner.mjs` có default 90s và driver có deadline riêng | Trước RUN/NET, chốt deadline thực tế từ env/driver vào manifest; kiểm tra biên theo giá trị đó; khác biệt là defect/spec issue |
| BL-09 | Production HTTPS, offsite/encrypted backup, SIEM/ticket, trực xử lý và SLO phụ thuộc cấu hình hạ tầng ngoài repo | `CFG/GAP` không có nghĩa PASS; cần bằng chứng staging/production rehearsal trước sign-off |

## 2. Quy ước, trách nhiệm và trạng thái

| Ký hiệu | Ý nghĩa |
| --- | --- |
| P0 | Chặn release nếu chưa đạt: sai/mất dữ liệu, vượt quyền/tenant/worker, mất session control, Apply lặp không kiểm soát, restore không bảo đảm |
| P1 | Nghiệp vụ chính, recovery, validation, vận hành và khả năng đáp ứng; ngoại lệ chỉ được chủ rủi ro ký có hạn |
| P2 | Usability/utility ít tác động hơn; vẫn phải ghi kết quả và lỗi |
| F / N / B / C | Functional / Negative / Boundary / Concurrency |
| R / S / U / P / O | Recovery / Security / UI-accessibility / Performance / Operations |
| SRC | Có module/đường xử lý liên quan trong source; **không khẳng định module đã đạt kết quả mong đợi** |
| CFG | Cần cấu hình, công cụ, hạ tầng hoặc quy trình được doanh nghiệp cấp trước khi chạy |
| GAP | Yêu cầu nghiệm thu chưa có phần triển khai hoàn chỉnh hoặc chưa có cơ chế chứng minh trong snapshot; vẫn giữ trong kế hoạch |
| NOT RUN / PASS / FAIL | Chưa chạy / chạy đủ bước và đủ bằng chứng đạt / có kết quả trái mong đợi |
| BLOCKED / N/A | Không thể chạy do dependency hoặc GAP có lý do; N/A chỉ dùng khi ngoài scope được Product/QA ký duyệt. Không đổi BLOCKED thành PASS |

Ưu tiên test không đồng nghĩa severity lỗi. Defect cần đánh giá riêng: Critical (rò quyền/tenant, mất dữ liệu, không thể vận hành an toàn), High (chức năng chính/recovery hỏng), Medium và Low. QA lead quản lý coverage; Backend/RPA/Frontend sửa chức năng; DBA/DevOps chịu bằng chứng vận hành; Product chốt policy và scope.

## 3. Ma trận tác động nội vi và ngoại vi

| Tác động / ranh giới | Kịch bản phải kiểm tra | Nhóm test |
| --- | --- | --- |
| Browser/người dùng → Nginx/API | Input sai, double-click, tab cũ, cross-site, logout/role change, keyboard/zoom/Safari | AUTH, ACL, ACCT, UI, API, SEC |
| Các module nội bộ → SQL | Transaction fail, lock, deadlock, pool đầy, stale writes, permissions, codec corrupt | DATA, QUEUE, DB |
| API → worker | Assignment persist/emit lệch, ACK thiếu, sai identity, socket stale, capacity/lease | JOB, QUEUE, RUN, SOCK |
| Scheduler → queue/worker | Due slots, clock/epoch, pause/resume/stop/delete races, leader failover | SCH, QUEUE, RETRY, OPS |
| Worker → VAHAN | DOM/options đổi, network/HTTP lỗi, rate limit, stale results, validation, download sai | PROF, UH, RUN, CAP, NET |
| API → document service | Malformed file, ZIP/XML abuse, CPU/RAM/time limit, process crash, network timeout | FILE, SEC, PERF |
| VAHAN/data source thay đổi | Hãng/RTO mới/mất, tổng không đổi nhưng tháng đổi, file thiếu, snapshot khác thời điểm | DATA, HIST, MKR, E2E |
| Tác động tài khoản nội bộ | Insider admin, demote admin cuối, offboarding, đổi password/khóa user đang chạy | AUTH, ACL, ACCT, SCH, SEC |
| Tác động khách hàng/tác nhân ngoài | Token giả/replay, Origin sai, upload độc hại, request burst, file/ID đã biết | API, ACL, SEC, SOCK |
| Hạ tầng/host | Power loss, OS/Docker restart, OOM, disk/WAL/tmp đầy, read-only volume | DB, OPS, PERF, ENV |
| Mạng ngoài | DNS/TCP/TLS/proxy/firewall lỗi, jitter/loss, maintenance200, redirect | NET, RUN, SEC |
| Đồng hồ | UTC+7/UTC, tháng ngắn/năm nhuận, NTP skew, deadline expiry | AUTH, MFA, SCH, DB, OPS |
| Backup/keys | Dump hỏng/cũ, sai tenant/key, offsite lỗi, rotate key, restore host mới | OPS, SEC, E2E |
| Supply chain/deployment | Browser/lib/schema upgrade, image digest/SBOM mismatch, config/port sai | PLAT, ENV, SEC, OPS |
| Tải/khách hàng đồng thời | Users/workers/export/import/queries/events tranh tài nguyên; soak và recovery sau spike | PERF, DB, QUEUE, SOCK |

## 4. Môi trường, dữ liệu và oracle độc lập

### Môi trường thực thi

| Môi trường | Dùng cho | Ràng buộc |
| --- | --- | --- |
| E-UNIT | Parser/policies/codec/timing/state machine với fixtures | Không kết nối portal thật hoặc DB production; fake clock có thể kiểm soát |
| E-INT | API/SQL/socket/scheduler giữa các service | DB disposable có tên riêng; secrets test; fixture VAHAN và document servers; ports/volumes tách |
| E-STAGE-A/B | Deployment tenant A/B, integration/fault/load/security | Hai DB/key/network/runtime độc lập; dữ liệu tổng hợp; không dùng dữ liệu/credential doanh nghiệp thật |
| E-BROWSER | Chromium/Chrome/Edge/Firefox/Safari theo support matrix | Browser profile test; viewport/zoom/privacy modes được ghi trong run manifest |
| E-UAT | Kiểm thử portal live được phép và đối soát nghiệp vụ | Mẫu nhỏ đã duyệt, throttle hợp lệ, quy trình validation hợp lệ; không load/fault/pentest lên VAHAN thật |
| E-DR | Restore/release rehearsal | Host/volume khác; kiểm tra checksum và tenant trước cutover; không đè DB đang chạy |

Trong công việc lập tài liệu này không thực thi bất kỳ tác động phá hủy nào. Khi chạy suite, chỉ fault/load/abuse trên E-INT/E-STAGE/E-DR có snapshot và quyền đã cấp. Không dùng `.docker.env` thật trong fixtures, log hoặc artifacts; không tự `down -v`, clear DB thật hay gửi thông báo bên ngoài nếu chưa được cấp phạm vi.

### Bộ dữ liệu chuẩn bị

| Mã dữ liệu | Nội dung và cách xây oracle |
| --- | --- |
| D-ENV | Cấu hình production/development hợp lệ và các bản thiếu/sai; chỉ dummy secrets; manifest ghi flags/versions không ghi secret |
| D-AUTH | Admin A1/A2, member A, disabled A; MFA enabled/not-enabled; expired/idle/revoked sessions; deployment B độc lập; worker tokens riêng |
| D-PROFILE / D-OPTIONS | 15 fields; fixed/iterate/include/exclude/rules; parent-child options theo fixture; Maker có Unicode, comma và tên gần giống |
| D-PLAN12 | 2 State × 3 RTO hợp lệ × 2 lựa chọn fuel trong fixture; 12 caseKey độc lập, order/filters khóa trong golden JSON |
| D-PLAN-BOUNDARY | 0/1/9/10/11/20/21/1.676/3.000/3.001 case; nhiều scope và case lỗi có vị trí xác định; 1.676 chỉ là fixture, không chứng minh full VAHAN |
| D-XLS | Workbook nhiều sheet; header/month/year chuẩn; giá trị dễ đối soát; OTHERS, Unicode, null và zero riêng; expected cells nhập tay/được QA review, không dùng chính parser under test tạo oracle |
| D-XLS-DELTA | Snapshot t0/t1/equal-time; Maker/RTO mới/mất; tổng bằng nhau nhưng vector tháng khác; partial file và duplicate conflicts |
| D-BADFILE | Empty/truncated/ZIP hỏng/giả extension/XML entity/formula CSV; sizes/row count từng biên; chỉ fixture an toàn, không thực thi mã độc thật |
| D-STATE | Users/sessions/jobs/queue/retry phases/profile revisions/main rows/provenance/audit/browser state encrypted trước restart/backup |
| D-FAULT | Fault proxy cho DNS/TCP/TLS/HTTP/latency; process/SQL barriers theo F-FAULT; clock được mock/điều khiển trong test, không đổi giờ host thật |
| D-LOAD | Synthetic reports/history: 205/100k main rows, ≥1m historical jobs khi cần; 1/5/10 workers và 1/10/50 users; không PII thật |

**Cleanup chung:** mỗi run có `runId`, tenant/project/DB/volume riêng; hoàn tất thì hủy fixture jobs, giải phóng lease/connection/process, dọn temp và restore baseline trong môi trường test. Giữ artifacts đã che secret theo retention. Không xóa toàn DB hoặc tenant khác; cleanup lỗi được ghi riêng.

### Ràng buộc dữ liệu bắt buộc I-DATA

| Mã | Invariant / bằng chứng |
| --- | --- |
| I-01 | Logical case duy nhất theo case/session lineage; nhiều attempts không tăng total case; source filters/retry metadata giữ nguyên |
| I-02 | Mọi planned case có outcome xác định: committed data, confirmed no-data, failed, cancelled hoặc pending/active; không case mất/skip không lý do |
| I-03 | COMPLETED chỉ sau transaction dữ liệu/history/job/release commit; NO_DATA cần outcome xác nhận, không từ timeout/loading/error |
| I-04 | Toàn bộ cell State/RTO/Maker/year/month khớp golden; null khác0; source newer không bị stale response ghi đè |
| I-05 | Replay same job/checksum chỉ một commit; differing checksum/late terminal update conflict, không overwrite mù |
| I-06 | Excel xuất đủ phạm vi/snapshot, rowCount/hash và nội dung reopen khớp; không HTML/JSON lỗi đổi tên thành XLSX |
| I-07 | ACL/session/tenant/worker checks trên mọi đường HTTP/socket/legacy; deny không side effect; secrets không lọt vào evidence |
| I-08 | Queue limit/lease/state/epoch có hiệu lực; một worker một job; không tự click Apply lại chỉ vì mất ACK |
| I-09 | `done` có thể giữ monotonic khi FINAL mở lại case lỗi; **100% Progress không đồng nghĩa batch đã hoàn tất recovery**. Status phải xét retry phase và failed remaining |
| I-10 | Pause/stop/delete/restart giữ dữ liệu đã commit; backup/restore và audit có reconcile được theo release/runId |

## 5. Giới hạn và tiêu chí đo

### L-LIMIT — đọc từ source/config snapshot, phải khóa vào run manifest

| Khu vực | Baseline source / biến thể bắt buộc |
| --- | --- |
| Auth/session | Absolute12h; idle60min; activity có chủ ý. Username1–128; login password1–1024; new password12–1024 |
| Login quota | Backend: account5/600s, IP20/60s, global120/60s. Nginx10 request/min + burst5; test tách ingress/backend và test kết hợp |
| MFA | Challenge/pending5min; TOTP6 digits với window ±1slot, replay counter; 10 recovery codes one-use; enroll3/300s, confirm5/300s |
| Profile | 15 fields; maxCases1–3000; values/include≤100, exclude≤500, rules≤30, value length1–500, name1–120; scalar fixed chỉ1 |
| Worker/queue | Worker1–10 integer; queue1–3000 tasks; checkpoint10; initial + checkpoint retry + final retry; không retry NO_DATA |
| Preflight | 1–10 unique workers; freshness5min; tối đa2 workers kiểm tra song song, tối đa2 attempts/worker, ACK55s/attempt theo source |
| Upload/parser | Upload50MiB; Nginx body52MiB; expanded250MiB; archive≤10.000entries; extracted≤500.000 rows trên mọi sheet |
| Document service | Internal request≤128MiB; response client≤256MiB; parser timeout default120s; subprocess resource limits và1slot |
| Export | max_export_rows default100.000 có thể cấu hình; Excel ceiling chặn tại1.048.573 rows; user2/60s, global4/60s |
| DB pressure | pool 10 + overflow 5; acquire5s; statement60s; lock 5s; idle transaction 30s; bulk concurrency 2, acquire2s; HTTP503/Retry-After3s cho pressure được phân loại |
| Network/socket | Monitor5s; recovery2 success; disconnect grace default30s; Socket.IO max buffer2MiB; endpoint-specific ACK deadlines khóa theo config |
| Pagination | Annual1–500; history1–100; jobs/audit/file rows1–1000; files1–500; sessions1–200; detail1–500; offset≥0 |
| Result wait | BL-08 chưa thống nhất tài liệu/driver; ghi giá trị thực tế trong manifest rồi thử ngay trước/đúng/sau deadline |

Tại mỗi biên số/length/time, tạo ít nhất `min−1, min, min+1, max−1, max, max+1`, missing, null, sai kiểu và boolean (khi integer nghiêm ngặt). File limits tính bytes/MiB, không dùng nhầm MB decimal; tập nhiều sheet tính tổng, không riêng từng sheet.

### SLO đề xuất để doanh nghiệp chốt trước PERF/OPS

| Mã | Mốc khởi điểm đề xuất — chưa là SLA đã nghiệm thu |
| --- | --- |
| SLA-API | Staging50 users đồng thời: list/search p95≤2s, p99≤5s; successful request errors không do inject<0,1%; login/MFA p95≤3s ngoài thời gian người dùng nhập mã |
| SLA-UI | Bảng phản ánh commit≤5s admin/socket, ≤15s member/polling; main thread không treo quá1s ở workload chuẩn; đánh giá theo support browser |
| SLA-LOAD | Warm-up5min + steady30min; soak8h, release-critical24h; memory/connection/temp/PID không tăng vô hạn; tài nguyên có headroom được DevOps ký |
| SLA-RPA | Không ấn định cases/min portal thật từ fixture. Measure p50/p95 từng phase/worker; queue chậm vượt deadline phải có stage/lý do, không “Preparing” im lặng |
| SLA-DR | RPO≤15min, RTO≤60min là đề xuất; phải điều chỉnh và có restore drill bằng chứng trước cam kết |

## 6. Quy tắc mở rộng coverage

| Ma trận | Quy tắc bắt buộc và truy vết |
| --- | --- |
| M-API-ROLE | Với **mỗi operation A-API**, instantiate TC-API-001/002/008 và test nhóm nghiệp vụ: anonymous, admin hợp lệ, admin khác cùng deployment, member, disabled/revoked/expired, worker đúng, worker sai ID, credential tenant B. Public endpoints có allowlist riêng; không áp blanket deny cho health/login |
| M-PARAM | Với mỗi field trong model/query/path/header: equivalence/boundary, missing/null/wrong type, Unicode/length; expected dựa contract được duyệt. StrictModel reject extras; VahanFilters extras không được tự chuyển thành control chưa mapping |
| M-JOB | TC-JOB-001 chạy **mọi 144cặp của12 trạng thái**, gồm self-transition, mọi cạnh hợp lệ và mọi cạnh sai; xác minh side effects thay vì chỉ bool transition |
| M-SCH | TC-SCH và API matrix chạy mọi action create/start, toggle, pause, resume, stop, delete trên WAITING/PREPARING/RUNNING/PAUSING/PAUSED/RESUMING/COMPLETED/COMPLETED_WITH_ERRORS/ERROR/STOPPED; thêm owner, eligible queue, count và network intent guards |
| M-CONCURRENCY | Mỗi mutation critical thử duplicate request, two actors, old callback, cancellation và mất ACK trước/sau commit; chạy ít nhất30 iterations race có barriers, không dựa timing ngẫu nhiên |
| M-BROWSER | Critical flows trên browser support; viewport320/390/768/1024/1440/1920, zoom100/200/400%; pairwise cho tổ hợp ít rủi ro, exhaustive cho quyền/data invariants |
| M-NET | Allowed links: browser→web; web→api; api→DB/runner/documents; runner→API/VAHAN/DNS cần thiết. Deny links: web/runner→DB, application→Docker socket, public→documents, tenantA→private services tenantB |
| Run instance | ID dạng `TC-<group>-nnn.HTTP-xxx.principal.variant.environment.iteration`; một case parameterized có nhiều kết quả. Count case gốc không bằng count run instances hoặc coverage đã đạt |

## 7. Test case chi tiết

Tiền điều kiện chung: môi trường/dữ liệu ở mục4 sẵn sàng, policy BL/P-TENANT và thresholds được khóa vào manifest; mỗi group dùng nguồn được liệt kê để trace. Mọi expected cần bằng chứng UI/API **và trạng thái bền vững/side effects** khi áp dụng. `SRC/CFG/GAP` là căn cứ chuẩn bị, tất cả kết quả thực thi ban đầu đều **NOT RUN**.

### 7.1. Khởi động, cấu hình và trust boundary (ENV)

**Phụ trách:** DevOps + Backend. **Tác động:** Nội vi và ngoại vi. **Nguồn:** `compose.yaml; app/main.py; app/deployment_security.py; app/initialize_database.py`.

| ID | Ưu tiên / loại / căn cứ | Tình huống và tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
| --- | --- | --- | --- | --- |
| TC-ENV-001 | P0 · O · SRC | Khởi động mới; DB sạch, cấu hình hợp lệ D-ENV. | 1) Chạy migration; 2) khởi động stack; 3) đọc health/ready. | Schema đúng head; bootstrap một admin; ready chỉ đạt sau DB và guard; không lộ secret. |
| TC-ENV-002 | P0 · N · SRC | Thiếu signing key, MFA key hoặc worker token trong production. | 1) Bỏ từng biến bắt buộc; 2) khởi động. | Từ chối cấu hình không an toàn; lỗi đủ chẩn đoán; không phục vụ session/job nửa khởi tạo. |
| TC-ENV-003 | P0 · S · SRC | DB thuộc tenant B; service cấu hình tenant A. | 1) Trỏ service A vào DB B; 2) khởi động. | Startup bị chặn; không bootstrap, sửa dữ liệu hay phát job vào tenant B. |
| TC-ENV-004 | P0 · S · SRC | Runtime DB role có superuser/createdb/createrole/bypassrls. | 1) Cấp từng quyền trên DB test; 2) startup production. | Guard từ chối; runtime hợp lệ không có DDL/admin capability. |
| TC-ENV-005 | P1 · R · SRC | Restart stack; đã có users, lịch và dữ liệu. | 1) Ghi snapshot D-STATE; 2) restart; 3) đối soát. | Mật khẩu không bị bootstrap ghi đè; SQL/queue giữ checkpoint; job dở dang có trạng thái truy vết. |
| TC-ENV-006 | P1 · N · SRC | Sai cú pháp tenant, wildcard Origin hoặc worker token trùng/ngắn. | 1) Thử từng cấu hình sai; 2) startup. | Fail closed; không tự rơi về token dùng chung/default hoặc Origin bất kỳ. |
| TC-ENV-007 | P1 · O · SRC | Health và readiness khi PostgreSQL ngắt kết nối. | 1) Ngắt DB test; 2) gọi hai endpoint; 3) phục hồi. | Liveness không bị hiểu là readiness; ready báo không sẵn sàng; không trả DB lỗi giả thành healthy. |
| TC-ENV-008 | P1 · O · CFG | Nginx/API origin cùng host và reverse proxy. | 1) Mở UI; 2) gọi API/socket; 3) tải sâu #settings. | Assets/API/socket định tuyến đúng; SPA không che lỗi API bằng HTML 200. |
| TC-ENV-009 | P1 · N · SRC | Trùng port hoặc Docker không chạy; launcher trên OS mục tiêu. | 1) Chiếm port/stop Docker test; 2) chạy launcher. | Dừng với lỗi rõ; không kill dịch vụ khác, xóa volume hay ghi đè cấu hình. |
| TC-ENV-010 | P1 · S · SRC | Service documents/DB ở mạng riêng. | 1) Kiểm tra connectivity matrix M-NET; 2) thử kết nối bị cấm. | Chỉ kết nối được cấp quyền; runner/web không đọc DB hoặc gọi Docker socket. |

### 7.2. Đăng nhập, session và logout (AUTH)

**Phụ trách:** Backend + AppSec + QA. **Tác động:** Nội vi; browser và proxy ngoại vi. **Nguồn:** `app/api/auth.py; app/security.py; app/security_limits.py; AuthGate.tsx; session-activity.ts`.

| ID | Ưu tiên / loại / căn cứ | Tình huống và tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
| --- | --- | --- | --- | --- |
| TC-AUTH-001 | P0 · F · SRC | U-ADMIN có MFA; U-MEMBER hợp lệ. | 1) Login đúng credential; 2) đọc /me; 3) tải dashboard. | Đúng user/role/tenant; browser dùng cookie; không có bearer bí mật trong localStorage/response browser. |
| TC-AUTH-002 | P0 · N · SRC | Sai password, user không tồn tại hoặc disabled. | 1) Login từng trường hợp; 2) kiểm tra session và audit. | Không tạo session; lỗi credential không tiết lộ user tồn tại; ghi sự kiện an toàn. |
| TC-AUTH-003 | P1 · B · SRC | Username/password rỗng và biên 1/128/129, 1/1024/1025 ký tự. | 1) Submit UI và API trực tiếp từng giá trị. | Validation đúng giới hạn; input không cắt âm thầm; không gây 500 hoặc lộ password. |
| TC-AUTH-004 | P0 · S · SRC | Token sửa chữ ký, exp, tenant hoặc session ID. | 1) Gửi từng token giả tới GET/mutation/socket. | Bị từ chối; không đọc dữ liệu, ghi state hoặc gia nhập room. |
| TC-AUTH-005 | P0 · B · SRC | Session tuyệt đối 12 giờ; đồng hồ test điều khiển được. | 1) Kiểm tra trước biên, đúng biên và sau biên; 2) REST/socket. | Hết hạn đúng biên; activity không kéo dài tuyệt đối; UI quay về login, socket đóng. |
| TC-AUTH-006 | P0 · B · SRC | Session idle 60 phút; đang có polling/socket heartbeat. | 1) Không thao tác 60 phút; 2) kiểm tra before/at/after. | Polling/heartbeat không gia hạn idle; API từ chối và UI logout khi hết hạn. |
| TC-AUTH-007 | P1 · F · SRC | Người dùng thực sự thao tác UI; nhiều tab dùng một session. | 1) Pointer/keyboard/input/wheel; 2) kiểm tra activity/deadline. | Activity hợp lệ cập nhật có giới hạn; tab khác xác minh deadline mới; không logout nhầm. |
| TC-AUTH-008 | P0 · S · SRC | Logout với cookie/session hiện hành. | 1) Logout; 2) dùng lại cookie/bearer/socket cũ. | Session bị revoke trong DB; cookie xóa đúng attributes; socket không tiếp tục nhận sự kiện. |
| TC-AUTH-009 | P1 · C · SRC | Login/logout đồng thời với request /me hoặc hydrate state chậm. | 1) Giữ phản hồi cũ; 2) logout/login user khác; 3) trả phản hồi. | Phản hồi session cũ không mount dashboard hoặc ghi state của user mới. |
| TC-AUTH-010 | P0 · S · SRC | Cookie mutation thiếu/sai/cũ CSRF token. | 1) POST/PUT/PATCH/DELETE; 2) đổi session rồi replay CSRF. | 403 và không side effect; token đúng mới cho phép; GET không đổi trạng thái ngầm. |
| TC-AUTH-011 | P0 · S · SRC | Cookie session trên HTTPS và cross-site request. | 1) Kiểm tra HttpOnly/SameSite/Secure; 2) fetch từ Origin khác. | Script không đọc cookie; Origin ngoài allowlist bị chặn; Secure đúng cấu hình production TLS. |
| TC-AUTH-012 | P1 · B · SRC | Rate limits login qua API trực tiếp và Nginx. | 1) Dùng virtual clock đạt ngưỡng L-LIMIT; 2) vượt và chờ reset. | 429/Retry-After; ngưỡng account/IP/global độc lập; restart và concurrency không reset quota. |
| TC-AUTH-013 | P1 · N · SRC | X-Real-IP giả; request trực tiếp và qua trusted proxy. | 1) Gửi header giả từ nguồn không tin cậy; 2) so audit/quota. | Chỉ proxy tin cậy được cung cấp IP; không bypass rate limit hoặc giả actor. |
| TC-AUTH-014 | P1 · N · SRC | API unavailable, auth chưa cấu hình hoặc hydrate SQL lỗi. | 1) Mở/refresh UI; 2) phục hồi service. | Hiển thị đúng lỗi/setup; không mount màn hình có quyền khi chưa xác minh user/state. |

### 7.3. MFA, enrollment và recovery code (MFA)

**Phụ trách:** AppSec + Backend. **Tác động:** Nội vi; authenticator/đồng hồ ngoại vi. **Nguồn:** `app/mfa.py; app/api/auth.py; AuthGate.tsx`.

| ID | Ưu tiên / loại / căn cứ | Tình huống và tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
| --- | --- | --- | --- | --- |
| TC-MFA-001 | P0 · F · SRC | Admin mới chưa có MFA; production yêu cầu MFA. | 1) Login password đúng; 2) thử API với setup challenge. | Chỉ nhận enrollment challenge; chưa có session truy cập; không bypass bằng đổi browserSession. |
| TC-MFA-002 | P0 · F · SRC | Enrollment challenge hợp lệ; authenticator test. | 1) Enroll; 2) xác nhận TOTP; 3) login lại. | Secret mã hóa trong DB; MFA active; session cũ revoke; recovery code chỉ hiện khi tạo. |
| TC-MFA-003 | P0 · N · SRC | Challenge giả/sai tenant/hết 5 phút; password hoặc role vừa đổi. | 1) Gọi enroll/confirm từng challenge. | Từ chối; không thay MFA hoặc tạo session từ credential đã mất hiệu lực. |
| TC-MFA-004 | P0 · B · SRC | TOTP đúng/sai; window hiện tại, trước/sau một slot và ngoài window. | 1) Điều khiển giờ test; 2) login/confirm các mã. | Chỉ window hỗ trợ được chấp nhận; mã sai không tạo session; time skew được chẩn đoán. |
| TC-MFA-005 | P0 · C · SRC | Một TOTP replay và hai login đồng thời cùng mã. | 1) Dùng mã hai lần/song song; 2) đọc last_counter. | Tối đa một lần xác minh thành công; counter lưu nguyên tử. |
| TC-MFA-006 | P0 · C · SRC | Recovery code hợp lệ, dùng lại hoặc đồng thời. | 1) Login bằng code; 2) replay/song song. | Mỗi code dùng một lần; DB chỉ lưu hash; format chuẩn hóa không phá one-use. |
| TC-MFA-007 | P1 · B · SRC | OTP rỗng, 5/6/7 ký tự, chữ; confirm chưa enroll/hết hạn. | 1) Submit UI/API các biến thể. | Validation/lỗi rõ; không lỗi 500; enrollment cũ không ghi đè MFA đã bật. |
| TC-MFA-008 | P1 · S · SRC | Enrollment/confirm đạt và vượt quota. | 1) Gọi ở biên; 2) restart/replay challenge. | Quota bền vững; 429 đúng; secret/recovery codes không xuất hiện trong audit/log. |
| TC-MFA-009 | P0 · N · SRC | MFA encryption key thiếu, sai hoặc ciphertext hỏng. | 1) Enroll/login trên dữ liệu test; 2) quan sát lỗi. | Fail closed; không bỏ qua second factor; lỗi không lộ secret hoặc ciphertext. |
| TC-MFA-010 | P1 · R · CFG | Mất authenticator và hết recovery codes. | 1) Thực hiện runbook khôi phục danh tính đã duyệt. | Có xác minh độc lập, phê duyệt/audit; không reset MFA chỉ dựa vào yêu cầu UI chưa xác thực. |

### 7.4. Phân quyền, ownership và tách doanh nghiệp (ACL)

**Phụ trách:** AppSec + Backend + Product. **Tác động:** Nội vi và ranh giới triển khai ngoại vi. **Nguồn:** `app/access.py; app/main.py; app/security.py; app/deployment_security.py`.

| ID | Ưu tiên / loại / căn cứ | Tình huống và tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
| --- | --- | --- | --- | --- |
| TC-ACL-001 | P0 · S · SRC | Anonymous, admin, member, disabled và revoked cho mọi route A-API. | 1) Chạy ma trận M-API-ROLE; 2) kiểm tra DB trước/sau. | Chỉ thao tác được allowlist mới thành công; deny không side effect; route cũ không bypass. |
| TC-ACL-002 | P0 · S · SRC | Member biết URL Settings/Filters và endpoint quản trị. | 1) Deep-link; 2) gọi users/schedules/jobs/pool/audit trực tiếp. | UI từ chối; API/socket cũng từ chối; không dựa riêng nút ẩn. |
| TC-ACL-003 | P0 · F · SRC | Member đọc kho báo cáo dùng chung trong cùng deployment. | 1) Đọc/search/export/coverage; 2) đối chiếu policy P-TENANT. | Đúng quyền tham chiếu chung đã duyệt; không đọc browser state, credential hoặc quản trị. |
| TC-ACL-004 | P0 · S · SRC | Token tenant A dùng tại deployment B; ID tài nguyên B đã biết. | 1) Gửi REST/socket/download; 2) so audit hai môi trường. | B từ chối tenant/signature/session khác; không rò metadata, số dòng hoặc dữ liệu riêng. |
| TC-ACL-005 | P0 · S · SRC | Worker A dùng credential của mình với runner ID/job/state B. | 1) REST và socket đổi ID; 2) upload hoặc sửa trạng thái. | Bị từ chối; dữ liệu B nguyên vẹn; ghi security worker deny theo đường được hỗ trợ. |
| TC-ACL-006 | P0 · S · SRC | UI credential vào namespace runner và ngược lại. | 1) Hoán đổi cookie/bearer/worker token trên hai namespace/API. | Không nâng quyền chéo; auth cho một transport không cấp quyền mọi route. |
| TC-ACL-007 | P0 · S · SRC | Admin đổi role/khóa user/reset password đang mở REST/socket. | 1) Thay quyền; 2) dùng lại session/socket cũ ngay. | Quyền mới/revoke có hiệu lực; không tiếp tục event hoặc mutation theo quyền cũ. |
| TC-ACL-008 | P1 · S · SRC | Admin A1 truy cập session/schedule của admin A2 cùng deployment. | 1) List/detail/pause/delete theo policy đã chốt. | Hành vi quản trị toàn deployment đúng P-TENANT; không suy diễn đây là tenant isolation. |
| TC-ACL-009 | P0 · S · SRC | Tài nguyên không tồn tại hoặc không được quyền. | 1) Đổi UUID/file name/path/state key; 2) so response. | 401/403/404 theo contract; không lộ secret, SQL hoặc nội dung tài nguyên. |
| TC-ACL-010 | P0 · S · CFG | Chuyển tenant database/browser/backup config. | 1) Dùng volume/key sai tenant; 2) startup/restore test. | Phát hiện mismatch; không nhập dữ liệu/cookie doanh nghiệp khác mặc định. |
| TC-ACL-011 | P0 · S · GAP | Yêu cầu nhiều tenant trong một DB/pool. | 1) Chạy toàn ma trận A/B nếu chọn shared SaaS. | Phải có membership/tenant ACL end-to-end; nếu chưa hỗ trợ ghi GAP, không cấp nhãn PASS từ deployment đơn tenant. |
| TC-ACL-012 | P1 · S · CFG | Tài khoản nhân viên rời công ty; đang có lịch chạy. | 1) Offboard; 2) kiểm tra session, role, lịch và audit. | Session thu hồi; lịch xử lý theo quyết định chủ sở hữu; không chạy vô chủ hoặc xóa kết quả âm thầm. |

### 7.5. Account settings và quản lý user (ACCT)

**Phụ trách:** QA + Frontend + Backend. **Tác động:** Nội vi; thao tác người dùng. **Nguồn:** `AccountSettings.tsx; DataManagement.tsx; app/api/data.py; app/api/auth.py`.

| ID | Ưu tiên / loại / căn cứ | Tình huống và tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
| --- | --- | --- | --- | --- |
| TC-ACCT-001 | P1 · U · SRC | Admin mở WORKSPACE ACCESS trên desktop/mobile. | 1) Chuyển Profile/Password/Manage users nhiều lần. | Chỉ panel được chọn hiện; khung không đổi kích thước/vị trí; nội dung dài cuộn bên trong. |
| TC-ACCT-002 | P1 · U · SRC | Member mở Account settings. | 1) Dùng tab/keyboard; 2) kiểm tra DOM/API. | Có Profile/Password; không có quản trị; logout ở Profile hoạt động. |
| TC-ACCT-003 | P1 · F · SRC | Đổi password đúng current; hai phiên cùng user. | 1) Lưu password mới; 2) dùng credential/session cũ. | Password băm mới; giữ phiên hiện tại theo contract; các phiên khác revoke; audit không chứa password. |
| TC-ACCT-004 | P0 · N · SRC | Current sai, new trùng current hoặc confirm không khớp. | 1) Submit từng lỗi; 2) thử login password cũ. | Không thay hash/revoke nhầm; validation rõ; trường password không bị log. |
| TC-ACCT-005 | P1 · B · SRC | Tạo user: username hợp lệ/trùng/sai pattern; password 11/12/1024/1025. | 1) Create bằng UI/API; 2) kiểm tra DB/login. | Giới hạn thống nhất; duplicate không ghi đè; role mới đúng chính sách. |
| TC-ACCT-006 | P0 · F · SRC | Admin reset password user khác; user đang có nhiều session. | 1) Reset; 2) kiểm tra session/socket/user hash. | User mục tiêu revoke; user khác không ảnh hưởng; self-reset dùng luồng current-password theo UI. |
| TC-ACCT-007 | P0 · C · SRC | Grant/Revoke admin hoặc disable trùng thao tác hai người. | 1) Gửi mutation đồng thời; 2) refresh bảng/role. | Trạng thái DB nhất quán; không privilege escalation, race hồi quyền hoặc UI báo sai. |
| TC-ACCT-008 | P1 · N · SRC | Danh sách users/panel lỗi mạng; submit đang chờ. | 1) Ngắt phản hồi; 2) đổi panel/close/Escape; 3) phục hồi. | Không gửi lặp mutation; lỗi hiện trong panel đúng; khung cố định; không để form pending vĩnh viễn. |
| TC-ACCT-009 | P1 · U · SRC | Danh sách 0/1/100 user; username dài. | 1) Mở Manage users; 2) cuộn/xem actions. | Không tràn dialog; bảng/actions vẫn truy cập được; dữ liệu không bị cắt không có cách xem. |
| TC-ACCT-010 | P1 · U · SRC | Keyboard tab/arrow/Home/End/Escape; đóng rồi mở lại. | 1) Duyệt toàn chức năng chỉ bằng bàn phím. | Focus đúng panel; Escape theo busy policy; đóng xóa password; mở mặc định Profile. |
| TC-ACCT-011 | P0 · C · SRC | Hai admin cuối cùng đồng thời tự demote/disable. | 1) PATCH song song; 2) đếm active admins. | Luôn còn ≥1 active admin; loser409; không lockout toàn deployment. |
| TC-ACCT-012 | P0 · N · SRC | Role ngoài admin/user; mutation tự reset hoặc field nhạy cảm lạ. | 1) Gửi API trực tiếp; 2) thử đăng nhập/quyền. | Role/schema theo contract; self-reset409; không tự cấp quyền hoặc ghi password_hash. |

### 7.6. Điều hướng, responsive và khả năng sử dụng (UI)

**Phụ trách:** QA + Frontend. **Tác động:** Nội vi; browser, thiết bị và người dùng ngoại vi. **Nguồn:** `App.tsx; styles.css; use-live-query.ts; AuthenticatedDownload.tsx`.

| ID | Ưu tiên / loại / căn cứ | Tình huống và tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
| --- | --- | --- | --- | --- |
| TC-UI-001 | P1 · U · SRC | Admin/member và mọi hash hỗ trợ. | 1) Mở/refresh/back/forward; 2) link hash cũ #health. | Nav đúng Exported Reports/Filters/Settings; route cũ xử lý rõ; không tái hiện Create Report đã bỏ. |
| TC-UI-002 | P1 · U · SRC | 320/390/768/1024/1440/1920px; zoom 100/200/400%. | 1) Mở các panel/modal; 2) thay nội dung dài. | Không chồng controls; nội dung/cuộn có thể dùng; dialog trong viewport; focus/nút đóng luôn truy cập. |
| TC-UI-003 | P1 · U · CFG | Chrome/Edge/Firefox/Safari phiên bản được duyệt. | 1) Chạy critical UI flows trên từng browser. | Control native căn hàng; download/dialog/socket tương thích; không lỗi riêng Safari hoặc stale assets. |
| TC-UI-004 | P1 · U · SRC | Progress tăng 9→10→1000; tên profile/status dài. | 1) Phát fixture cập nhật liên tục; 2) đo vị trí controls. | Bố cục không nhảy làm nhấn nhầm; số không đè nút; status/counter đọc được. |
| TC-UI-005 | P1 · N · SRC | Query A chậm, query B mới trả trước. | 1) Đổi filter/năm/dataset nhanh; 2) trả A muộn. | Chỉ B hiển thị; không trộn dữ liệu/export label của A với B. |
| TC-UI-006 | P1 · U · SRC | Loading/empty/error/retry states. | 1) Lần lượt trả 200 empty, 401, 403, 429, 503. | Thông báo có hành động phù hợp; không hiện số 0 như dữ liệu đã thu thập khi chưa tải được. |
| TC-UI-007 | P1 · U · CFG | Keyboard/screen reader và độ tương phản. | 1) Duyệt form/table/modal; 2) kiểm tra accessible names/live region. | Có label/focus/trạng thái lỗi; focus không thoát modal; màu không là cách nhận biết duy nhất. |
| TC-UI-008 | P1 · R · SRC | Reload/đóng tab khi phiên backend chạy. | 1) Đóng toàn dashboard; 2) mở lại sau tiến độ mới. | Scheduled queue vẫn chạy; UI đọc checkpoint server; không tự tạo phiên/case mới. |
| TC-UI-009 | P2 · U · SRC | Clipboard được cho phép/bị chặn và nhiều lỗi giống nhau. | 1) Copy diagnostics/errors; 2) từ chối clipboard. | Chỉ báo Copied sau thành công; lỗi hiển thị; grouping không gộp lỗi khác nhau. |
| TC-UI-010 | P1 · U · SRC | Tải file khi token hết hạn, mạng chậm hoặc người dùng hủy. | 1) Download; 2) gây lỗi và tải lại. | Không tải trang login/JSON thành Excel; tên file đúng; trạng thái lỗi không khóa UI. |
| TC-UI-011 | P1 · U · CFG | Mobile xoay ngang/dọc và virtual keyboard đang mở trong dialog. | 1) Focus password/search; 2) rotate; 3) chuyển panel. | Không mất field/focus; close/submit và scroll vẫn truy cập; frame ổn định theo viewport hiện tại. |

### 7.7. Filter profile, options và lập kế hoạch (PROF)

**Phụ trách:** QA + Backend + RPA. **Tác động:** Nội vi và VAHAN ngoại vi. **Nguồn:** `FilterProfiles.tsx; app/models/filter_profile.py; app/filter_planner.py; app/api/filter_profiles.py`.

| ID | Ưu tiên / loại / căn cứ | Tình huống và tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
| --- | --- | --- | --- | --- |
| TC-PROF-001 | P1 · F · SRC | D-PROFILE hợp lệ có State/RTO/Archive và năm. | 1) Create/update/reload/delete; 2) đối chiếu SQL. | Lưu đúng definition/revision; xóa không xóa kết quả/lịch snapshot đã tạo. |
| TC-PROF-002 | P1 · B · SRC | Tên 0/1/120/121; whitespace, Unicode; revision thiếu/cũ. | 1) Gửi từng biến thể; 2) hai editor cùng sửa. | Validation rõ; optimistic revision chặn ghi đè bản mới. |
| TC-PROF-003 | P1 · B · SRC | maxCases 0/1/3000/3001; bool/string/float. | 1) Lưu profile và preview ở từng biên. | Chỉ integer 1–3000; không âm thầm cắt plan hoặc bypass bằng kiểu dữ liệu. |
| TC-PROF-004 | P1 · B · SRC | Values/include 100/101, exclude 500/501, rules 30/31. | 1) Kiểm tra biên danh sách và field lạ. | Schema reject đúng; không tạo tổ hợp ngoài định nghĩa. |
| TC-PROF-005 | P1 · F · SRC | Fixed và Iterate all, include/exclude của 15 fields. | 1) Preview từng policy với D-OPTIONS. | Chỉ giá trị hợp lệ; scalar một fixed value; exclude ưu tiên theo rule, không sinh duplicate. |
| TC-PROF-006 | P1 · N · SRC | State/RTO/Archive/region thiếu; rule self/field lạ. | 1) Save/preview; 2) kiểm tra plan/worker. | Chặn lựa chọn bắt buộc/rule sai; chưa Apply hoặc publish queue. |
| TC-PROF-007 | P1 · F · SRC | Options phụ thuộc region→State→RTO, group→sub→class, EV→fuel. | 1) Đổi parent; 2) load child options. | Child đúng context; giá trị cũ bị xóa/đánh dấu; cache không dùng sai parent. |
| TC-PROF-008 | P1 · C · SRC | Hai preview/options tranh worker; đang có job. | 1) Gửi đồng thời; 2) theo lease và assignment. | Lease độc quyền; không sửa trang job đang chạy; busy có retry hữu hạn. |
| TC-PROF-009 | P1 · F · SRC | Maker chứa dấu phẩy, Unicode, dấu cách và tên gần nhau. | 1) Search/select; 2) preview/filter verification. | Tên nguyên vẹn trong mảng; không split nhầm, bỏ dấu hoặc chọn hãng gần giống. |
| TC-PROF-010 | P1 · N · SRC | Option biến mất/đổi label, options request timeout/401. | 1) Thay fixture portal khi preview; 2) retry. | Chặn giá trị không xác minh; lỗi phân loại; không giả plan hoàn chỉnh. |
| TC-PROF-011 | P1 · F · SRC | D-PLAN12 có rules và tổ hợp phụ thuộc. | 1) Preview; 2) so danh sách độc lập của oracle. | Đúng toàn bộ caseKey/filter/order/count; không sinh Cartesian product không hợp lệ. |
| TC-PROF-012 | P1 · B · SRC | 0/1/3000/>3000 case hoặc quá nhiều context phụ thuộc. | 1) Preview các plan biên. | 0/over-limit báo lỗi; 1/3000 đầy đủ; không cắt case silently. |
| TC-PROF-013 | P1 · R · SRC | Hủy/đóng preview giữa NDJSON stream. | 1) Cancel; 2) mở preview mới/khởi chạy. | Lease/request được giải phóng; incomplete plan không được dùng chạy. |
| TC-PROF-014 | P0 · F · SRC | Lịch tạo với revision N; profile sau đó đổi N+1. | 1) Đặt lịch; 2) sửa/xóa profile; 3) kích hoạt. | Chạy snapshot N đã lưu và kiểm tra options live; không đổi scope của lịch âm thầm. |

### 7.8. UI Health, SQL contract và fail-closed preflight (UH)

**Phụ trách:** RPA + Backend + QA. **Tác động:** Nội vi và thay đổi DOM ngoại vi. **Nguồn:** `app/repositories/ui_contract.py; app/api/ui_health.py; ui-health-contract.mjs; UiHealthContract.tsx`.

| ID | Ưu tiên / loại / căn cứ | Tình huống và tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
| --- | --- | --- | --- | --- |
| TC-UH-001 | P0 · F · SRC | 1/10 worker selected; DOM fixture đầy đủ. | 1) Preflight; 2) preview/publish/claim. | PASS cần evidence SQL của đủ workers và cùng version; chỉ sau gate mới tải Maker/assign. |
| TC-UH-002 | P0 · N · SRC | Một worker offline/busy/không ACK hoặc SQL không xác minh. | 1) Start/resume; 2) thử gọi queue/job trực tiếp. | WAITING/BLOCKED đúng lý do; không bypass qua API/socket cũ; không case Apply. |
| TC-UH-003 | P0 · B · SRC | Gate thiếu, sai owner, thiếu worker, version cũ, tuổi 5 phút. | 1) Dùng before/at/after biên; 2) options/start/resume. | Chỉ gate đúng binding và freshness hợp lệ; gate cũ không tự được gia hạn. |
| TC-UH-004 | P0 · N · SRC | Missing control, wrong type, sai multiplicity hoặc duplicate selector. | 1) Thay từng DOM control; 2) preflight. | BLOCKED với expected/actual/worker; không tạo contract mới từ evidence không hợp lệ. |
| TC-UH-005 | P1 · F · SRC | Selector ID đổi nhưng semantic name/label xác minh được. | 1) Quan sát DOM; 2) preflight; 3) chạy case fixture. | Revision immutable mới lưu SQL; runner dùng selector đã xác minh; bản cũ truy vết được. |
| TC-UH-006 | P0 · N · SRC | Cả name/label đổi hoặc semantic match mơ hồ. | 1) Đưa candidate chưa chứng minh; 2) retry. | Không tự repair hoặc ép allowed; diagnostic cụ thể; chặn dữ liệu sai. |
| TC-UH-007 | P1 · C · SRC | Workers nhìn hai DOM versions; contract đổi giữa check và claim. | 1) Preflight song song; 2) đổi version trước publish. | Gate bị vô hiệu nếu versions không đồng nhất; recheck toàn worker trước tiếp tục. |
| TC-UH-008 | P1 · F · SRC | DOM hợp lệ nhưng options hash thay đổi. | 1) Thay options; 2) preflight/preview lại. | Ghi DATA_CHANGED/diagnostics đúng; cập nhật option state; không coi khác options là no-data. |
| TC-UH-009 | P1 · N · SRC | Evidence ban đầu lỗi tạm hoặc ACK timeout. | 1) Lần một fail; 2) lần hai pass/fail. | Retry hữu hạn theo contract; cuối cùng pass đúng evidence hoặc block, không vòng lặp vô hạn. |
| TC-UH-010 | P0 · S · SRC | Client tự gửi PASS/observedControls bằng bearer hoặc runner ID khác. | 1) Gửi log/preflight giả; 2) đọc SQL contract. | Không tự chứng nhận SQL PASS; chỉ worker được xác thực mới cung cấp evidence đúng ID. |
| TC-UH-011 | P1 · U · SRC | Settings khi không có lỗi, khi block, sau reload và sửa lỗi. | 1) Chuyển các trạng thái; 2) Copy all/per-error. | Không lỗi thì panel ẩn; lỗi tồn tại sau reload; copy có context an toàn và ACK clipboard. |
| TC-UH-012 | P1 · F · SRC | API UI-health schedule/run-now/reports cũ còn tồn tại. | 1) Dùng admin/worker/member; 2) thử chạy khi job busy. | ACL và giới hạn đúng; kiểm tra riêng không phá active job; UI không tái thêm lịch kiểm tra riêng. |
| TC-UH-013 | P1 · B · SRC | CSV/log ngày UTC+7, logId lặp và sai date/file name. | 1) Lưu hai lần; 2) đọc/download ở biên ngày. | Không duplicate; ngày/encoding/header đúng; bad date/path không đọc file khác. |
| TC-UH-014 | P0 · R · SRC | DB fail sau DOM pass trước persist preflight. | 1) Chặn SQL write; 2) thử tạo queue. | Không sử dụng PASS chỉ trong RAM; lỗi bền vững/khả phục hồi; không publish trước commit gate. |

### 7.9. Lịch Once/Daily/Monthly và điều khiển phiên (SCH)

**Phụ trách:** QA + Backend + Frontend. **Tác động:** Nội vi; thời gian/người dùng ngoại vi. **Nguồn:** `app/run_scheduler.py; app/repositories/run_schedules.py; app/models/run_schedule.py; AutomaticRunSettings.tsx`.

| ID | Ưu tiên / loại / căn cứ | Tình huống và tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
| --- | --- | --- | --- | --- |
| TC-SCH-001 | P1 · F · SRC | Lịch Once; profile hợp lệ, 1/10 workers. | 1) Tạo giờ tương lai; 2) qua thời điểm kích hoạt. | Một session/plan đúng snapshot; không chạy sớm hoặc hai lần; kết thúc không có future start. |
| TC-SCH-002 | P1 · B · SRC | startsAt quá khứ/hiện tại/không timezone; year biên, bool/string. | 1) Submit từng giá trị UI/API. | Reject sai; UTC+7 hiển thị đúng UTC lưu; năm tương lai không crawl. |
| TC-SCH-003 | P1 · F · SRC | Daily lúc 23:59 UTC+7; server chạy UTC. | 1) Chạy qua ngày; 2) kiểm tra nextRunAt. | Giữ giờ Việt Nam; không lệch ngày hoặc lặp do đổi timezone máy. |
| TC-SCH-004 | P1 · B · SRC | Monthly ngày 28/29/30/31; tháng ngắn/năm nhuận. | 1) Tạo ngày gốc; 2) đi qua Feb/Apr/Mar. | Clamp cuối tháng cần thiết; tháng sau quay về ngày gốc; không trôi lịch tích lũy. |
| TC-SCH-005 | P1 · R · SRC | Server offline qua nhiều slot Daily/Monthly. | 1) Tắt server test; 2) qua các slot; 3) khởi động. | Áp dụng chính sách bỏ slot cũ; không tạo backlog vô hạn hoặc chạy trùng. |
| TC-SCH-006 | P1 · C · SRC | Nhiều lịch cùng hạn; workers đang bận preview/job. | 1) Đến hạn đồng thời; 2) giải phóng workers. | Giữ lịch chờ; điều phối không vượt capacity; không mất/silently complete lịch. |
| TC-SCH-007 | P0 · F · SRC | Tắt future runs khi lịch đang RUNNING. | 1) Disable; 2) theo phiên hiện tại và slot tiếp. | Phiên hiện tại vẫn chạy; future slot không khởi tạo; toggle không đồng nghĩa Pause/Stop. |
| TC-SCH-008 | P1 · R · SRC | Pause từ PREPARING/RUNNING/RESUMING. | 1) Pause; 2) đợi active case lưu; 3) đọc queue. | PAUSING→PAUSED; không claim mới; kết quả đang commit giữ nguyên. |
| TC-SCH-009 | P0 · F · SRC | PAUSED với queue còn việc; tăng/giảm 1–10 workers. | 1) Chọn worker; 2) Continue. | Cùng session/case/filter; preflight mới; worker limit mới áp dụng; không chạy lại case hợp lệ. |
| TC-SCH-010 | P1 · N · SRC | Đổi worker/resume khi RUNNING/PAUSING hoặc hoàn tất hết case. | 1) Gọi API trực tiếp với state sai. | 409/no-op idempotent theo contract; không mutation queue/elapsed ngoài ý muốn. |
| TC-SCH-011 | P1 · F · SRC | Stop khác Pause; có active case và pending case. | 1) Stop; 2) kiểm tra job/queue/report. | Job dừng đúng policy; dữ liệu đã commit giữ; trạng thái và khả năng tiếp tục rõ. |
| TC-SCH-012 | P0 · F · SRC | Delete lịch sau pause/stop; còn pending và dữ liệu đã thu thập. | 1) Delete; 2) đối soát queue/report/history. | Lịch/case còn lại bị loại theo contract; báo cáo đã commit không mất; không auto-run lại. |
| TC-SCH-013 | P0 · N · SRC | Delete lịch khi PREPARING/RUNNING/PAUSING/RESUMING. | 1) UI và API trực tiếp. | Không cho xóa trong state không an toàn; active commit/worker không thành orphan. |
| TC-SCH-014 | P0 · C · SRC | Pause/resume/stop/delete đua scheduler callback cũ. | 1) Giữ callback; 2) đổi state/epoch; 3) trả callback. | Fencing session/epoch bỏ callback cũ; queue không bị kích hoạt lại sau lệnh mới. |
| TC-SCH-015 | P1 · R · SRC | API restart và hai scheduler process cạnh tranh. | 1) Khởi động hai instance test; 2) chuyển leader. | Chỉ một leader phát work; checkpoint bền vững; không trùng session/assignment. |
| TC-SCH-016 | P1 · N · SRC | Owner disabled, profile/options invalid hoặc pool thiếu worker. | 1) Kích hoạt lịch; 2) kiểm tra diagnostics. | Thông báo stage/lý do/retry rõ; không treo Preparing vô thời hạn không phản hồi. |
| TC-SCH-017 | P1 · U · SRC | Progress/elapsed khi reload, pause dài, resume. | 1) Lưu timing; 2) reload; 3) pause/resume. | Rate dựa active elapsed server; không reset hoặc spike; pause không tính như thời gian xử lý. |
| TC-SCH-018 | P1 · U · GAP | Yêu cầu ETA còn lại/giờ hoàn thành trong thẻ lịch. | 1) Có mẫu đủ/thiếu/stale; 2) đổi worker và pause. | Hiển thị dự báo hoặc trạng thái chưa đủ dữ liệu; không số âm/giờ sai; chưa render thì ghi GAP. |

### 7.10. Job lifecycle, ACK và state machine (JOB)

**Phụ trách:** Backend + RPA + QA. **Tác động:** Nội vi và transport ngoại vi. **Nguồn:** `app/models/job.py; app/api/jobs.py; realtime/runner_events.py; test-job-lifecycle.mjs`.

| ID | Ưu tiên / loại / căn cứ | Tình huống và tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
| --- | --- | --- | --- | --- |
| TC-JOB-001 | P0 · F · SRC | Toàn bộ 12 trạng thái job và mọi cặp chuyển trạng thái. | 1) Chạy ma trận M-JOB; 2) replay self-transition. | Chỉ cạnh hợp lệ được lưu; terminal không sống lại; self-transition không nhân side effect. |
| TC-JOB-002 | P1 · F · SRC | Create job trên worker online/idle, source new và gate hợp lệ. | 1) Create; 2) đọc job/runner/event. | Một job assigned đúng filters/session/owner; worker busy đúng job; event sau persist. |
| TC-JOB-003 | P1 · N · SRC | Worker offline/reconnecting/busy; source old; gate thiếu. | 1) Create từng trường hợp; 2) so SQL. | 404/409/410 phù hợp; không tạo orphan job hoặc chiếm worker. |
| TC-JOB-004 | P0 · C · SRC | Hai create đồng thời vào một worker. | 1) Gửi cùng lúc; 2) đối soát assignment. | Tối đa một job active; request thua trả conflict; không hai Apply cùng worker. |
| TC-JOB-005 | P0 · F · SRC | SUBMITTING cần backend ACK trước browser click. | 1) Hold ACK; 2) trả ACK success/failure. | Không Apply trước success; ACK deny/timeout không bị coi accepted; đếm click chỉ sau click thật. |
| TC-JOB-006 | P0 · C · SRC | SUBMITTING bị cancel hoặc submit trùng trong lúc ACK. | 1) Chạy hai submission/cancel; 2) quan sát click IDs. | Không bấm Apply lặp; ACK trễ không đảo CANCELLED; click ID dedup đúng. |
| TC-JOB-007 | P0 · N · SRC | Worker gửi COMPLETED trước SQL main-report commit. | 1) Phát status và report-result trái điều kiện. | Không hoàn tất thiếu dữ liệu; lỗi rõ; case vẫn có thể recovery đúng policy. |
| TC-JOB-008 | P0 · R · SRC | Mất kết nối trước/sau Apply nhưng chưa result. | 1) Drop socket từng điểm; 2) reconnect. | Không tự lặp Apply không có quyết định recovery; job gián đoạn truy vết được. |
| TC-JOB-009 | P0 · C · SRC | Cancel đồng thời workbook/no-data commit. | 1) Dùng barrier ở transaction; 2) giải phóng hai luồng. | Một kết quả thắng nguyên tử; không vừa CANCELLED vừa ghi kết quả muộn trái state. |
| TC-JOB-010 | P1 · N · SRC | Cancel terminal/missing/UUID sai. | 1) Gọi API; 2) so state/counters. | 409/404/422 theo contract; không release worker đang chạy job khác. |
| TC-JOB-011 | P0 · R · SRC | API commit assignment thành công nhưng emit/HTTP reply mất. | 1) Cắt transport sau commit; 2) reconcile/retry. | Không tạo job lặp; nguồn sự thật SQL; worker/queue không kẹt bí mật. |
| TC-JOB-012 | P1 · F · SRC | Pagination jobs và report-result offset/limit. | 1) Dùng 0/1/max/max+1, negative offset. | Page/order/ACL đúng; không leak payload lớn/ảnh CAPTCHA; invalid bị reject. |

### 7.11. Hàng đợi SQL, capacity và concurrency (QUEUE)

**Phụ trách:** Backend + DBA + QA. **Tác động:** Nội vi. **Nguồn:** `app/repositories/batch_queue.py; app/api/batch_queue.py; app/worker_pool.py`.

| ID | Ưu tiên / loại / căn cứ | Tình huống và tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
| --- | --- | --- | --- | --- |
| TC-QUEUE-001 | P0 · F · SRC | D-PLAN12; gate đúng; maxWorkers 1/10. | 1) Start queue; 2) claim tới hết; 3) so oracle. | Mọi case được settle đúng một logical case; scope/order/filters giữ nguyên. |
| TC-QUEUE-002 | P1 · B · SRC | Tasks 0/1/3000/3001; count 0/1/10/11/bool. | 1) Start/resume/pool từng biên. | Chỉ schema hợp lệ được publish; không cắt danh sách hoặc vượt worker limit. |
| TC-QUEUE-003 | P0 · C · SRC | 10 worker claim đồng thời; một task pending. | 1) Barrier nhiều claim; 2) kiểm tra job/case IDs. | Một task chỉ một claimant/active job; losers waiting; không duplicate commit. |
| TC-QUEUE-004 | P0 · C · SRC | Cùng session start lại với cùng/khác task payload. | 1) Gửi duplicate/concurrent start. | Idempotent hoặc conflict rõ; không thay plan đã chạy/nhân task. |
| TC-QUEUE-005 | P0 · F · SRC | Pool logical 5; 10 container online. | 1) Claim từ worker 1–10; 2) options/lease đồng thời. | Active assignment+planning không vượt 5; online count không bị hiểu là active capacity. |
| TC-QUEUE-006 | P1 · N · SRC | Giảm pool dưới active jobs/planning leases. | 1) Update limit lúc busy. | Reject không an toàn; không kill container/job hoặc bỏ lease. |
| TC-QUEUE-007 | P1 · F · SRC | Tăng pool khi queue đã có maxWorkers thấp. | 1) Tăng global; 2) quan sát existing/new queue. | Không tự tăng parallelism queue cũ ngoài contract; queue mới dùng giới hạn hợp lệ. |
| TC-QUEUE-008 | P0 · R · SRC | Worker crash hoặc lease hết hạn khi PROCESSING. | 1) Kill worker test; 2) reconcile/claim. | Case gián đoạn không biến mất; phục hồi hữu hạn, giữ retry lineage và nguyên filters. |
| TC-QUEUE-009 | P0 · C · SRC | Pause/resume/settle/claim đồng thời. | 1) Barrier mutations; 2) đối chiếu queue state. | State lock/fencing đúng; pause không claim mới; settle lặp không tăng counter. |
| TC-QUEUE-010 | P0 · S · SRC | Sai owner/session/gate hoặc claim bằng worker không thuộc limit. | 1) Gọi từng endpoint queue trực tiếp. | Deny trước tạo job; không bypass scheduler guard hoặc cross-session mutation. |
| TC-QUEUE-011 | P1 · R · SRC | API restart giữa PRIMARY/CHECKPOINT/FINAL. | 1) Lưu từng phase; 2) restart; 3) đọc snapshot. | Phase/window/counters/attempts còn đủ; không bắt đầu lại plan từ đầu. |
| TC-QUEUE-012 | P0 · N · SRC | Session deleted, invalid task position hoặc terminal job stale. | 1) Settle/claim/resume từng trường hợp. | Không phục hồi deleted session; index ngoài plan không sửa task khác; error hữu ích. |

### 7.12. Retry checkpoint và phục hồi cuối (RETRY)

**Phụ trách:** QA + Backend + RPA. **Tác động:** Nội vi; lỗi worker/portal ngoại vi. **Nguồn:** `batch_queue.py; BatchRetryStatus.tsx; FailedBatchCases.tsx; verification/test_queue_retry_checkpoints.py`.

| ID | Ưu tiên / loại / căn cứ | Tình huống và tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
| --- | --- | --- | --- | --- |
| TC-RETRY-001 | P0 · F · SRC | 12 case; case 3/8 fail một lần. | 1) Chạy 1–10; 2) quan sát checkpoint rồi case 11. | Retry lỗi nhóm trước nhóm kế; case thành công/no-data không lặp. |
| TC-RETRY-002 | P1 · B · SRC | Plan 1/9/10/11/20/21 case. | 1) Inject một fail mỗi nhóm; 2) chạy hết. | Nhóm cuối dưới 10 cũng retry; không bỏ checkpoint biên hoặc tạo nhóm rỗng. |
| TC-RETRY-003 | P0 · F · SRC | Case lỗi cả initial/checkpoint, pass lượt FINAL. | 1) Chạy toàn plan; 2) phân phối final cho workers. | Final chỉ lỗi còn lại; tổng case không tăng; Failed giảm, With data/No data cập nhật. |
| TC-RETRY-004 | P0 · N · SRC | Case lỗi tất cả lượt; quota hiện tại initial+checkpoint+final. | 1) Giữ lỗi; 2) đếm attempts. | Không retry vô hạn; case vẫn FAILED với nguyên lỗi và đủ lineage. |
| TC-RETRY-005 | P0 · F · SRC | NO_DATA đã xác nhận và lỗi timeout/result/CAPTCHA. | 1) Trộn kết quả; 2) xem retry targets. | Chỉ lỗi thực thi được retry; no-data không bị retry hoặc che lấp lỗi. |
| TC-RETRY-006 | P0 · R · SRC | Pause/reload/restart giữa checkpoint hoặc final. | 1) Chặn lúc retry active; 2) resume. | Giữ đúng retry phase/position/attempts; không tăng lượt do reload. |
| TC-RETRY-007 | P0 · F · SRC | Manual retry failed/cancelled; giữ session/case/source/update metadata. | 1) Retry đúng rồi đổi từng field trong API. | Chỉ retry hợp lệ; metadata khác bị chặn; logical case đếm một lần. |
| TC-RETRY-008 | P0 · C · SRC | Manual retry và auto retry cùng case. | 1) Gửi đồng thời; 2) settle các phản hồi. | Không hai retry active cho cùng case; latest accepted attempt/counters nhất quán. |
| TC-RETRY-009 | P1 · U · SRC | Nhiều lỗi giống/khác; có lỗi đã recovery. | 1) Xem/copy Failed cases và diagnostics. | Gom đúng thông báo gốc; exhausted còn hiển thị; không báo recovered trước commit. |
| TC-RETRY-010 | P0 · N · SRC | Session bị delete hoặc UI Health block trước lượt FINAL. | 1) Kích hoạt retry qua mọi đường. | Không vượt ACL/gate; không hồi queue đã xóa; báo nguyên nhân rõ. |
| TC-RETRY-011 | P1 · U · SRC | done=total nhưng FINAL còn PROCESSING/FAILED targets. | 1) Giữ final reply; 2) xem UI/state. | Progress monotonic không bằng completed; phase/failed còn rõ; không báo hoàn tất sớm. |

### 7.13. Browser runner và tương tác VAHAN (RUN)

**Phụ trách:** RPA + QA. **Tác động:** Nội vi và portal/browser ngoại vi. **Nguồn:** `runner.mjs; page-driver.js; page-recovery.mjs; config.mjs`.

| ID | Ưu tiên / loại / căn cứ | Tình huống và tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
| --- | --- | --- | --- | --- |
| TC-RUN-001 | P1 · F · SRC | Worker startup/reconnect; browser state hợp lệ. | 1) Connect/heartbeat; 2) nhận một job. | Registry đúng identity; Chromium sẵn sàng; mỗi worker một job, tái dùng trang đúng. |
| TC-RUN-002 | P0 · F · SRC | Điền 5 nhóm song song; D-OPTIONS dependency chậm. | 1) Fill; 2) xem DOM và filterExecution. | Giữ region→State→RTO, group→sub→class, EV→fuel, axes; final values đúng oracle. |
| TC-RUN-003 | P0 · F · SRC | Trang tái sử dụng còn filter cũ. | 1) Chạy case A; 2) case B bỏ optional values. | Xóa lựa chọn cũ/hidden axis; case B không mang filter của A. |
| TC-RUN-004 | P0 · N · SRC | Request muộn reset field; mismatch ngay trước Apply. | 1) Delay fetch/XHR; 2) verify twice. | Chỉ sửa nhóm bị ảnh hưởng trong giới hạn; mismatch còn lại chặn Apply. |
| TC-RUN-005 | P1 · F · SRC | Maker multi-search và tên dấu phẩy. | 1) Dò nhiều hãng; 2) đo concurrency và selection. | Tối đa concurrency thiết kế; mảng Maker nguyên vẹn; không sửa chéo request. |
| TC-RUN-006 | P0 · N · SRC | Control thiếu/unmapped/disabled; native và hidden values khác. | 1) Đổi DOM fixture; 2) fill/verify. | Dừng trước Apply; expected/actual được lưu; không lấy báo cáo filter sai. |
| TC-RUN-007 | P0 · R · SRC | Một nhóm fill lỗi khi nhóm khác còn chạy. | 1) Fail group; 2) phát case kế tiếp. | Hủy/chờ tác vụ cũ; request cũ không sửa DOM case mới. |
| TC-RUN-008 | P0 · F · SRC | ACK filters-verified không được persist hoặc bị từ chối. | 1) Block ACK; 2) theo Apply. | Không click khi evidence backend chưa xác nhận; không khai báo verified chỉ ở client. |
| TC-RUN-009 | P1 · F · SRC | Kết quả mới có đúng RTO, hết loading. | 1) Apply; 2) thay stale table/loading/marker. | Chỉ đọc result mới đúng context; không dùng bảng từ case trước. |
| TC-RUN-010 | P1 · N · SRC | Portal HTTP401/403/429/5xx hoặc redirect login. | 1) Fixture trả từng response. | Phân loại auth/rate/server lỗi; không coi là NO_DATA; retry hữu hạn theo policy. |
| TC-RUN-011 | P1 · R · SRC | Browser/page crash, navigation timeout, closed tab. | 1) Gây từng lỗi; 2) page recovery/retry. | Job lỗi truy vết; recovery không nhân Apply; page mới/context đúng tenant. |
| TC-RUN-012 | P1 · F · SRC | Workbook download tên lạ/multiple hoặc chậm sau result. | 1) Emit các download events; 2) kiểm tra chọn file. | Chọn đúng report của case; không upload file cũ/sai; timeout có lỗi rõ. |
| TC-RUN-013 | P0 · R · SRC | SQL commit upload thành công nhưng HTTP ACK mất. | 1) Drop reply; 2) gửi lại same workbook. | Idempotent checksum; một report/counter; worker chỉ nhận case tiếp sau confirmed commit. |
| TC-RUN-014 | P1 · S · SRC | Runner browser state/cookie/cache giữa workers/tenant. | 1) Lưu/load state; 2) đổi identity/deployment. | Fernet đúng key; state chỉ worker đúng; không lộ credential trong log/artifact. |

### 7.14. Validation challenge và dữ liệu nhạy cảm (CAP)

**Phụ trách:** RPA + AppSec + QA. **Tác động:** Portal và thao tác vận hành ngoại vi. **Nguồn:** `runner.mjs; image-pipe.mjs; realtime/ui_events.py; realtime/runner_events.py`.

| ID | Ưu tiên / loại / căn cứ | Tình huống và tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
| --- | --- | --- | --- | --- |
| TC-CAP-001 | P1 · F · SRC | Challenge xuất hiện lúc fill/Apply/result. | 1) Phát fixture yêu cầu validation; 2) kiểm tra job. | Trạng thái chờ/lỗi đúng; không COMPLETED hoặc NO_DATA giả khi validation chưa đạt. |
| TC-CAP-002 | P0 · S · SRC | Ảnh challenge/giá trị nhập xuất hiện ở worker. | 1) Kiểm tra filesystem/SQL/API/socket/log sau flow. | Không ghi ảnh mới vào SQL/disk hoặc phát ảnh dashboard trái chính sách; giá trị nhập được che log. |
| TC-CAP-003 | P1 · N · SRC | Submit sai chiều dài, captcha ID cũ, job terminal hoặc worker offline. | 1) Gửi qua socket tương thích. | Reject rõ; không chuyển state hoặc click Apply sai case. |
| TC-CAP-004 | P0 · C · SRC | Submit/refresh/cancel đồng thời; hai operator. | 1) Barrier các events; 2) replay ACK trễ. | Tối đa một submission; captcha ID hiện hành; ACK cũ không thắng state mới. |
| TC-CAP-005 | P1 · N · SRC | Official refresh không ACK hoặc validation liên tục sai. | 1) Refresh/submit fixture; 2) qua deadline. | Timeout/lỗi hữu hạn; case còn retryable theo policy; không bỏ qua validation. |
| TC-CAP-006 | P0 · S · SRC | Challenge chứa text nhạy cảm trong error screenshot/artifact. | 1) Ghi lỗi ảnh; 2) xem ảnh/log dùng tài khoản test. | Ảnh đã che vùng challenge; không lưu cookie/token/password hoặc text nhập. |
| TC-CAP-007 | P1 · R · SRC | Refresh job/captcha ID giữa reconnect. | 1) Ngắt socket; 2) challenge đổi; 3) reconnect/submit cũ. | Chỉ metadata mới được chấp nhận; không gửi lại giá trị cũ tự động. |
| TC-CAP-008 | P1 · U · GAP | Portal cần người vận hành nhưng dashboard chưa có flow hoàn chỉnh. | 1) Diễn tập quy trình validation hợp lệ end-to-end. | Có hướng dẫn/trạng thái tiếp tục rõ; thiếu UI/runbook ghi GAP, không dùng bypass để đánh dấu pass. |

### 7.15. Workbook ingestion và toàn vẹn dữ liệu (DATA)

**Phụ trách:** Backend + DBA + QA. **Tác động:** Nội vi và tài liệu VAHAN ngoại vi. **Nguồn:** `file_store.py; annual_reports.py; report_results.py; app/api/excel.py`.

| ID | Ưu tiên / loại / căn cứ | Tình huống và tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
| --- | --- | --- | --- | --- |
| TC-DATA-001 | P0 · F · SRC | D-XLS đầy đủ nhiều sheet, Maker/State/RTO/năm/12 tháng. | 1) Upload assigned WAITING_RESULT; 2) đối soát mọi ô. | Tất cả sheet đọc; main_reports đúng oracle; job/history/release cùng transaction. |
| TC-DATA-002 | P0 · F · SRC | Blank, null, zero, số có dấu phẩy và OTHERS. | 1) Import D-XLS-VALUES; 2) read/export. | Blank khác 0; số đúng; OTHERS giữ như nhãn; tổng không mất hãng/dòng hợp lệ. |
| TC-DATA-003 | P0 · N · SRC | Wrong year/State/RTO/Maker hoặc header ambiguous. | 1) Upload file sai context; 2) so snapshot. | Reject/rollback toàn filter; không ghi nhầm scope hoặc báo COMPLETED. |
| TC-DATA-004 | P0 · N · SRC | Số âm/fraction/non-numeric/formula và duplicate khác giá trị. | 1) Import từng fixture invalid. | Không có dữ liệu nửa hợp lệ; diagnostic sheet/row/field đủ, không âm thầm bỏ dòng. |
| TC-DATA-005 | P0 · F · SRC | Workbook mới bổ sung Maker/tháng thiếu. | 1) Import baseline; 2) import phần bổ sung. | Chỉ thêm ô/hãng cần; count/provenance đúng; không nhân hàng đã tồn tại. |
| TC-DATA-006 | P0 · F · SRC | Normal crawl newer observed_at thay số cũ. | 1) Nhập t0 rồi t1>t0; 2) đọc provenance/history. | Giá trị t1 cập nhật; giá trị cũ truy vết được; summary updatedCells đúng. |
| TC-DATA-007 | P0 · C · SRC | Kết quả t0 đến sau t1; cùng office hai workers. | 1) Commit đảo thứ tự; 2) đối soát. | Không rollback về số cũ; serialized overlap; RTO độc lập vẫn có thể commit song song. |
| TC-DATA-008 | P1 · N · SRC | Cùng observed_at khác giá trị; metadata thời gian thiếu timezone. | 1) Upload hai nguồn/metadata mơ hồ. | Conflict/reject theo contract; không dùng arrival time để tự chứng minh newer. |
| TC-DATA-009 | P0 · C · SRC | Same job/checksum upload hai lần đồng thời. | 1) Replay/parallel identical file. | Một commit logical; trả kết quả idempotent; history và counters không nhân. |
| TC-DATA-010 | P0 · N · SRC | Same job upload checksum khác sau completed. | 1) Upload file khác; 2) đọc main report. | Conflict; dữ liệu đã xác nhận nguyên vẹn; không overwrite terminal job. |
| TC-DATA-011 | P0 · R · SRC | DB lỗi tại history/rows/job/release transaction. | 1) Inject lỗi từng điểm; 2) retry. | Rollback đồng bộ; worker không giải phóng trước commit; retry an toàn. |
| TC-DATA-012 | P0 · F · SRC | No record found đã xác nhận cho đúng filter/năm. | 1) Submit NO_DATA; 2) xem coverage/history/main. | No-data có nguồn/thời gian; không fake dòng 0; không file Excel giả; có giá trị coverage riêng. |
| TC-DATA-013 | P0 · N · SRC | Timeout/loading/HTTP error bị client gửi như no-data. | 1) Submit result thiếu evidence hoặc stale. | Reject; case giữ lỗi; không tăng coverage hợp lệ hoặc xóa dữ liệu cũ. |
| TC-DATA-014 | P0 · S · SRC | Upload từ wrong worker, bearer admin giả runner hoặc job bị hủy. | 1) Gửi qua main-report và upload-excel cũ. | Deny/no write; cả alias cũ cùng auth/state checks; không lộ main result khác. |
| TC-DATA-015 | P1 · S · SRC | Sau success còn file tạm/Excel/DOM payload trong SQL. | 1) Import; 2) kiểm tra storage/temp/job payload. | Theo policy không lưu bản sao report mới; giữ checksum/provenance cần thiết; temp dọn. |
| TC-DATA-016 | P0 · F · SRC | Thay đổi case filter nhưng cùng Maker/RTO/năm. | 1) Import hai scope khác; 2) query từng dataset. | Không trộn dataset; canonical scope đúng; cùng scope dùng chung trong deployment. |
| TC-DATA-017 | P0 · S · SRC | Report-result DATA chứa DOM tables trước/sau full workbook commit. | 1) Gửi compatibility endpoint; 2) inspect storage. | Trước commit reject; sau commit chỉ ACK compatibility; không lưu DOM copy hoặc nhân kết quả. |

### 7.16. Upload, parser và document service (FILE)

**Phụ trách:** Backend + AppSec + QA. **Tác động:** Nội vi và file/network ngoại vi. **Nguồn:** `file_store.py; document_client.py; document_worker.py; app/api/data.py; app/api/excel.py`.

| ID | Ưu tiên / loại / căn cứ | Tình huống và tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
| --- | --- | --- | --- | --- |
| TC-FILE-001 | P1 · F · SRC | File hỗ trợ XLSX/CSV/JSON/TXT/log với encoding phù hợp. | 1) Upload/import từng loại theo API. | Parser/metadata/rows đúng loại; unsupported không giả workbook; quyền download đúng. |
| TC-FILE-002 | P1 · B · SRC | Upload 0 byte, 50 MiB−1/đúng/＋1 và Nginx 52 MiB. | 1) Gửi streaming/truncated request. | API reject empty/oversize; không giữ file rác; proxy/API phân biệt giới hạn. |
| TC-FILE-003 | P0 · B · SRC | XLSX expanded 250 MiB, 10.000 entries, 500.000 rows. | 1) Thử dưới/đúng/trên từng giới hạn. | Giới hạn enforced; không OOM/commit partial; tính cả các worksheet. |
| TC-FILE-004 | P0 · S · SRC | ZIP hỏng/giả XLSX, đường dẫn nguy hiểm, XML entity. | 1) Import fixture có kiểm soát trên staging. | Không đọc file host, outbound entity hoặc code execution; lỗi bounded/rollback. |
| TC-FILE-005 | P1 · N · SRC | CSV BOM/quote/newline; JSON malformed; text invalid UTF-8. | 1) Import fixture boundary. | Giá trị/cells nguyên vẹn hoặc lỗi encoding rõ; không decode mất chữ âm thầm. |
| TC-FILE-006 | P1 · N · SRC | Parser vượt 120s hoặc giới hạn CPU/RAM. | 1) Fixture slow parser; 2) theo process/temp. | Subprocess bị kết thúc; API không kẹt; temp dọn; case chưa completed. |
| TC-FILE-007 | P1 · C · SRC | Document service chỉ một slot; API bulk slots bị đầy. | 1) Gửi extract/export song song. | 429/503 có recovery rõ; không queue vô hạn, semaphore leak hoặc vượt resource. |
| TC-FILE-008 | P1 · R · SRC | Document service down/reply hỏng/>256 MiB. | 1) Cắt service hoặc sửa response. | Lỗi hữu hạn; production không fallback parser không cô lập; không SQL partial. |
| TC-FILE-009 | P0 · S · SRC | Document service network/credentials boundary. | 1) Inspect env/process; 2) thử từ mạng không được cấp. | Không DB/signing/runner secrets; endpoint internal không public; parser child không nhận secret env. |
| TC-FILE-010 | P1 · N · SRC | File name Unicode, slash, CRLF, rất dài, trùng tên. | 1) Upload/download; 2) kiểm tra headers/path. | Tên an toàn/encoding đúng; không path traversal, header injection hoặc overwrite file khác. |
| TC-FILE-011 | P0 · S · SRC | Artifacts ảnh lỗi có vùng nhạy cảm; file ID khác quyền. | 1) Upload theo job; 2) read rows/download. | Chỉ artifact hợp lệ/đã che; ACL đúng; checksum và content khớp. |
| TC-FILE-012 | P1 · R · SRC | Client disconnect giữa upload/response. | 1) Abort streaming; 2) kiểm tra temp/process/DB. | Tài nguyên được thu hồi; trạng thái rõ; không ghi nửa report hoặc file orphan. |

### 7.17. Bảng chính, tìm kiếm và Excel export (REP)

**Phụ trách:** QA + Frontend + Backend + DBA. **Tác động:** Nội vi và người dùng/Excel ngoại vi. **Nguồn:** `AnnualReports.tsx; annual_reports.py; annual_export.py; AuthenticatedDownload.tsx`.

| ID | Ưu tiên / loại / căn cứ | Tình huống và tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
| --- | --- | --- | --- | --- |
| TC-REP-001 | P1 · F · SRC | Dataset/năm có 205 dòng và 12 tháng. | 1) Xem 3 pages; 2) so D-XLS oracle. | Đúng sort/dòng/ô; không duplicate hoặc thiếu ở pagination; tổng thống kê khớp SQL. |
| TC-REP-002 | P1 · B · SRC | Search State/RTO/code, Unicode, %, _, slash, whitespace. | 1) Tìm từng giá trị; 2) query API tương ứng. | Escape wildcard đúng; không SQL injection; cùng filter trả cùng tập dữ liệu. |
| TC-REP-003 | P1 · F · SRC | Đổi năm/dataset và kết quả 0 dòng. | 1) Đổi nhanh; 2) clear filters. | Offset reset hợp lệ; options/year/summary cùng context; no-data chưa tải không bị lẫn empty thật. |
| TC-REP-004 | P1 · F · SRC | Export UI khi đang search và khi bỏ search. | 1) Search; 2) clear; 3) confirm/cancel Export all. | Theo source UI chỉ export toàn report khi search rỗng; confirm/cancel rõ; không lén export scope khác. |
| TC-REP-005 | P1 · F · SRC | API export filtered State/RTO và export toàn bộ. | 1) GET filtered; 2) GET all với/không confirmAll. | Filtered đủ mọi page; all thiếu confirm bị409; workbook scope đúng query được cho phép. |
| TC-REP-006 | P0 · F · SRC | Export >1 page; file reopen trong Excel/LibreOffice/openpyxl. | 1) Download; 2) so mọi cell/count/title. | Đủ rows, 12months, Maker/RTO Unicode; X-Report-Row-Count đúng; file không hỏng. |
| TC-REP-007 | P1 · B · SRC | Export 0/1/max_export_rows/＋1 và Excel sheet ceiling. | 1) Dùng dataset từng biên. | 0 trả404; quá giới hạn413; hợp lệ đủ dòng; không cắt phần vượt âm thầm. |
| TC-REP-008 | P0 · C · SRC | Data update đồng thời với streaming export. | 1) Giữ snapshot query; 2) commit report mới; 3) hoàn tất export. | Workbook nhất quán một snapshot REPEATABLE READ; không page mix/counter lệch. |
| TC-REP-009 | P1 · N · SRC | Export user/global quota, bulk/DB pressure. | 1) Đạt/vượt ngưỡng L-LIMIT; 2) phục hồi. | 429 hoặc503/Retry-After; không OOM; không mất kết quả đã lưu. |
| TC-REP-010 | P1 · R · SRC | Export disconnect/save/compression lỗi hoặc disk temp đầy. | 1) Abort/error từng điểm; 2) theo temp/DB. | Temp cleanup; connection/slot release; lỗi không gửi file half-valid như success. |
| TC-REP-011 | P1 · F · SRC | Save report phát socket; member dùng polling. | 1) Commit case; 2) đo admin/member refresh. | Bảng cập nhật số đã commit; không cần đợi batch; member không cần quyền admin socket. |
| TC-REP-012 | P1 · F · SRC | Legacy per-job Excel/no-data/report-file endpoints. | 1) Tải file cũ tồn tại/missing/current policy retired. | File cũ đúng ACL/hash; thiếu bản sao mới có lỗi rõ, không giả file hoặc che dữ liệu main. |
| TC-REP-013 | P1 · S · SRC | Maker/cell bắt đầu =,+,-,@ hoặc HTML/script. | 1) Import/export fixture benign; 2) mở file/UI. | Không thực thi script/formula không mong muốn; ô textual giữ nguyên ngữ nghĩa. |
| TC-REP-014 | P1 · U · SRC | Cột cố định, tên dài, zoom/mobile và refresh khi đang cuộn. | 1) Duyệt bảng/đổi page; 2) phát updates. | Header/body đúng hàng; có scroll truy cập đầy đủ; không chồng nhãn, nhảy focus. |

### 7.18. Sessions, update history và coverage (HIST)

**Phụ trách:** QA + Backend + Frontend. **Tác động:** Nội vi; dữ liệu nguồn ngoại vi. **Nguồn:** `report_sessions.py; ExportedReportsList.tsx; UpdateHistory.tsx; update_status.py; report_coverage.py`.

| ID | Ưu tiên / loại / căn cứ | Tình huống và tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
| --- | --- | --- | --- | --- |
| TC-HIST-001 | P1 · F · SRC | Session nhiều attempts cho cùng case, file legacy và statuses mixed. | 1) List/detail paginate; 2) so logical case oracle. | Mỗi case đếm theo latest attempt; summaries không cần tải mọi payload; không inflated Failed/files. |
| TC-HIST-002 | P1 · F · SRC | Delete terminal session rồi Restore. | 1) Xóa có xác nhận; 2) mở Deleted; 3) Restore. | Chỉ ẩn lịch sử; main data/file vẫn giữ; restored đúng session. |
| TC-HIST-003 | P0 · N · SRC | Delete active session hoặc retry/continue session deleted. | 1) UI/API các đường tương thích. | 409/deny; không phá active queue; restore cần trước retry. |
| TC-HIST-004 | P1 · B · SRC | Ngày UTC+7, nhiều phiên/ngày và page vượt count. | 1) Lọc trước/sau midnight; 2) load more/detail. | Đúng ngày bắt đầu, totals/hasMore; không thiếu/nhân session khi polling. |
| TC-HIST-005 | P0 · F · SRC | D-PLAN12 có completed, no-data, failed, review và pending. | 1) POST coverage; 2) so oracle independent. | Chỉ committed data/no-data tính covered; attempted/review/failed không tính đạt. |
| TC-HIST-006 | P1 · F · SRC | Coverage có gap giữa plan; workers hoàn tất lệch thứ tự. | 1) Complete positions 1/3/5; 2) đọc firstMissing/coveredThrough. | Không nhầm last save là liên tục đủ; firstMissing theo plan order. |
| TC-HIST-007 | P1 · N · SRC | Plan/filter/year không tương thích; không có plan; import legacy. | 1) Coverage/update-status các trường hợp. | Unknown/incompatible rõ; không báo100% toàn dataset chỉ từ rows hiện có. |
| TC-HIST-008 | P1 · U · SRC | Update history filter from/to/dataset trên Safari/mobile. | 1) Đổi ranges; 2) mở day details; 3) zoom. | Controls thẳng hàng; bảng cuộn; range invalid reject; dữ liệu/day/status đúng context. |
| TC-HIST-009 | P1 · F · SRC | Cùng ngày nhiều scan; ngày mới chỉ cập nhật một phần. | 1) Seed history nhiều ngày; 2) so daily coverage. | Daily counts đúng ngày/known plan; ngày mới không thừa hưởng100% ngày trước giả. |
| TC-HIST-010 | P0 · S · SRC | History/API cũ còn tồn tại dù tài liệu/UI mâu thuẫn. | 1) Inventory routes; 2) test ACL/data policy. | Không bỏ coverage vì UI ẩn; quyết định giữ/gỡ ghi rõ; route legacy không rò dữ liệu. |
| TC-HIST-011 | P1 · B · SRC | Coverage scenarios0/1/5000/5001 và duplicate caseKey. | 1) POST plan biên/duplicate; 2) so logical coverage. | Giới hạn5000 enforced; không inflate covered do duplicate; missing/unknown semantics rõ. |

### 7.19. Maker Update tăng dần (MKR)

**Phụ trách:** Backend + RPA + Product + QA. **Tác động:** Nội vi và dữ liệu tổng hợp VAHAN ngoại vi. **Nguồn:** `app/repositories/maker_updates.py; app/api/maker_updates.py; Job.updateKind`.

| ID | Ưu tiên / loại / căn cứ | Tình huống và tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
| --- | --- | --- | --- | --- |
| TC-MKR-001 | P0 · F · SRC | GLOBAL lần đầu; tất cả State độc lập xác nhận. | 1) Nạp summary; 2) đọc run/tasks/baseline. | Baseline/vector tháng đúng; lần đầu không được mặc định là toàn RTO đã crawl. |
| TC-MKR-002 | P0 · N · SRC | GLOBAL ít State, có RTO/Maker, sai axes/năm. | 1) Tạo update jobs invalid. | Reject trước assignment; ngưỡng ≥30 State không được dùng làm chứng minh coverage đầy đủ. |
| TC-MKR-003 | P0 · F · SRC | GLOBAL mới y hệt baseline. | 1) Nạp snapshot cùng values; 2) so task targets. | Không tạo refresh không cần thiết; baseline/time/run ghi đúng, không fake completed tasks. |
| TC-MKR-004 | P0 · F · SRC | Maker mới/mất/đổi tên, OTHERS hoặc tháng thay nhưng tổng bằng nhau. | 1) Nạp từng delta vector. | Không chỉ so grand total; changed Makers đúng; name identity/delta truy vết. |
| TC-MKR-005 | P0 · N · SRC | Summary partial/duplicate/sai total/sai year. | 1) Import từng fixture. | MAKER_UPDATE_PARSE_FAILED; rollback baseline; không coi file thiếu là Maker đã mất. |
| TC-MKR-006 | P0 · F · SRC | DISCOVER có RTO mới và RTO từng tồn tại. | 1) Nạp summary từng State/Maker. | Targets bao gồm office mới/cũ cần refresh; không bỏ RTO bị giảm/mất dữ liệu. |
| TC-MKR-007 | P0 · F · SRC | REFRESH một State/RTO/Maker. | 1) Nạp workbook đúng; 2) so main/provenance. | Chỉ phạm vi được phép thay; task completed cùng transaction; dataset khác nguyên vẹn. |
| TC-MKR-008 | P0 · N · SRC | REFRESH sai scope/task/run/owner hoặc task đang chạy/completed. | 1) Đổi metadata rồi upload. | Deny/conflict; không thay dữ liệu ngoài task được phê duyệt. |
| TC-MKR-009 | P0 · F · SRC | REFRESH xác nhận no-data hoặc nhiều ô giảm/blank. | 1) Áp dụng delta fixture; 2) đọc main/index/history. | Xóa/cập nhật đúng scope theo policy; không xóa toàn dataset; no-data cần evidence. |
| TC-MKR-010 | P0 · R · SRC | Run unfinished, task fail, restart hoặc duplicate assignment. | 1) Retry/resume cùng run; 2) GLOBAL cạnh tranh. | Không mở run trùng scope; task lineage đúng; baseline chưa đủ không báo completed. |
| TC-MKR-011 | P1 · F · SRC | API GET history/detail cho year/run và ACL. | 1) List/read existing/missing/invalid run. | Đúng changedMakers/states/tasks/locations; không leak tenant/owner khác quyền. |
| TC-MKR-012 | P0 · F · GAP | Bộ điều phối end-to-end GLOBAL→DISCOVER→REFRESH. | 1) Trigger update; 2) inject delta/lỗi; 3) so full-scan oracle. | Tự hoàn tất/tiếp tục theo policy, độ bao phủ và chênh lệch 0; thiếu orchestrator/UI ghi GAP. |
| TC-MKR-013 | P0 · N · SRC | GLOBAL trả NO_RECORD; DISCOVER/REFRESH trả no-data xác nhận. | 1) Submit từng updateKind; 2) so baseline/task/main. | GLOBAL bị chặn không xóa baseline; discovery/refresh chỉ xử lý đúng scope và task được phép. |

### 7.20. Contract HTTP áp dụng cho toàn bộ endpoint (API)

**Phụ trách:** QA + Backend + AppSec. **Tác động:** Nội vi và client/proxy ngoại vi. **Nguồn:** `app/api/*.py; app/main.py; services/api-client.ts; phụ lục A-API`.

| ID | Ưu tiên / loại / căn cứ | Tình huống và tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
| --- | --- | --- | --- | --- |
| TC-API-001 | P0 · F · SRC | Mỗi operation trong A-API; fixture request hợp lệ độc lập. | 1) Gửi happy path; 2) đối soát schema/side effect. | Status/content-type/body/persist đúng contract; không chỉ assert HTTP200. |
| TC-API-002 | P0 · S · SRC | Mọi operation và principal trong M-API-ROLE. | 1) Chạy anonymous/admin/member/worker/disabled/revoked. | Allow/deny thống nhất REST/socket/UI; không mutation hoặc metadata leak khi deny. |
| TC-API-003 | P1 · B · SRC | Mọi path/query/body/header có giới hạn kiểu/length/range. | 1) Chạy lớp tương đương và min−1/min/max/max+1. | Validation đúng field; 422/400 hợp lý; không coercion bool thành worker count. |
| TC-API-004 | P1 · N · SRC | Malformed JSON/multipart, wrong MIME, missing fields, extra fields. | 1) Gửi biến thể mỗi schema applicable. | Reject strict model; extras cho phép không được runner Apply khi unmapped; lỗi bounded. |
| TC-API-005 | P1 · N · SRC | Sai method, trailing slash, case URL, query lặp. | 1) Gửi GET/POST/PUT/PATCH/DELETE/OPTIONS variants. | Không biến route khác thành mutation; 404/405/redirect đúng; duplicate params không bypass validation. |
| TC-API-006 | P0 · C · SRC | Mọi mutation replay/double-click/parallel và mất phản hồi. | 1) Replay request sau từng persist boundary. | Idempotent nơi contract quy định; nơi khác conflict rõ; không tự replay write chưa biết commit. |
| TC-API-007 | P1 · N · SRC | Endpoint gặp DB/network/processor pressure. | 1) Inject503/timeout/429; 2) client retry policy. | Error envelope/Retry-After/CORS đúng; không trả HTML giả JSON hoặc success giả. |
| TC-API-008 | P1 · S · SRC | Origin allowlist, cookie CSRF và bearer/worker token trên mọi route. | 1) Chạy ma trận auth transport hợp lệ/sai. | Trust boundary nhất quán; endpoint alias/legacy không bypass security. |
| TC-API-009 | P1 · F · SRC | Pagination/filter/sort trên list endpoints. | 1) Seed >2pages; 2) cập nhật khi đọc; 3) so count/order. | Không full-payload mặc định; limit hợp lệ; document snapshot/cursor behavior rõ. |
| TC-API-010 | P1 · S · SRC | Health/docs/schema/root và internal documents routes. | 1) Probe anon ở dev/production/ngress. | Chỉ public endpoints theo policy; production docs off; internal routes không bị expose qua proxy. |

### 7.21. Socket.IO, realtime và reconnect (SOCK)

**Phụ trách:** Backend + Frontend + RPA + QA. **Tác động:** Nội vi và transport ngoại vi. **Nguồn:** `realtime/server.py; ui_events.py; runner_events.py; socket-client.ts; phụ lục A-SOCKET`.

| ID | Ưu tiên / loại / căn cứ | Tình huống và tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
| --- | --- | --- | --- | --- |
| TC-SOCK-001 | P0 · S · SRC | 17 input events; credential đúng/sai theo namespace. | 1) Connect rồi phát từng event A-SOCKET. | Authenticate ở connect và event; invalid payload không crash; không room/resource ngoài quyền. |
| TC-SOCK-002 | P0 · F · SRC | Worker token riêng và engine=playwright. | 1) Register/heartbeat; 2) gửi status/filters evidence. | Identity ràng buộc socket/job; không giả legacy source hoặc worker ID khác. |
| TC-SOCK-003 | P0 · C · SRC | Worker cùng ID reconnect; socket cũ disconnect/heartbeat trễ. | 1) Connect B thay A; 2) phát event từ A. | Chỉ socket hiện hành thay registry/job; stale disconnect không hạ worker mới. |
| TC-SOCK-004 | P0 · S · SRC | Admin subscribe job/report room; member subscribe. | 1) Join bằng authorized/unauthorized principal. | Chỉ admin feed theo policy; member dùng read/poll; không ảnh/cookie/secret trong broadcast. |
| TC-SOCK-005 | P1 · F · SRC | reports:updated sau SQL commit và UI đang mở filter. | 1) Commit; 2) đo UI refresh/reconcile. | Notify đúng dữ liệu đã commit; không chạy premature update hoặc mất count. |
| TC-SOCK-006 | P1 · R · SRC | Disconnect/reconnect, duplicate/out-of-order events. | 1) Đảo event/status; 2) refresh snapshot. | UI/state về SQL hiện hành; không hồi terminal, tăng counter hoặc render dữ liệu cũ. |
| TC-SOCK-007 | P0 · S · SRC | Session expire/revoke/disable khi socket còn sống. | 1) Revoke; 2) thử nhận/phát event. | Socket disconnect hoặc deny ngay theo bounded deadline; không tiếp tục data feed. |
| TC-SOCK-008 | P1 · N · SRC | Payload socket >2MiB, schema sai, event lạ. | 1) Gửi fixtures biên và unsupported events. | Bounded reject/close; không OOM; logger không in toàn payload bí mật. |
| TC-SOCK-009 | P1 · N · SRC | ACK timeout, mất ACK và ACK malformed. | 1) Với options/assignment/captcha/filters; 2) reconcile. | Không giả success; timeout có chẩn đoán; không retry side effect Apply tự động. |
| TC-SOCK-010 | P1 · S · SRC | Origin sai và transport polling/WebSocket trực tiếp/proxy. | 1) Kết nối từng tổ hợp. | Origin allowlist consistent; runner hợp lệ không Origin vẫn theo worker auth riêng. |
| TC-SOCK-011 | P1 · R · SRC | API restart, browser sleep/wake, tab hidden. | 1) Gián đoạn rồi resume transport. | Không tạo nhiều subscriptions/socket; snapshot khôi phục đúng; idle session không được heartbeat gia hạn. |
| TC-SOCK-012 | P0 · N · SRC | DB auth lookup fail khi socket đã xác thực. | 1) Ngắt DB test; 2) phát/nhận event. | Fail closed; không giữ feed quyền cũ khi không xác minh session được. |

### 7.22. Mạng, VAHAN và lỗi phụ thuộc ngoài (NET)

**Phụ trách:** QA + RPA + DevOps. **Tác động:** Ngoại vi và recovery nội vi. **Nguồn:** `network_guard.py; NetworkNotice.tsx; runner.mjs; docker/nginx.conf`.

| ID | Ưu tiên / loại / căn cứ | Tình huống và tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
| --- | --- | --- | --- | --- |
| TC-NET-001 | P1 · N · SRC | DNS failure, TCP reset, connect timeout tới VAHAN. | 1) Proxy fixture từng lỗi; 2) đọc network status. | Phân loại NETWORK_PAUSED; không NO_DATA; timestamp/lý do rõ. |
| TC-NET-002 | P0 · R · SRC | Mất mạng giữa download/upload/commit. | 1) Cắt từng boundary; 2) phục hồi. | Không mất dữ liệu đã commit hoặc áp dụng lại mù; pending/retry lineage đúng. |
| TC-NET-003 | P1 · R · SRC | Một probe success rồi fail; hai success liên tiếp. | 1) Điều khiển sequence monitor 5s. | Không resume khi chưa đủ recovery; hai success xác nhận online; không flapping run liên tục. |
| TC-NET-004 | P0 · R · SRC | User Keep paused trong lúc network tự recovery. | 1) Auto-pause; 2) user pause; 3) mạng về. | Không tự resume phiên người dùng giữ pause; epoch/manual intent thắng. |
| TC-NET-005 | P1 · N · SRC | VAHAN HTTP401/403/unsupported HEAD so với HTTP5xx. | 1) Trả từng status qua probe và page. | Reachability khác validation/auth failure; không gộp mọi4xx thành mất mạng hoặc no-data. |
| TC-NET-006 | P1 · R · SRC | API reachable nhưng portal down; portal reachable nhưng API down. | 1) Tách hai links; 2) chạy job fixture. | UI/runner báo đúng dependency; không báo toàn hệ thống healthy từ một health check. |
| TC-NET-007 | P1 · N · CFG | TLS cert hết hạn/sai hostname/CA, proxy chặn TLS. | 1) Dùng endpoint staging lỗi cert. | Không disable TLS verification; lỗi hữu hạn/truy vết; không gửi credential sang endpoint khác. |
| TC-NET-008 | P1 · B · CFG | Latency/jitter/loss/bandwidth thấp và rate limit portal. | 1) Inject profile mạng D-FAULT; 2) phục hồi. | Timeout/retry hữu hạn; không giả dữ liệu đủ; lưu được job đang commit trước lỗi. |
| TC-NET-009 | P1 · N · CFG | Redirect portal sang domain khác hoặc maintenance page200. | 1) Fixture redirect/content không phải report. | Không import trang HTML giả Excel; không gửi credential tùy ý; operator thấy lỗi đúng. |
| TC-NET-010 | P1 · R · SRC | Ngắt mạng chỉ một worker trong pool. | 1) Isolate worker; 2) giữ workers khác online. | Case worker lỗi được recovery; không hủy dữ liệu workers khỏe không cần thiết. |
| TC-NET-011 | P1 · N · CFG | Browser adblock/privacy mode/DNS filter chặn font/socket/download. | 1) Mở UI với cấu hình client tương ứng. | Core UI vẫn đọc được; lỗi kết nối/download rõ; không logout hoặc reset state nhầm. |
| TC-NET-012 | P0 · R · SRC | Thay DOM/options/dataset trong lúc queue chạy. | 1) Change portal fixture giữa hai cases. | Phát hiện drift/context; ngừng work sai; giữ kết quả trước thay đổi và có hướng recovery. |

### 7.23. SQL, backpressure và lưu state (DB)

**Phụ trách:** DBA + Backend + QA. **Tác động:** Nội vi và storage/resource ngoại vi. **Nguồn:** `app/db/__init__.py; app/db/pressure.py; postgres.py; state_codec.py; report_sessions.py`.

| ID | Ưu tiên / loại / căn cứ | Tình huống và tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
| --- | --- | --- | --- | --- |
| TC-DB-001 | P0 · F · SRC | User state nhiều tài khoản và shared main reports. | 1) Save/restore state A/B; 2) đối chiếu scope. | State riêng đúng principal; main shared theo deployment policy; không trộn cấu hình cá nhân. |
| TC-DB-002 | P1 · N · SRC | State codec dữ liệu cũ/new/compressed/hỏng/oversize. | 1) Decode/PUT từng biến thể. | Không mất schema/Unicode; reject corruption rõ; không zip/memory abuse. |
| TC-DB-003 | P0 · R · SRC | Pool10+overflow 5 cạn; timeout 5s. | 1) Giữ connections test; 2) gọi list/mutation. | 503 DATABASE_BUSY/Retry-After; bounded wait; không tự replay write. |
| TC-DB-004 | P1 · N · SRC | Statement 60s/lock 5s/idle transaction 30s timeout. | 1) Giữ query/lock/transaction có kiểm soát. | Rollback/release; mã pressure đúng; không treo worker/API vô thời hạn. |
| TC-DB-005 | P0 · C · SRC | Deadlock/serialization failure/connection invalidated. | 1) Inject SQLSTATE thuộc L-DB; 2) retry rõ ràng. | 503 recoverable; không commit partial hoặc tự nhân side effect. |
| TC-DB-006 | P0 · R · SRC | DB restart/crash tại transaction main/queue/auth. | 1) Kill test DB tại barriers; 2) recover. | ACID giữ; dữ liệu/session/attempt không lệch; no healthy giả. |
| TC-DB-007 | P1 · P · SRC | Bulk concurrency 2, acquire2s; 10 workers import khác RTO. | 1) Saturate bulk slots và query nhỏ. | Heavy work bounded; lightweight requests vẫn đáp ứng SLO; slot release mọi exception. |
| TC-DB-008 | P1 · P · SRC | Report sessions/job detail trên history lớn. | 1) Seed D-LOAD; 2) EXPLAIN và đo query/memory. | Pagination/count đúng; không tải historical payload/artifact toàn bộ chỉ để summary. |
| TC-DB-009 | P0 · S · SRC | Runtime DML role, migrator, backup và audit permissions. | 1) Test GRANT/REVOKE bằng từng role. | Runtime không DDL/admin/audit update-delete; backup read-only; secrets không xuất logs. |
| TC-DB-010 | P0 · C · SRC | Hai office overlap và nhiều office độc lập. | 1) Commit song song; 2) compare independent oracle. | Không lost update; lock order hạn chế deadlock; unrelated offices không serialize toàn hệ thống. |
| TC-DB-011 | P1 · R · SRC | Filesystem/WAL volume đầy hoặc storage read-only. | 1) Gây lỗi trên DB clone; 2) phục hồi. | Không partial write; alert/lỗi rõ; không tự xóa dữ liệu để cứu dung lượng. |
| TC-DB-012 | P1 · F · SRC | Source observed_at/saved_at và host timezone/NTP khác. | 1) Nhập t0/t1; 2) hiển thị/export. | TIMESTAMPTZ đúng UTC; UI UTC+7; không tự suy ngày từ tháng/năm filter. |
| TC-DB-013 | P1 · F · SRC | GET /database/status khi DB bình thường/pressure; admin/member. | 1) Gọi endpoint; 2) so pool/connection stats. | Metrics đúng thời điểm và quyền; không lộ connection string/query parameters; metrics failure không fake healthy. |

### 7.24. An toàn ứng dụng, secrets và hardening (SEC)

**Phụ trách:** AppSec + DevOps + QA. **Tác động:** Nội vi và tác nhân không tin cậy ngoại vi. **Nguồn:** `docker/nginx.conf; compose.yaml; security.py; Dockerfiles`.

| ID | Ưu tiên / loại / căn cứ | Tình huống và tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
| --- | --- | --- | --- | --- |
| TC-SEC-001 | P0 · S · SRC | XSS/reflected/stored ở Maker/profile/user/error/filename. | 1) Fixture benign markup/script; 2) render/copy/export. | Không chạy script; encode theo output context; không rò cookie/session. |
| TC-SEC-002 | P0 · S · SRC | SQL injection/path traversal/header injection trên filters/IDs/download. | 1) Gửi strings kiểm thử an toàn; 2) so DB/log. | Query tham số hóa, path/header an toàn; không đọc/tác động ngoài scope. |
| TC-SEC-003 | P0 · S · CFG | SSRF/egress qua URL/state/upload/page redirects. | 1) Fixture trỏ domain test/metadata giả. | Không truy cập endpoint nội bộ/metadata không được cấp; egress policy xác minh ở network thực tế. |
| TC-SEC-004 | P1 · S · SRC | CSP/frame/nosniff/referrer/permissions trên200/4xx/5xx. | 1) Đọc response Nginx/API; 2) thử frame. | Headers đúng cả lỗi; không clickjacking; font/connect chính đáng không phá app. |
| TC-SEC-005 | P0 · S · CFG | HTTPS ingress, cert rotation, HTTP redirect và bypass API port. | 1) Test domain approved; 2) probe direct routes. | Không auth qua plaintext ngoài trust boundary; Secure cookie/HSTS ở ingress đúng policy. |
| TC-SEC-006 | P0 · S · SRC | Secret scan repo/image/log/build/artifact/backup metadata. | 1) Scan fixture và manifest; 2) review findings. | Không embedded production keys; false positives được triage; không đưa password vào bằng chứng. |
| TC-SEC-007 | P0 · S · SRC | Rotate runner/signing/Fernet/MFA keys. | 1) Rotate test keys; 2) replay old credentials/data. | Credential cũ revoke; ciphertext cũ theo kế hoạch reencrypt/restore; không mất dữ liệu do đổi key mù. |
| TC-SEC-008 | P0 · S · SRC | Containers non-root/read-only/cap_drop/seccomp/no-new-privileges. | 1) Inspect runtime; 2) thử writes/escalation có kiểm soát. | Chỉ tmpfs cần thiết ghi được; không Docker socket/privileged/host mounts trái policy. |
| TC-SEC-009 | P1 · S · SRC | CPU/RAM/PID/log limits và disk growth. | 1) Tạo tải có giới hạn; 2) inspect caps/rotation. | Caps thật áp dụng; không ảnh hưởng host/người dùng khác; log retention không tăng vô hạn. |
| TC-SEC-010 | P0 · S · CFG | Insider admin đổi quyền/export/xóa history trái quy trình. | 1) Diễn tập thay đổi đã duyệt; 2) kiểm tra audit. | Không vượt trust boundary; nhạy cảm truy vết/phê duyệt theo enterprise policy. |
| TC-SEC-011 | P1 · S · CFG | Dependency/OS image/SBOM/signature/release digest. | 1) Scan source/lockfiles/images; 2) verify artifact. | Findings reachable triage; critical/high unresolved theo gate; đúng digest đã test mới deploy. |
| TC-SEC-012 | P1 · S · CFG | Credential/phishing/session theft trong thiết bị bị mất. | 1) Diễn tập revoke/offboard; 2) replay session test. | MFA/revoke giảm phạm vi; incident evidence đủ; không tự coi MFA chữa được mọi session theft. |

### 7.25. Migration, backup, restore và disaster recovery (OPS)

**Phụ trách:** DBA + DevOps + QA. **Tác động:** Nội vi và hạ tầng ngoại vi. **Nguồn:** `migrations/versions/*; initialize_database.py; import_legacy.py; scripts/backup-docker.py; deployment.md`.

| ID | Ưu tiên / loại / căn cứ | Tình huống và tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
| --- | --- | --- | --- | --- |
| TC-OPS-001 | P0 · F · SRC | DB sạch và DB ở mọi supported migration predecessor. | 1) Upgrade; 2) so schema/data/checksums. | Một Alembic head hợp lệ; merge branches đầy đủ; không mất main data/history. |
| TC-OPS-002 | P0 · R · SRC | Migration fail giữa bước; chạy lại. | 1) Inject lỗi test; 2) retry migration. | Atomic hoặc resumable có bằng chứng; không schema nửa mới phục vụ API. |
| TC-OPS-003 | P0 · S · SRC | Sai DB name/tenant/role trong initializer. | 1) Chạy lên DB clone sai identity. | Fail closed; không ALTER/grant nhầm production DB; lỗi không in password SQL. |
| TC-OPS-004 | P0 · F · SRC | Legacy import dry-run/import/reimport cùng path+SHA. | 1) Nhập snapshot; 2) chạy lại. | Nguồn nguyên vẹn; ledger dedup; giữ failed/cancelled jobs và metadata cần thiết. |
| TC-OPS-005 | P0 · N · SRC | Legacy file hỏng/đổi nội dung/thiếu session/đang copy. | 1) Nhập các fixtures; 2) đối chiếu versions. | Không ghi partial/duplicate; file mới phiên bản đúng; lỗi được báo và retry được. |
| TC-OPS-006 | P0 · F · SRC | Backup khi scheduled batch/SQL commits hoạt động. | 1) pg_dump snapshot test; 2) restore clone. | Consistent dump; DB và key/browser state theo manifest; không giả backup thành công khi command fail. |
| TC-OPS-007 | P0 · S · GAP | Backup role tối thiểu, encrypted/offsite/immutable. | 1) Kiểm tra script/quyền/archive; 2) restore thử. | Read-only backup role; mã hóa/key tách quản lý; thiếu control ghi GAP, quyền600 không thay encryption. |
| TC-OPS-008 | P0 · R · CFG | Restore DB+Fernet/MFA keys lên host mới. | 1) Restore môi trường riêng; 2) read/login/browser state. | Checksum/row counts/tenant đúng; ciphertext giải được; session/job recovery theo policy. |
| TC-OPS-009 | P0 · R · CFG | Restore cũ: lịch quá hạn, job active. | 1) Khởi động clone từ backup tại thời điểm đó. | Không tự Apply/replay writes từ snapshot không rõ; checkpoint/revoke/reconcile rõ. |
| TC-OPS-010 | P0 · O · CFG | Host power loss/OS reboot/Docker restart/OOM. | 1) Gây fault staging tại điểm F-FAULT; 2) recover. | Đạt RPO/RTO đã duyệt; không duplicate/lost committed result; timeline evidence đủ. |
| TC-OPS-011 | P1 · O · SRC | Launch/stop/restart scripts và Web-only deployment. | 1) Test active-job safeguards; 2) update đúng service. | Không recreate API/DB/runner ngoài scope; không down-v; preserves volume/secrets. |
| TC-OPS-012 | P1 · R · CFG | Rollback release sau schema thay đổi. | 1) Deploy new trên clone; 2) rollback theo runbook. | Compatibility/migration policy rõ; không downgrade mất dữ liệu hoặc dùng keys/cookie không tương thích. |
| TC-OPS-013 | P1 · O · CFG | Backup quá hạn/corrupt/offsite unavailable; restore drill định kỳ. | 1) Giả từng failure; 2) thử fallback. | Alert và owner; kiểm tra checksum trước cutover; không ghi backup success giả. |
| TC-OPS-014 | P1 · O · CFG | NTP skew, license/policy VAHAN, thay đổi host/network/firewall. | 1) Diễn tập thay đổi cấu hình đã duyệt. | Login/MFA/lịch/data timestamp đúng hoặc lỗi rõ; tài liệu/runbook được cập nhật cùng release. |

### 7.26. Tải, tài nguyên và độ ổn định (PERF)

**Phụ trách:** Performance QA + DevOps + DBA. **Tác động:** Nội vi; tải khách hàng và network ngoại vi. **Nguồn:** `db/pressure.py; annual_export.py; document_worker.py; compose.yaml; các harness fixture`.

| ID | Ưu tiên / loại / căn cứ | Tình huống và tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
| --- | --- | --- | --- | --- |
| TC-PERF-001 | P1 · P · CFG | D-LOAD; 1/10/50 users, queries200/1000 rows. | 1) Warm-up; 2) steady30min; 3) đo p50/p95/p99. | Đạt SLA-API đã duyệt; errors/DB pool/query metrics đủ; không định nghĩa pass chỉ bằng average. |
| TC-PERF-002 | P1 · P · CFG | 1/5/10 workers cùng plan fixture. | 1) Benchmark cùng data/latency; 2) so correctness/rate. | Không missing/duplicate; throughput đo thực; không hứa scale tuyến tính hoặc tốc độ portal thật từ fixture. |
| TC-PERF-003 | P0 · P · SRC | 10 workers commit same/different RTO; data lớn. | 1) Stress transaction locks; 2) compare oracle. | Zero lost update/duplicate; timeout bounded; DB contention không làm lỗi thành no-data. |
| TC-PERF-004 | P1 · P · SRC | Export100k rows và upload near limits đồng thời. | 1) Saturate có kiểm soát; 2) đo RSS/CPU/PID/tmp. | Không OOM dưới tải hợp lệ; caps/headroom theo SLA; reject tải vượt có503/429 rõ. |
| TC-PERF-005 | P1 · P · SRC | Small GET/login/health khi bulk/report queries saturation. | 1) Giữ bulk slots; 2) đo critical requests. | Không starvation vô hạn; readiness phản ánh pressure phù hợp; service phục hồi khi hết tải. |
| TC-PERF-006 | P1 · P · CFG | Soak8h/24h với fixture reports/reconnects. | 1) Chạy workload lặp; 2) theo resources/trend. | Không memory/connection/process/temp/socket leak; không counter drift. |
| TC-PERF-007 | P1 · P · SRC | Burst events/polling từ50 tabs và network reconnect storm. | 1) Tăng connections trong caps; 2) cancel. | Bounded load, rate limits hiệu lực; không duplicate listeners/subscriptions hoặc session extension tự động. |
| TC-PERF-008 | P1 · P · CFG | History1m jobs và main reports100k–1m rows. | 1) Seed synthetic; 2) list/search/export phân vùng. | Query pagination/index/SLO hợp lệ; max-export vẫn enforced; không tải toàn history blob. |
| TC-PERF-009 | P1 · P · CFG | VAHAN chậm/rate-limit với throttle hợp lệ. | 1) Controlled fixture; 2) small authorized live sample. | Retry/backoff không khuếch đại tải; live sample không được dùng làm load test portal. |
| TC-PERF-010 | P1 · P · CFG | Load giảm sau spike và service capacity thay đổi. | 1) Ramp-up/down; 2) tiếp tục workload bình thường. | Resources/queue recover; không semaphore leak, backlog bị bỏ hoặc degraded state vĩnh viễn. |

### 7.27. Nghiệm thu toàn luồng và đối soát toàn dữ liệu (E2E)

**Phụ trách:** QA lead + Product + Backend + RPA + DBA. **Tác động:** Toàn bộ nội vi và ngoại vi. **Nguồn:** `Toàn bộ thành phần trong A-API/A-SOCKET và ma trận yêu cầu R-TRACE`.

| ID | Ưu tiên / loại / căn cứ | Tình huống và tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
| --- | --- | --- | --- | --- |
| TC-E2E-001 | P0 · F · SRC | Admin MFA→profile→schedule→preflight→queue→VAHAN→SQL→Excel. | 1) Chạy D-PLAN12; 2) so independent golden workbook. | Đúng mọi case/filter/cell; audit/lineage đủ; job hoàn tất chỉ sau dữ liệu durable. |
| TC-E2E-002 | P0 · R · SRC | Luồng trên có1no-data,2transient fail,1exhausted. | 1) Inject faults; 2) checkpoint/final; 3) export. | Expected counters đúng logical case; retry bounded; no-data không retry; lỗi còn truy vết. |
| TC-E2E-003 | P0 · R · SRC | Pause→giảm worker→continue→đóng UI→restart API. | 1) Chạy nhiều checkpoint; 2) recovery từng bước. | Cùng session/plan; không lost/duplicate/auto-Apply mù; active timing đúng. |
| TC-E2E-004 | P0 · C · SRC | Tất cả fault boundaries F-FAULT với same logical case. | 1) Inject từng điểm; 2) recover; 3) so SQL/UI/export. | Ràng buộc I-DATA đều đúng; outcome lỗi cũng không mất/bóp méo dữ liệu. |
| TC-E2E-005 | P0 · S · SRC | Hai deployment A/B đồng thời; admin/member/worker sai danh tính. | 1) Run/exfiltration-negative test trên cảHTTP/socket/files. | Không đọc/ghi cross-deployment; enterprise metadata riêng; same-deployment shared data đúng policy. |
| TC-E2E-006 | P0 · F · CFG | Toàn State/RTO trong profile so với baseline VAHAN độc lập. | 1) Lấy scope oracle đã duyệt; 2) chạy; 3) đối soát case/cell. | Không missing/duplicate; every case có committed/no-data/failure;100% known plan không thay full-source proof. |
| TC-E2E-007 | P0 · F · GAP | Maker incremental so với full crawl cùng source snapshot. | 1) Tạo delta giữ/đổi tổng; 2) incremental; 3) full-scan oracle. | Khác biệt dữ liệu0; phạm vi/refresh không bỏ office; chưa có orchestrator thì chưa nghiệm thu thay manual. |
| TC-E2E-008 | P0 · O · CFG | DR+release production rehearsal. | 1) Restore clone/revoke incident/deploy digest; 2) sign-off. | Đạt gates G-EXIT và RPO/RTO; evidence theo release; ngoại lệ có owner/hạn, không pass chỉ từ build. |

### 7.28. Đa nền tảng, utilities và CI/release (PLAT)

**Phụ trách:** QA + DevOps + Engineering. **Tác động:** Nội vi và OS/supply chain ngoại vi. **Nguồn:** `.github/workflows/platform.yml; scripts/setup-docker.py; Dockerfiles; test_ocr_platform.py`.

| ID | Ưu tiên / loại / căn cứ | Tình huống và tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
| --- | --- | --- | --- | --- |
| TC-PLAT-001 | P1 · O · CFG | Ubuntu, Windows/WSL2, macOS; amd64/arm64 được hỗ trợ. | 1) Build/run cùng release; 2) critical E2E. | Không hardcode đường dẫn/OS; sandbox/volumes/network đúng; data format thống nhất. |
| TC-PLAT-002 | P1 · O · SRC | Node22/Python3.12 và Playwright package/image1.63.0. | 1) Clean install; 2) build/runner launch. | Lock/image tương thích; không thiếu browser binary hoặc dependency khi deploy sạch. |
| TC-PLAT-003 | P0 · S · SRC | Setup .docker.env lần đầu/lần sau; POSIX và Windows. | 1) Generate fixture secrets; 2) chạy lại/kiểm tra permissions. | Secrets độc lập; quyền600/ACL riêng; không overwrite keys/config đã dùng hoặc in secrets. |
| TC-PLAT-004 | P1 · O · SRC | Repo path có dấu cách/Unicode; PowerShell/Bash launchers. | 1) Chạy setup/config-only/backup trên path test. | Command quoting đúng; paths relative; không shell expansion hoặc chọn sai project. |
| TC-PLAT-005 | P0 · S · SRC | Test runner DB destructive guard và artifacts. | 1) Trỏ harness vào tên DB production giả; 2) run dry setup. | Từ chối DB không disposable; evidence không chứa credential; không dùng prod .env trong CI. |
| TC-PLAT-006 | P1 · O · SRC | Tất cả harness sẵn có với fixture/schema hiện hành. | 1) Run trên environment riêng; 2) so danh mục CI với A-AUTO. | Không report test cũ pass cho feature mới; auth/schema lỗi phải sửa hoặc ghi defect, không bỏ qua âm thầm. |
| TC-PLAT-007 | P1 · O · GAP | Security/MFA/DR cases chưa nối vào CI. | 1) Thay controlled regression; 2) mở PR test. | Gate phát hiện/từ chối release; file test tồn tại không đồng nghĩa CI chạy. |
| TC-PLAT-008 | P1 · R · CFG | Upgrade libs/browser/PostgreSQL/Fernet và schema. | 1) Replay encrypted old state/golden workbooks; 2) E2E. | Compatibility dữ liệu/keys đảm bảo; performance/security regression được đánh giá. |
| TC-PLAT-009 | P2 · F · SRC | Utilities OCR tài liệu thường; ảnh rõ/mờ/Unicode; Tesseract OS paths. | 1) Chạy fixture ordinary-document theo từng utility. | Lỗi dependency/encoding rõ; không crash OS; kết quả đối chiếu golden text; không dùng để bypass challenge. |
| TC-PLAT-010 | P0 · O · CFG | Bundle live/image digest không trùng source đã test. | 1) Verify deployed assets/digest/migration; 2) smoke. | Release mismatch được phát hiện; không ký nghiệm thu chỉ bằng build source chưa deploy. |


## 8. Fault injection tại các điểm nhạy cảm F-FAULT

| Điểm | Lỗi tiêm trên staging | Oracle sau phục hồi | Test liên quan |
| --- | --- | --- | --- |
| F01 Trước persist preflight | SQL fail/worker evidence timeout | Chưa gate PASS; chưa load Maker/queue | TC-UH-002, TC-UH-014 |
| F02 Sau gate trước publish | Contract đổi/clock qua freshness | Gate cũ bị từ chối; không queue sai version | TC-UH-003, TC-UH-007 |
| F03 Sau assignment SQL trước emit | API crash/socket drop | Re-deliver same job ID; không create case lặp | TC-JOB-011, TC-QUEUE-008 |
| F04 Trong nhóm fill song song | Một request fail/request khác trả muộn | Tác vụ cũ hết trước case mới; chưa Apply sai | TC-RUN-002, TC-RUN-004, TC-RUN-007 |
| F05 Sau SUBMITTING persist trước ACK/click | ACK drop/cancel | Không click khi chưa xác minh outcome; không tự replay Apply | TC-JOB-005, TC-JOB-006, TC-JOB-008 |
| F06 Sau click trước apply-clicked/status ACK | API/network crash | Side effect chưa biết được reconcile; attempt/click ID không nhân | TC-JOB-006, TC-JOB-008, TC-RUN-008 |
| F07 Result đang loading/download | Stale marker/page crash/HTTP401 | Không NO_DATA/COMPLETE giả | TC-RUN-009, TC-RUN-010, TC-RUN-011 |
| F08 Workbook đọc được trước SQL | Parser timeout/cancel/DB fail | Không half-filter rows hoặc release worker trước commit | TC-DATA-011, TC-DATA-014, TC-FILE-006, TC-FILE-008 |
| F09 SQL commit trước HTTP reply | Drop reply/replay same checksum | Một logical commit, idempotent response | TC-DATA-009, TC-DATA-010, TC-RUN-013 |
| F10 Commit trước notify/UI refresh | Socket loss/browser closed | Data durable; polling/reload thấy kết quả | TC-REP-011, TC-SOCK-005, TC-SOCK-006 |
| F11 Checkpoint/final đang active | Pause/worker death/API restart | Same phase/window/lineage; không reset quota | TC-RETRY-001, TC-RETRY-003, TC-RETRY-006, TC-RETRY-011 |
| F12 Scheduler callback cũ | Stop/delete/resume epoch mới | Old callback không hồi state/queue | TC-SCH-014, TC-SCH-015 |
| F14 Backup/restore/cutover | Dump lỗi/key sai/host mất điện | Không switch sang DB không kiểm chứng; RPO/RTO có số đo | TC-OPS-006, TC-OPS-008, TC-OPS-010 |

Mỗi injection ghi timestamp UTC, barrier, process/job/session/case/attempt/requestID, snapshot trước/sau và cleanup. Không cố tạo “exactly once” cho browser side effect chưa biết; yêu cầu hệ thống nhận diện uncertainty, không replay mù và giữ dữ liệu idempotent ở SQL.

## 9. Ma trận truy vết R-TRACE và automation sẵn có

Các đường dẫn dưới đây là harness **tồn tại/tham chiếu trong repo**, không phải bằng chứng đã PASS phiên bản này. CI hiện chạy một tập con; MFA/pressure/DR mới cần đối chiếu và bổ sung. `verification/*` thuộc API, `scripts/test-*.mjs` thuộc web-ui, `test-*.mjs` thuộc browser-runner.

| Yêu cầu/nhóm | Case gốc | Phạm vi ID | Harness và khoảng trống |
| --- | --- | --- | --- |
| R-ENV · Khởi động, cấu hình và trust boundary | 10 | TC-ENV-001 … TC-ENV-010 | scripts/setup-docker.py; scripts/run-docker.py; test-platform.mjs |
| R-AUTH · Đăng nhập, session và logout | 14 | TC-AUTH-001 … TC-AUTH-014 | verification/test_session_limits.py; verification/test_account_passwords.py |
| R-MFA · MFA, enrollment và recovery code | 10 | TC-MFA-001 … TC-MFA-010 | Chưa thấy harness chuyên dụng cho enrollment/TOTP/recovery trong snapshot |
| R-ACL · Phân quyền, ownership và tách doanh nghiệp | 12 | TC-ACL-001 … TC-ACL-012 | verification/test_permissions.py; scripts/test-permissions-ui.mjs |
| R-ACCT · Account settings và quản lý user | 12 | TC-ACCT-001 … TC-ACCT-012 | scripts/test-account-settings-ui.mjs; verification/test_account_passwords.py |
| R-UI · Điều hướng, responsive và khả năng sử dụng | 11 | TC-UI-001 … TC-UI-011 | scripts/test-navigation-ui.mjs; scripts/test-platform.mjs |
| R-PROF · Filter profile, options và lập kế hoạch | 14 | TC-PROF-001 … TC-PROF-014 | verification/test_filter_profiles.py; scripts/test-filter-profiles-ui.mjs; test-profile-options.mjs |
| R-UH · UI Health, SQL contract và fail-closed preflight | 14 | TC-UH-001 … TC-UH-014 | verification/test_ui_contract.py; scripts/test-health-page-ui.mjs; test-ui-health-contract.mjs |
| R-SCH · Lịch Once/Daily/Monthly và điều khiển phiên | 18 | TC-SCH-001 … TC-SCH-018 | verification/test_run_schedules.py; scripts/test-run-schedules-ui.mjs; scripts/test-schedule-timing.mjs |
| R-JOB · Job lifecycle, ACK và state machine | 12 | TC-JOB-001 … TC-JOB-012 | verification/test_run_controls.py; test-job-lifecycle.mjs |
| R-QUEUE · Hàng đợi SQL, capacity và concurrency | 12 | TC-QUEUE-001 … TC-QUEUE-012 | verification/test_shared_batch_queue.py; verification/test_worker_pool.py |
| R-RETRY · Retry checkpoint và phục hồi cuối | 11 | TC-RETRY-001 … TC-RETRY-011 | verification/test_queue_retry_checkpoints.py; verification/test_retry_sessions.py |
| R-RUN · Browser runner và tương tác VAHAN | 14 | TC-RUN-001 … TC-RUN-014 | test-filter-fill.mjs; test-options.mjs; test-navigation.mjs; test-page-recovery.mjs; test-main-report-save.mjs |
| R-CAP · Validation challenge và dữ liệu nhạy cảm | 8 | TC-CAP-001 … TC-CAP-008 | verification/test_captcha_ephemeral.py; verification/test_captcha_refresh_race.py; test-image-pipe.mjs |
| R-DATA · Workbook ingestion và toàn vẹn dữ liệu | 17 | TC-DATA-001 … TC-DATA-017 | verification/test_annual_reports.py; verification/test_report_results.py; verification/test_main_live_workbook.py |
| R-FILE · Upload, parser và document service | 12 | TC-FILE-001 … TC-FILE-012 | tests/test_excel.py (cần đối chiếu legacy contract); chưa thấy timeout/resource-isolation harness đầy đủ |
| R-REP · Bảng chính, tìm kiếm và Excel export | 14 | TC-REP-001 … TC-REP-014 | scripts/test-annual-reports.mjs; verification/test_annual_reports.py |
| R-HIST · Sessions, update history và coverage | 11 | TC-HIST-001 … TC-HIST-011 | scripts/test-session-ui.mjs; scripts/test-update-history-ui.mjs; verification/test_report_coverage.py; verification/test_update_status.py |
| R-MKR · Maker Update tăng dần | 13 | TC-MKR-001 … TC-MKR-013 | Chưa thấy harness độc lập đủ GLOBAL/DISCOVER/REFRESH/orchestrator |
| R-API · Contract HTTP áp dụng cho toàn bộ endpoint | 10 | TC-API-001 … TC-API-010 | tests/test_api.py; verification suites; cần parameterized tất cả operations + auth mới |
| R-SOCK · Socket.IO, realtime và reconnect | 12 | TC-SOCK-001 … TC-SOCK-012 | tests/test_socketio_flow.py; tests/test_repositories.py; cần so schema/auth/cookie mới |
| R-NET · Mạng, VAHAN và lỗi phụ thuộc ngoài | 12 | TC-NET-001 … TC-NET-012 | scripts/test-network-ui.mjs; test-page-recovery.mjs; chưa thấy fault-proxy end-to-end đầy đủ |
| R-DB · SQL, backpressure và lưu state | 13 | TC-DB-001 … TC-DB-013 | tests/test_repositories.py; DB integration suites; cần thêm pressure/least-privilege/restore coverage |
| R-SEC · An toàn ứng dụng, secrets và hardening | 12 | TC-SEC-001 … TC-SEC-012 | scripts/security-audit.py (đọc trạng thái, không thay thế pentest); verification/test_permissions.py |
| R-OPS · Migration, backup, restore và disaster recovery | 14 | TC-OPS-001 … TC-OPS-014 | verification/test_main_migration.py; verification/test_shared_migration.py; cần restore/fault rehearsal riêng |
| R-PERF · Tải, tài nguyên và độ ổn định | 10 | TC-PERF-001 … TC-PERF-010 | verification/test_shared_batch_queue.py kiểm tra concurrency; chưa thay thế workload/soak/metrics đầy đủ |
| R-E2E · Nghiệm thu toàn luồng và đối soát toàn dữ liệu | 8 | TC-E2E-001 … TC-E2E-008 | Harness thành phần sẵn có; chưa có bằng chứng current-turn nghiệm thu full portal/DR |
| R-PLAT · Đa nền tảng, utilities và CI/release | 10 | TC-PLAT-001 … TC-PLAT-010 | .github/workflows/platform.yml; scripts/test-platform.mjs; verification/test_ocr_platform.py |

## 10. Phụ lục A-API — từng operation phải có run instances

Có **84 operations** từ decorator source ở snapshot này. Mỗi dòng áp dụng TC-API-001…010 theo tính thích hợp cùng nhóm nghiệp vụ; route alias/deprecated vẫn phải kiểm thử ACL/input/state. Không lấy con số 81 ở API document cũ làm inventory mới.

| API ID | Method | Path | Nhóm nghiệp vụ | Model/handler nguồn |
| --- | --- | --- | --- | --- |
| HTTP-001 | GET | `/api/annual-reports` | REP, DATA; API, ACL | `api/annual_reports.py::annual_reports` |
| HTTP-002 | POST | `/api/annual-reports/coverage` | HIST, REP; API, ACL | `api/report_coverage.py::report_coverage` |
| HTTP-003 | GET | `/api/annual-reports/export` | REP, DATA; API, ACL | `api/annual_reports.py::export_annual_reports` |
| HTTP-004 | GET | `/api/annual-reports/history` | REP, DATA; API, ACL | `api/annual_reports.py::annual_history` |
| HTTP-005 | GET | `/api/annual-reports/update-status` | HIST; API, ACL | `api/update_status.py::update_status` |
| HTTP-006 | GET | `/api/audit` | ACL, ACCT, FILE, DB; API, ACL | `api/data.py::audit_history` |
| HTTP-007 | POST | `/api/auth/activity` | AUTH, MFA, ACCT; API, ACL | `api/auth.py::session_activity` |
| HTTP-008 | POST | `/api/auth/login` | AUTH, MFA, ACCT; API, ACL | `api/auth.py::login` |
| HTTP-009 | POST | `/api/auth/logout` | AUTH, MFA, ACCT; API, ACL | `api/auth.py::logout` |
| HTTP-010 | GET | `/api/auth/me` | AUTH, MFA, ACCT; API, ACL | `api/auth.py::current_user` |
| HTTP-011 | POST | `/api/auth/mfa/confirm` | AUTH, MFA, ACCT; API, ACL | `api/auth.py::mfa_confirm` |
| HTTP-012 | POST | `/api/auth/mfa/enroll` | AUTH, MFA, ACCT; API, ACL | `api/auth.py::mfa_enroll` |
| HTTP-013 | POST | `/api/auth/password` | AUTH, MFA, ACCT; API, ACL | `api/auth.py::change_password` |
| HTTP-014 | GET | `/api/auth/status` | AUTH, MFA, ACCT; API, ACL | `api/auth.py::auth_status` |
| HTTP-015 | POST | `/api/batch-queue/sessions` | QUEUE, RETRY, JOB; API, ACL | `api/batch_queue.py::start_queue` |
| HTTP-016 | GET | `/api/batch-queue/sessions/{session_id}` | QUEUE, RETRY, JOB; API, ACL | `api/batch_queue.py::get_queue` |
| HTTP-017 | POST | `/api/batch-queue/sessions/{session_id}/claim` | QUEUE, RETRY, JOB; API, ACL | `api/batch_queue.py::claim_task` |
| HTTP-018 | POST | `/api/batch-queue/sessions/{session_id}/pause` | QUEUE, RETRY, JOB; API, ACL | `api/batch_queue.py::pause_queue` |
| HTTP-019 | POST | `/api/batch-queue/sessions/{session_id}/resume` | QUEUE, RETRY, JOB; API, ACL | `api/batch_queue.py::resume_queue` |
| HTTP-020 | POST | `/api/batch-queue/sessions/{session_id}/tasks/{position}/settle` | QUEUE, RETRY, JOB; API, ACL | `api/batch_queue.py::settle_task` |
| HTTP-021 | GET | `/api/database/status` | ENV, DB, NET; API, ACL | `api/health.py::database_status` |
| HTTP-022 | GET | `/api/files` | ACL, ACCT, FILE, DB; API, ACL | `api/data.py::files` |
| HTTP-023 | POST | `/api/files` | ACL, ACCT, FILE, DB; API, ACL | `api/data.py::upload` |
| HTTP-024 | GET | `/api/files/{file_id}/download` | ACL, ACCT, FILE, DB; API, ACL | `api/data.py::download` |
| HTTP-025 | GET | `/api/files/{file_id}/rows` | ACL, ACCT, FILE, DB; API, ACL | `api/data.py::rows` |
| HTTP-026 | GET | `/api/filter-profiles` | PROF, UH; API, ACL | `api/filter_profiles.py::list_profiles` |
| HTTP-027 | POST | `/api/filter-profiles` | PROF, UH; API, ACL | `api/filter_profiles.py::create_profile` |
| HTTP-028 | POST | `/api/filter-profiles/makers` | PROF, UH; API, ACL | `api/filter_profiles.py::search_makers` |
| HTTP-029 | POST | `/api/filter-profiles/options` | PROF, UH; API, ACL | `api/filter_profiles.py::load_options` |
| HTTP-030 | DELETE | `/api/filter-profiles/{profile_id}` | PROF, UH; API, ACL | `api/filter_profiles.py::delete_profile` |
| HTTP-031 | PUT | `/api/filter-profiles/{profile_id}` | PROF, UH; API, ACL | `api/filter_profiles.py::update_profile` |
| HTTP-032 | POST | `/api/filter-profiles/{profile_id}/preview` | PROF, UH; API, ACL | `api/filter_profiles.py::preview_profile` |
| HTTP-033 | GET | `/api/health` | ENV, DB, NET; API, ACL | `api/health.py::health` |
| HTTP-034 | GET | `/api/jobs` | JOB, DATA, ACL; API, ACL | `api/jobs.py::list_jobs` |
| HTTP-035 | POST | `/api/jobs` | JOB, DATA, ACL; API, ACL | `api/jobs.py::create_job` |
| HTTP-036 | GET | `/api/jobs/reports` | DATA, FILE, HIST, REP; API, ACL | `api/excel.py::list_exported_reports` |
| HTTP-037 | GET | `/api/jobs/reports/file/{file_name}` | DATA, FILE, HIST, REP; API, ACL | `api/excel.py::download_stored_report` |
| HTTP-038 | GET | `/api/jobs/reports/sessions` | DATA, FILE, HIST, REP; API, ACL | `api/excel.py::list_exported_report_sessions` |
| HTTP-039 | DELETE | `/api/jobs/reports/sessions/{session_id}` | DATA, FILE, HIST, REP; API, ACL | `api/excel.py::delete_report_session` |
| HTTP-040 | GET | `/api/jobs/reports/sessions/{session_id}` | DATA, FILE, HIST, REP; API, ACL | `api/excel.py::read_exported_report_session` |
| HTTP-041 | POST | `/api/jobs/reports/sessions/{session_id}/restore` | DATA, FILE, HIST, REP; API, ACL | `api/excel.py::restore_report_session` |
| HTTP-042 | POST | `/api/jobs/reports/verify` | DATA, FILE, HIST, REP; API, ACL | `api/excel.py::verify_exported_reports` |
| HTTP-043 | GET | `/api/jobs/{job_id}` | JOB, DATA, ACL; API, ACL | `api/jobs.py::get_job` |
| HTTP-044 | POST | `/api/jobs/{job_id}/artifacts` | ACL, ACCT, FILE, DB; API, ACL | `api/data.py::runner_artifact` |
| HTTP-045 | POST | `/api/jobs/{job_id}/cancel` | JOB, DATA, ACL; API, ACL | `api/jobs.py::cancel_job` |
| HTTP-046 | GET | `/api/jobs/{job_id}/excel` | DATA, FILE, HIST, REP; API, ACL | `api/excel.py::download_excel` |
| HTTP-047 | POST | `/api/jobs/{job_id}/main-report` | DATA, FILE, HIST, REP; API, ACL | `api/excel.py::upload_excel` |
| HTTP-048 | GET | `/api/jobs/{job_id}/no-data` | DATA, FILE, HIST, REP; API, ACL | `api/excel.py::download_no_data_file` |
| HTTP-049 | GET | `/api/jobs/{job_id}/report-result` | JOB, DATA, ACL; API, ACL | `api/jobs.py::read_report_result` |
| HTTP-050 | POST | `/api/jobs/{job_id}/report-result` | JOB, DATA, ACL; API, ACL | `api/jobs.py::save_report_result` |
| HTTP-051 | POST | `/api/jobs/{job_id}/upload-excel` | DATA, FILE, HIST, REP; API, ACL | `api/excel.py::upload_excel` |
| HTTP-052 | GET | `/api/maker-updates` | MKR; API, ACL | `api/maker_updates.py::latest_update` |
| HTTP-053 | GET | `/api/maker-updates/{run_id}` | MKR; API, ACL | `api/maker_updates.py::get_update` |
| HTTP-054 | GET | `/api/network/status` | ENV, DB, NET; API, ACL | `api/health.py::network_status` |
| HTTP-055 | GET | `/api/ready` | ENV, DB, NET; API, ACL | `api/health.py::ready` |
| HTTP-056 | GET | `/api/run-schedules` | SCH, UH; API, ACL | `api/run_schedules.py::list_schedules` |
| HTTP-057 | POST | `/api/run-schedules` | SCH, UH; API, ACL | `api/run_schedules.py::create_schedule` |
| HTTP-058 | GET | `/api/run-schedules/captchas` | SCH, UH; API, ACL | `api/run_schedules.py::current_captchas` |
| HTTP-059 | DELETE | `/api/run-schedules/{schedule_id}` | SCH, UH; API, ACL | `api/run_schedules.py::delete_schedule` |
| HTTP-060 | PATCH | `/api/run-schedules/{schedule_id}` | SCH, UH; API, ACL | `api/run_schedules.py::toggle_schedule` |
| HTTP-061 | POST | `/api/run-schedules/{schedule_id}/pause` | SCH, UH; API, ACL | `api/run_schedules.py::pause_schedule` |
| HTTP-062 | POST | `/api/run-schedules/{schedule_id}/resume` | SCH, UH; API, ACL | `api/run_schedules.py::resume_schedule` |
| HTTP-063 | POST | `/api/run-schedules/{schedule_id}/stop` | SCH, UH; API, ACL | `api/run_schedules.py::stop_schedule` |
| HTTP-064 | POST | `/api/runner-logs` | ACL, ACCT, FILE, DB; API, ACL | `api/data.py::runner_log` |
| HTTP-065 | GET | `/api/runner-state/{runner_id}` | ACL, ACCT, FILE, DB; API, ACL | `api/data.py::get_browser_state` |
| HTTP-066 | PUT | `/api/runner-state/{runner_id}` | ACL, ACCT, FILE, DB; API, ACL | `api/data.py::put_browser_state` |
| HTTP-067 | GET | `/api/runners` | RUN, SOCK; API, ACL | `api/runners.py::list_runners` |
| HTTP-069 | GET | `/api/ui-health/contract` | UH; API, ACL | `api/ui_health.py::current_contract` |
| HTTP-070 | POST | `/api/ui-health/logs` | UH; API, ACL | `api/ui_health.py::receive_ui_health_log` |
| HTTP-071 | POST | `/api/ui-health/preflight` | UH; API, ACL | `api/ui_health.py::preflight` |
| HTTP-072 | GET | `/api/ui-health/reports` | UH; API, ACL | `api/ui_health.py::list_ui_health_reports` |
| HTTP-073 | GET | `/api/ui-health/reports/{file_name}/download` | UH; API, ACL | `api/ui_health.py::download_ui_health_report` |
| HTTP-074 | POST | `/api/ui-health/run-now` | UH; API, ACL | `api/ui_health.py::request_ui_health_check_now` |
| HTTP-075 | GET | `/api/ui-health/schedule` | UH; API, ACL | `api/ui_health.py::get_ui_health_schedule` |
| HTTP-076 | PUT | `/api/ui-health/schedule` | UH; API, ACL | `api/ui_health.py::update_ui_health_schedule` |
| HTTP-077 | GET | `/api/ui-health/status` | UH; API, ACL | `api/ui_health.py::contract_status` |
| HTTP-078 | GET | `/api/user-state` | ACL, ACCT, FILE, DB; API, ACL | `api/data.py::state` |
| HTTP-079 | PUT | `/api/user-state/{key}` | ACL, ACCT, FILE, DB; API, ACL | `api/data.py::put_state` |
| HTTP-080 | GET | `/api/users` | ACL, ACCT, FILE, DB; API, ACL | `api/data.py::users` |
| HTTP-081 | POST | `/api/users` | ACL, ACCT, FILE, DB; API, ACL | `api/data.py::create_user` |
| HTTP-082 | PATCH | `/api/users/{username}` | ACL, ACCT, FILE, DB; API, ACL | `api/data.py::update_user` |
| HTTP-083 | POST | `/api/users/{username}/password` | ACL, ACCT, FILE, DB; API, ACL | `api/data.py::reset_password` |
| HTTP-084 | GET | `/api/worker-pool` | QUEUE, ENV; API, ACL | `api/worker_pool.py::get_worker_pool` |
| HTTP-085 | PUT | `/api/worker-pool` | QUEUE, ENV; API, ACL | `api/worker_pool.py::set_worker_pool` |

Ngoài `/api`: kiểm tra `GET /`, `/docs`, `/redoc`, `/openapi.json` theo dev/production; Nginx static/deep-link routes; transport `/socket.io`; internal document `GET /health`, `POST /extract`, `POST /export`; worker `GET :3001/health`. Các đường internal phải bị chặn từ client/public theo M-NET.

## 11. Phụ lục A-SOCKET — hai chiều giao tiếp

| Input ID | Namespace | Event đầu vào API | Coverage |
| --- | --- | --- | --- |
| SOCK-IN-001 | /runner | `captcha:invalid` | SOCK, AUTH, ACL; thêm JOB/RUN/CAP/NET/UH theo payload |
| SOCK-IN-002 | /runner | `captcha:refreshed` | SOCK, AUTH, ACL; thêm JOB/RUN/CAP/NET/UH theo payload |
| SOCK-IN-003 | /runner | `captcha:required` | SOCK, AUTH, ACL; thêm JOB/RUN/CAP/NET/UH theo payload |
| SOCK-IN-004 | /runner | `connect` | SOCK, AUTH, ACL; thêm JOB/RUN/CAP/NET/UH theo payload |
| SOCK-IN-005 | /runner | `disconnect` | SOCK, AUTH, ACL; thêm JOB/RUN/CAP/NET/UH theo payload |
| SOCK-IN-006 | /runner | `job:apply-clicked` | SOCK, AUTH, ACL; thêm JOB/RUN/CAP/NET/UH theo payload |
| SOCK-IN-007 | /runner | `job:filters-verified` | SOCK, AUTH, ACL; thêm JOB/RUN/CAP/NET/UH theo payload |
| SOCK-IN-008 | /runner | `job:status` | SOCK, AUTH, ACL; thêm JOB/RUN/CAP/NET/UH theo payload |
| SOCK-IN-009 | /runner | `network:problem` | SOCK, AUTH, ACL; thêm JOB/RUN/CAP/NET/UH theo payload |
| SOCK-IN-010 | /runner | `runner:heartbeat` | SOCK, AUTH, ACL; thêm JOB/RUN/CAP/NET/UH theo payload |
| SOCK-IN-011 | /runner | `runner:recover` | SOCK, AUTH, ACL; thêm JOB/RUN/CAP/NET/UH theo payload |
| SOCK-IN-012 | /ui | `captcha:refresh` | SOCK, AUTH, ACL; thêm JOB/RUN/CAP/NET/UH theo payload |
| SOCK-IN-013 | /ui | `captcha:submitted` | SOCK, AUTH, ACL; thêm JOB/RUN/CAP/NET/UH theo payload |
| SOCK-IN-014 | /ui | `connect` | SOCK, AUTH, ACL; thêm JOB/RUN/CAP/NET/UH theo payload |
| SOCK-IN-015 | /ui | `disconnect` | SOCK, AUTH, ACL; thêm JOB/RUN/CAP/NET/UH theo payload |
| SOCK-IN-016 | /ui | `ui:runner-options` | SOCK, AUTH, ACL; thêm JOB/RUN/CAP/NET/UH theo payload |
| SOCK-IN-017 | /ui | `ui:subscribe-job` | SOCK, AUTH, ACL; thêm JOB/RUN/CAP/NET/UH theo payload |

Các event/command đầu ra literal phát hiện từ `sio.emit/sio.call` trong backend; tên event động và transport reconnect cũng thuộc SOCK/API matrix, không được bỏ chỉ vì không literal.

| Namespace | Event/command API phát | Cơ chế | Expected kiểm thử |
| --- | --- | --- | --- |
| /runner | `captcha:refresh` | call | Đúng target/room/ACL; payload không secret; xử lý mất/trùng/trễ ACK hoặc notification |
| /runner | `captcha:submit` | call | Đúng target/room/ACL; payload không secret; xử lý mất/trùng/trễ ACK hoặc notification |
| /runner | `job:assigned` | emit | Đúng target/room/ACL; payload không secret; xử lý mất/trùng/trễ ACK hoặc notification |
| /runner | `job:cancelled` | emit | Đúng target/room/ACL; payload không secret; xử lý mất/trùng/trễ ACK hoặc notification |
| /runner | `runner:cancel-options` | call | Đúng target/room/ACL; payload không secret; xử lý mất/trùng/trễ ACK hoặc notification |
| /runner | `runner:options` | call | Đúng target/room/ACL; payload không secret; xử lý mất/trùng/trễ ACK hoặc notification |
| /runner | `ui-health:preflight` | call | Đúng target/room/ACL; payload không secret; xử lý mất/trùng/trễ ACK hoặc notification |
| /runner | `ui-health:run-now` | emit | Đúng target/room/ACL; payload không secret; xử lý mất/trùng/trễ ACK hoặc notification |
| /runner | `ui-health:schedule-updated` | emit | Đúng target/room/ACL; payload không secret; xử lý mất/trùng/trễ ACK hoặc notification |
| /ui | `captcha:invalid` | emit | Đúng target/room/ACL; payload không secret; xử lý mất/trùng/trễ ACK hoặc notification |
| /ui | `captcha:refreshed` | emit | Đúng target/room/ACL; payload không secret; xử lý mất/trùng/trễ ACK hoặc notification |
| /ui | `captcha:required` | emit | Đúng target/room/ACL; payload không secret; xử lý mất/trùng/trễ ACK hoặc notification |
| /ui | `job:status` | emit | Đúng target/room/ACL; payload không secret; xử lý mất/trùng/trễ ACK hoặc notification |
| /ui | `network:status` | emit | Đúng target/room/ACL; payload không secret; xử lý mất/trùng/trễ ACK hoặc notification |
| /ui | `reports:updated` | emit | Đúng target/room/ACL; payload không secret; xử lý mất/trùng/trễ ACK hoặc notification |
| /ui | `runner:offline` | emit | Đúng target/room/ACL; payload không secret; xử lý mất/trùng/trễ ACK hoặc notification |
| /ui | `runner:online` | emit | Đúng target/room/ACL; payload không secret; xử lý mất/trùng/trễ ACK hoặc notification |
| /ui | `ui-health:blocked` | emit | Đúng target/room/ACL; payload không secret; xử lý mất/trùng/trễ ACK hoặc notification |
| /ui | `ui-health:log-received` | emit | Đúng target/room/ACL; payload không secret; xử lý mất/trùng/trễ ACK hoặc notification |
| /ui | `ui-health:verified` | emit | Đúng target/room/ACL; payload không secret; xử lý mất/trùng/trễ ACK hoặc notification |
| /ui | `ui-health:waiting` | emit | Đúng target/room/ACL; payload không secret; xử lý mất/trùng/trễ ACK hoặc notification |

### Ma trận job M-JOB từ source

| Trạng thái hiện tại | Cạnh hợp lệ khác self | Cạnh không liệt kê |
| --- | --- | --- |
| QUEUED | ASSIGNED, CANCELLED, FAILED | Reject/no mutation; self idempotent theo can_transition và endpoint guards |
| ASSIGNED | CANCELLED, FAILED, OPENING_VAHAN | Reject/no mutation; self idempotent theo can_transition và endpoint guards |
| OPENING_VAHAN | CANCELLED, CAPTURING_CAPTCHA, FAILED, FILLING_FILTERS | Reject/no mutation; self idempotent theo can_transition và endpoint guards |
| CAPTURING_CAPTCHA | CANCELLED, FAILED, WAITING_CAPTCHA | Reject/no mutation; self idempotent theo can_transition và endpoint guards |
| FILLING_FILTERS | CANCELLED, CAPTURING_CAPTCHA, FAILED, SUBMITTING, WAITING_CAPTCHA | Reject/no mutation; self idempotent theo can_transition và endpoint guards |
| WAITING_CAPTCHA | CANCELLED, FAILED, SUBMITTING | Reject/no mutation; self idempotent theo can_transition và endpoint guards |
| SUBMITTING | CANCELLED, FAILED, WAITING_CAPTCHA, WAITING_RESULT | Reject/no mutation; self idempotent theo can_transition và endpoint guards |
| WAITING_RESULT | CANCELLED, COMPLETED, FAILED, NO_DATA, WAITING_CAPTCHA | Reject/no mutation; self idempotent theo can_transition và endpoint guards |
| COMPLETED | Không có (terminal) | Reject/no mutation; self idempotent theo can_transition và endpoint guards |
| NO_DATA | Không có (terminal) | Reject/no mutation; self idempotent theo can_transition và endpoint guards |
| FAILED | Không có (terminal) | Reject/no mutation; self idempotent theo can_transition và endpoint guards |
| CANCELLED | Không có (terminal) | Reject/no mutation; self idempotent theo can_transition và endpoint guards |

Mọi144cặp phải được tạo thành run instances; endpoint guard bổ sung (COMPLETED cần report commit, filters evidence, worker identity) vẫn phải kiểm tra dù cạnh có trong state machine.

## 12. Protocol thực thi và mẫu ghi kết quả

### Trình tự chạy

| Đợt | Nội dung | Điều kiện qua đợt |
| --- | --- | --- |
| 0 — baseline | Khóa release/config/data/policy; inventory API/socket/schema; prepare isolated fixtures | Không secret thật; manifest và oracle review; môi trường test khác production |
| 1 — static/unit | Build/check, parser/profile/timing/codec/state/security policy fixtures | Tests hiện hành không bị skip để né regression; source và test contract thống nhất |
| 2 — integration | API/SQL/socket/queue/gates/worker trên fixture portal | Invariants I-DATA đạt; mọi API/namespace có positive và negative quyền |
| 3 — resilience/security | F-FAULT, race barriers, A/B isolation, abuse/file/Origin/MFA | Không mất/rò dữ liệu; unknown side effects được xử lý rõ; evidence độc lập |
| 4 — platform/performance | Browser/OS/architecture matrix, steady/soak/load limits | SLO đã duyệt, dữ liệu đúng sau load; resource/connection/temp phục hồi |
| 5 — UAT/DR/release | Mẫu portal được phép, full scope reconciliation, backup restore và deployed digest | Product/QA/AppSec/DBA/DevOps ký gates; có rollback/incident runbook |

**Một run không được báo full PASS vì test component pass.** Live UAT chỉ lấy mẫu đã cấp quyền/throttle; toàn bộ lỗi destructive/load vẫn trên fixture/staging. Giữ giờ UTC trong log và hiển thị UTC+7 trong biên bản.

### Mẫu bắt buộc cho mỗi run instance

| Trường | Giá trị cần điền |
| --- | --- |
| Run ID / test instance | `<release>-<runId>` / `TC-GROUP-nnn.HTTP-xxx.role.variant.env.iteration` |
| Release / source / config | Git SHA, working-tree digest nếu có, image digest, deployed bundle, migration head; flags/limits không chứa secret |
| Người thực hiện / người review | Tên, nhóm, ngày giờ, approver cho fault/load/UAT |
| Environment / data | E-INT/STAGE/etc; tenant/user/role/worker; fixture version+SHA; oracle version |
| Tiền điều kiện / bước thực tế | State ban đầu, request/event, boundary fault, thứ tự/barriers, timestamp bắt đầu/kết thúc |
| Expected / Actual | So từng assertion của case; ghi HTTP/schema/state/cell/counter/metric thực tế, không chỉ “works” |
| Kết quả | NOT RUN / PASS / FAIL / BLOCKED / N/A; blocked reason hoặc N/A approval |
| Bằng chứng | Request/response đã redact; requestID/job/session/case/attempt/preflight/sourceEventID; screenshot/trace/log/SQL checksum/export reopen/metrics |
| Defect / tác động | Bug ID, severity, scope, reproduction, data loss/exposure/availability, owner; không copy secret vào ticket |
| Cleanup / retest | Kết quả dọn environment; dữ liệu đã giữ; case/variant cần retest và related regression |

### Evidence tối thiểu theo loại

| Loại | Bằng chứng tối thiểu |
| --- | --- |
| Functional/data | UI/API response + SQL state/row count/field comparison/provenance + golden diff; Excel reopen khi applicable |
| Permission/security | Negative request/transport + DB/event không side effect + actor/tenant/signed event; không cần khai thác phá hoại để chứng minh deny |
| Concurrency/recovery | Barriers/timeline + before/after snapshots + job/case lineage + repeatability; ít nhất30 race iterations cho mutation critical |
| Performance | Workload/hardware/limits, p50/p95/p99/errors, RSS/CPU/PID/tmp/DB pool/locks, raw metrics và data diff sau run |
| DR/operations | Audit/incident timelines; dump/key/restore manifest; checksum và RPO/RTO đo được |

## 13. Gates nghiệm thu G-EXIT

| Gate | Điều kiện phải có trước khi kết luận đạt |
| --- | --- |
| G1 — coverage | 100% case P0 đã thực thi và PASS; mọi operation A-API và input A-SOCKET có run instances quyền/contract; mọi 144 job state pairs; boundary/decision rules applicable có bằng chứng |
| G2 — data | Chênh lệch golden/full-scope case/cell =0; không missing/duplicate/logical-count inflation; I-DATA đạt trên happy/fault/retry/pause/restore |
| G3 — security | Không Critical/High mở cho identity/tenant/worker/data leak; MFA/CSRF/Origin/role/revoke/upload checks có evidence; shared-SaaS nếu chọn phải qua TC-ACL-011 |
| G4 — recovery | F-FAULT đủ; không tự replay Apply khi chưa biết outcome; queue/checkpoint/epoch và active timing giữ qua restart/reload |
| G5 — operations | Cấu hình/network/DB role/resource đúng runtime; HTTPS ngoài trust boundary; backup/restore+keys+RPO/RTO có bằng chứng và owner |
| G7 — capacity | SLO được doanh nghiệp ký và đạt trên workload/hardware đã chốt; soak không leak; overload bounded, dữ liệu đúng sau tải |
| G8 — business replacement | Nếu tuyên bố thay manual toàn dữ liệu: TC-E2E-006 phải đạt full-source oracle; nếu dùng incremental: thêm TC-MKR-012/TC-E2E-007; known-plan 100% hoặc GLOBAL≥30 State chưa đủ |
| G9 — release identity | Bộ deploy đúng source/image/bundle/migration/config đã test; CI và production smoke có bằng chứng; rollback được review |
| G10 — sign-off | QA lead, Product, Backend/RPA, DBA/DevOps và AppSec ký phần mình. P1 chưa đạt cần quyết định ngoại lệ có owner/hạn; P0/GAP trong scope không được đổi thành PASS |

**Trạng thái tại lúc bàn giao tài liệu:** đã lập và kiểm tra tính nhất quán của test design; **chưa có run report nên chưa gate nào được công việc này chứng nhận đạt**. Các test/snapshot pass ở lần làm việc trước không tự thay thế evidence của release/source hiện tại.

## 14. Bảo trì bộ test

Mỗi thay đổi API/model/schema/filter/DOM/role/deployment phải cập nhật R-TRACE, A-API/A-SOCKET, dữ liệu oracle và case liên quan; bổ sung regression cho defect thực tế. Khi source/digest đổi, đánh giá lại impact rồi chọn regression phù hợp; không chạy lại mọi suite nếu thay đổi không ảnh hưởng và bằng chứng vẫn hợp lệ. Chỉ ký phiên bản mới sau review coverage và các policy BL còn mở.

Tài liệu nguồn hỗ trợ: [API reference](api-reference.md), [system status](system-status.md), [run schedules](run-schedules.md), [batch recovery](batch-error-recovery.md), [database enterprise](database-enterprise.md), [SQL UI Health](ui-health-sql.md), [deployment](deployment.md). Source snapshot và quyết định baseline ở mục1 được ưu tiên khi tài liệu cũ mâu thuẫn; khác biệt phải được ghi issue và chốt, không âm thầm bỏ test.

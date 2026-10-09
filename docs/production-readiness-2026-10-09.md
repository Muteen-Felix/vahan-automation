# VAHAN — phần còn thiếu để bàn giao production cho nhiều doanh nghiệp

Ngày review: 09/10/2026. Checkout được kiểm tra: branch `feat/filter`, HEAD `652f2e2`. Đây là backlog để chủ sản phẩm chủ động phân công và nghiệm thu; không phải chứng nhận hệ thống đã đạt production.

**Kết luận:** ứng dụng đã có nền tảng SQL, lịch chạy, retry, báo cáo và bộ kiểm thử. Chưa đủ căn cứ bàn giao một dịch vụ production hoàn chỉnh: runtime chính chưa áp dụng SOC, còn lỗi triển khai/cách ly tenant, chưa có recovery ngoài host/PITR, thiếu bằng chứng vận hành dưới tải và nghiệm thu nghiệp vụ trên release cuối.

## 1. Điều đã kiểm tra trực tiếp

| Nội dung | Kết quả quan sát | Ý nghĩa |
| --- | --- | --- |
| Stack chính | API/Web/10 runner chạy `vahan-db-capacity/*:20261008`; DB `postgres:17.7-bookworm`; các container báo healthy | Bản SOC trong checkout chưa phải bản chạy thực tế |
| Migration | `0013_database_capacity` | Chưa có các bảng `deployment_identity`, `user_mfa`, `soc_outbox` trên DB chính |
| Công việc đang chạy | 0 job chưa kết thúc tại thời điểm đọc | Chỉ là snapshot; không thay cho drain kiểm tra lại lúc deploy |
| Database | 5.366.574.227 byte, khoảng 5 GiB | Cần dự báo tăng trưởng và lưu giữ, không chỉ tối ưu query |
| PostgreSQL recovery | `archive_mode=off`, `wal_level=replica`, 0 replication connection | Chưa có WAL archive/PITR hay standby đang kết nối |
| Runtime DB role | `vahan_app` không superuser/CREATEDB/CREATEROLE/REPLICATION/BYPASSRLS | Least privilege đã có một phần; không suy ra MFA/SOC đã triển khai |
| Container API/Web/runner đại diện | `memoryBytes=0`, `nanoCPUs=0`, rootfs không readonly; Web không cấu hình user riêng | Hardening/giới hạn tài nguyên ở Compose mới chưa có trên runtime chính |
| Docker host | 8 CPU, 16.748.113.920 byte RAM được cấp | Chưa thể cam kết nhiều tenant, mỗi tenant 10 worker, chỉ bằng cấu hình hiện tại |
| SQL statistics | `stored_files` thực tế 75.588 dòng; `n_live_tup=43`; `last_analyze`/`last_autoanalyze` null | Thống kê hiện lệch lớn; endpoint capacity đang trả số ước lượng, không dùng làm số liệu đối soát |
| Tenant provisioning | CLI bình thường với tenant `automation` và port riêng vẫn tạo project `vahan-automation` | Xác nhận collision với project legacy; phải sửa trước khi cấp khách hàng |
| Unit SOC | Chạy lại 9/9 pass | Không bao phủ hết lỗi production đã phát hiện |
| Tài liệu | README thiếu 2 file được liên kết, mô tả backup cũ và lệnh nâng cấp đi thẳng qua Compose | Có nguy cơ vận hành sai dù mã nguồn đã có launcher mới |

Nguồn: kiểm tra chỉ đọc Docker/SQL, mã nguồn và probe temp. File [production-readiness-evidence-2026-10-09.json](production-readiness-evidence-2026-10-09.json) lưu snapshot đã loại bỏ secret. Các kết quả integration/browser/restore/CVE trước đây nằm trong [hồ sơ SOC](security/SOC-deployment-evidence.json); không chạy lại toàn bộ trong lần review này. Không chạy crawl, fault hoặc tải lên VAHAN thật.

## 2. Cách dùng backlog

- **P1:** chặn bàn giao phạm vi liên quan; sửa/kiểm chứng trước khi mở dịch vụ nhiều doanh nghiệp hoặc cam kết SLA đó.
- **P2:** cần cho vận hành doanh nghiệp; trường hợp chưa làm phải có giới hạn sản phẩm, người chịu trách nhiệm và ngày xử lý rõ ràng.
- **P3:** hoàn thiện trải nghiệm hoặc tính năng bổ sung; không tự động chặn toàn bộ sản phẩm.
- **Lỗi xác nhận:** đã thấy luồng mã và có probe cụ thể. **Thiếu triển khai:** có source nhưng chưa có runtime. **Thiếu bằng chứng:** chưa được chứng minh, không mặc định kết luận chức năng hỏng.
- Chỉ đóng một mục khi có commit/release, môi trường, dữ liệu test, expected/actual, log hoặc artifact và người nghiệm thu. Thay `Chưa` bằng `Đạt` sau kiểm chứng; không đánh dấu hoàn thành từ việc đọc source.

## 3. Backlog sửa mã và đưa đúng release vào runtime

| ID | Ưu tiên / hiện trạng | Việc cần sửa | Vị trí / người phụ trách gợi ý | Điều kiện đóng |
| --- | --- | --- | --- | --- |
| PR-01 | P1 · lỗi xác nhận | Chặn tenant/project/volume collision, gồm tên `automation`; xác minh ownership trước drain/backup/stop/up | `scripts/security_setup.py:41`, `scripts/provision-tenant.py:26`, `scripts/run-docker.py:43` · Backend/DevOps | Tenant A/B dùng DB/key/volume riêng; cấu hình trùng bị từ chối trước mọi mutation; stack A không bị ảnh hưởng khi deploy B |
| PR-02 | P1 · lỗi xác nhận | Đánh dấu mutation trước stop; không mở queue khi stop thất bại một phần; có đường phục hồi gate | `scripts/run-docker.py:62` · DevOps | Fault injection stop từng service/lỗi timeout giữ gate đóng; chỉ resume sau health/worker kiểm chứng |
| PR-03 | P2 · lỗi xác nhận | Tạo schema SQLite trước watchdog/server, không nuốt lỗi watchdog âm thầm | `docker/soc/collector.py:124` · Backend/SOC | Collector volume mới, chưa có event vẫn cảnh báo đúng khi API/backup mất |
| PR-04 | P2 · lỗi xác nhận | Tách readiness/liveness collector, kiểm tra storage bền vững và watchdog | `docker/soc/collector.py:82`, `compose.yaml:285` · Backend/SOC | Storage không ghi được, DB hỏng hoặc watchdog chết được phản ánh; `/health` hiện tại không được coi là bằng chứng SOC còn lưu log |
| PR-05 | P2 · lỗi xác nhận | Xác thực release bundle bằng public key được pin; đối chiếu image ID; giới hạn override chỉ chứa image | `scripts/run-docker.py:44`, `scripts/release-provenance.py:44` · DevOps/AppSec | Bundle thiếu/sai chữ ký, image mismatch hoặc override thêm mount/privilege bị từ chối trước mutation |
| PR-06 | P3 · lỗi xác nhận | Chỉ nhận ASCII cho TOTP; xử lý mã recovery riêng, input Unicode không gây 500 | `app/mfa.py:82`, `app/api/auth.py:22` · Backend | OTP sai/Unicode được từ chối có kiểm soát; TOTP và recovery hợp lệ còn hoạt động; không bypass/replay |
| PR-07 | P1 · thiếu triển khai | Sau PR-01/02/05, diễn tập và triển khai đúng bộ API/Web/runner/DB/SOC/backup/documents; kiểm tra migration merge và giữ nguyên dữ liệu | `compose.yaml`, launcher, migrations · DevOps/DBA | Runtime có đúng tenant identity/MFA/outbox và digest; admin thật enroll MFA; cookie/CSRF/worker binding/parser/resource limit được kiểm tra trên bản đã deploy; dữ liệu trước/sau khớp |
| PR-08 | P1 khi phục vụ ngoài local · chưa kết nối | Chọn ingress HTTPS, cert renewal, host/origin và cookie Secure; làm rõ trust proxy/IP rate limit | `docker/nginx.conf`, `app/deployment_security.py`, `app/main.py` · DevOps/AppSec | Truy cập HTTPS đúng host; origin/host sai bị chặn; secure cookie/CSRF và IP sau proxy đúng; cert hết hạn có cảnh báo. Giữ loopback cho mô hình local |
| PR-09 | P2 · thiếu quy trình | Hoàn thiện lost MFA, reissue recovery, rotate MFA/browser/signing/DB/worker key, offboarding và break-glass | `app/mfa.py`, `app/api/auth.py`, `app/api/data.py` · Backend/AppSec | Có recovery cần xác minh danh tính và audit; không tắt MFA công khai; rotate có thể giải mã/thu hồi đúng; disabled/demoted user mất quyền HTTP/socket và lịch tuân thủ policy |
| PR-10 | P1 · thiếu nghiệm thu bảo mật release cuối | Triage advisory còn lại theo package/code path; review toàn bộ HTTP/socket/worker/file boundary và tenant A/B; ghi exception có thời hạn | Lockfiles, scans, auth/realtime/API · AppSec/QA | Không còn lỗi P1 chưa xử lý; High/Critical còn lại có owner, lý do, biện pháp, hạn xử lý; scanner `--ignore-unfixed` không được dùng làm chứng nhận không có lỗ hổng |

Chi tiết sáu lỗi PR-01…06: [SOC-review-2026-10-09.md](security/SOC-review-2026-10-09.md). Mức ưu tiên backlog không thay cho mức severity của báo cáo security.

## 4. Backlog vận hành, dữ liệu và khả năng phục hồi

| ID | Ưu tiên / hiện trạng | Việc cần làm | Vị trí / người phụ trách gợi ý | Điều kiện đóng |
| --- | --- | --- | --- | --- |
| PR-11 | P1 cho cam kết phục hồi mất host · local mới có bằng chứng một phần | Lưu backup mã hóa và khóa ở failure domain riêng; diễn tập restore toàn stack trên host/volume mới | `scripts/backup_security.py`, `docker/backup/daemon.py` · DBA/DevOps | Khôi phục DB, config, tenant, quyền, state mã hóa và representative reports; đo RPO/RTO; không chỉ đếm row. Offsite chưa nối theo lựa chọn trước của chủ sản phẩm |
| PR-12 | P1 nếu RPO yêu cầu nhỏ hơn khoảng cách snapshot · archive đang off | Bổ sung base backup + WAL archive/PITR, retention và kiểm tra chuỗi WAL | PostgreSQL/backup infrastructure · DBA | Restore đến timestamp/transaction kiểm chứng được trên môi trường DR; mất WAL bị phát hiện; không coi logical `pg_dump` là PITR |
| PR-13 | P2, bắt buộc theo SLA availability · một host/primary | Chọn SLA phù hợp single host hoặc triển khai standby/failover, host replacement và phục hồi API/worker | Compose, DB, runtime architecture · DevOps/DBA | Failover/drill có số đo downtime/data loss; ai thực hiện và khi nào rõ; không bán HA chỉ từ `restart: unless-stopped` |
| PR-14 | P2 · thiếu monitoring theo thời gian | Thu metrics API latency/error/503, pool/lock, DB/WAL/disk, worker heartbeat, queue age, backup age và outbox backlog; có nơi nhận cảnh báo và owner | `app/api/health.py`, `app/api/soc_status.py`, collector · DevOps/SOC | Một lỗi tổng hợp trên stage tạo cảnh báo đến nơi operator thực sự theo dõi, có acknowledge/escalate/resolve; cảnh báo vẫn hoạt động khi API/host chết |
| PR-15 | P2 · thiếu retention tổng thể | Đặt thời hạn và job archive có kiểm soát cho jobs/events/artifacts/audit/outbox/SOC JSONL/SQLite; tránh growth không giới hạn | Schema, `app/soc.py`, collector, stored files · DBA/SOC | Dự báo dung lượng 30/90/365 ngày; archive có checksum/restore; chỉ maintenance role được prune; bảo toàn audit/retention yêu cầu; không tự xóa dữ liệu lịch sử |
| PR-16 | P2 · code còn đường chờ không có deadline tổng | Thử và xử lý backup bị lock/treo/disk đầy; timeout tổng và cleanup process; bảo đảm retention không bị kẹt sau snapshot lỗi | `scripts/backup_security.py:123`, `docker/backup/daemon.py:46,66,85` · DBA/Backend | Fault trên stage không giữ pool updating vô hạn; child/snapshot transaction được giải phóng; backup cũ còn dùng được; không chỉ có check free space 512 MiB |
| PR-17 | P2 · thống kê live lệch xác nhận | Kiểm tra ANALYZE/autovacuum sau migration/restore, thống kê hot tables và query plans | PostgreSQL, `app/api/health.py` · DBA | Sau maintenance có thống kê phù hợp; endpoint ghi rõ estimated/actual; query plan và latency được đo. Không thực hiện `VACUUM FULL` tùy tiện |
| PR-18 | P1 cho cam kết công suất · chưa thử tải production | Chốt tenants/workers/users/data volume; load/spike/soak fixture; áp dụng RAM/CPU/PID/time/body limits vào runtime, admission khi quá tải | Compose, DB pressure, UI/API/runner · QA/DevOps | Đạt workload/SLO đã chốt trong ít nhất một soak có recovery sau spike; không OOM, không mất/trùng report; chặn/export trả lỗi rõ. Idle snapshot không là benchmark |
| PR-19 | P2 · vận hành tenant mới có CLI | Inventory tenant/project/ports/keys/backup/digests; quota worker/job/export/storage và onboarding/suspend/retire/restore | Tenant provisioner, worker pool, operations · Backend/DevOps | Tenant noisy không làm tenant khác mất SLA; provision không collision; retire không xóa tenant khác; quyết định managed service hay instance bàn giao riêng được ghi rõ |
| PR-20 | P2 khi cần nhiều API replica · chưa hỗ trợ end-to-end | Thiết kế shared socket routing/adapter và recovery ownership/fencing trước khi tăng API process/replica | `app/realtime/server.py:5`, `app/main.py:32`, `repositories/postgres.py:504` · Backend | Replica B startup không fail job/disconnect runner của A; event/socket tới đúng người; rolling update và leader/reconnect được kiểm tra. SQL scheduler lock hiện có chưa đủ cho toàn hệ thống |

PITR cần base backup vật lý và chuỗi WAL; `pg_dump` không dùng làm nền cho WAL replay. Tham chiếu [PostgreSQL 17: Continuous Archiving and PITR](https://www.postgresql.org/docs/17/continuous-archiving.html). HA/PITR không bắt buộc cho mọi sản phẩm local; mức bắt buộc phụ thuộc SLA/RPO/RTO đã bán cho khách hàng.

## 5. Backlog nghiệm thu nghiệp vụ và trải nghiệm sản phẩm

| ID | Ưu tiên / hiện trạng | Việc cần làm | Vị trí / người phụ trách gợi ý | Điều kiện đóng |
| --- | --- | --- | --- | --- |
| PR-21 | P1 · thiếu UAT release cuối | Chạy luồng profile → all-worker UI Health → schedule → queue → workbook → SQL → Excel download, thêm pause/resume/retry/delete/restore/logout | [Bộ test cases](system-test-cases.md), scheduler/queue/UI · QA/Product | Có run report trên đúng source/images/schema/config cuối; expected cases độc lập bằng done+no-data+failed+cancelled+pending; workbook mở được và đúng phạm vi. Live portal chỉ dùng mẫu được phép |
| PR-22 | P1 · cần nghiệm thu failure matrix | Mô phỏng mất mạng/DB/worker, API restart, ACK mất sau SQL commit, client đóng/reload, scheduler qua ngày, pool overload và UI drift | Queue/scheduler/runner/realtime · QA/Backend | Không mất case, không replay Apply mù, retry không vượt chính sách; pause thủ công không tự resume; NO_DATA khác timeout/lỗi; completed chỉ sau commit |
| PR-23 | P1 cho cam kết dữ liệu chính xác · cần chốt policy | Chốt snapshot/refresh/conflict, phạm vi State/RTO/Maker/năm/tháng, null/zero, case coverage và provenance; đối soát fixture t0/t1 | `repositories/annual_reports.py:172`, `maker_updates.py`, coverage/export · Product/QA/Backend | Chứng minh không sai scope/thiếu worksheet/cắt dòng; dữ liệu thay đổi xử lý theo policy công bố; conflict không bị che bởi “Completed”. Source có cả fill-missing và refresh, không suy ra mọi luồng đều overwrite |
| PR-24 | P3 · thiếu UI xác nhận từ source | Hoàn thiện ETA/finish time với no sample/pause/resume/reload/mất worker; giải thích tốc độ cho operator | `RunScheduleProgress.tsx`, timing hooks · Frontend/QA | Render đúng remaining/finish khi đủ mẫu; không hiển thị ETA giả khi tốc độ 0; có kiểm chứng run. Hiện component chỉ render progress/status/cases per minute |
| PR-25 | P2 nếu export kết quả lọc thuộc phạm vi bán · source UI/API lệch | Quyết định hỗ trợ export State/RTO search rồi nối UI với API, hoặc sửa mô tả sản phẩm | `AnnualReports.tsx:74,105`, `api/annual_reports.py:134`, README:63 · Product/Frontend | Workbook lấy mọi trang đúng filter/search; clear search và export-all có xác nhận riêng; hoặc tài liệu ghi rõ chưa cung cấp. UI hiện ẩn nút khi có search trong khi backend hỗ trợ filter |
| PR-26 | P2 nếu Maker Update là tính năng cam kết · mới một phần | Hoàn thiện hoặc feature-gate chuỗi GLOBAL→DISCOVER→REFRESH và điều phối/retry/restart/coverage | `api/maker_updates.py`, `repositories/maker_updates.py`, scheduler/UI · Backend/Product | Một delta fixture chạy hết chuỗi, cập nhật đúng và resume được; không giới thiệu API GET/history hiện tại là orchestration đã hoàn tất |
| PR-27 | P2 · cần nghiệm thu trạng thái ngoại lệ | Chốt quy trình khi portal yêu cầu validation/login hoặc không hỗ trợ tiếp tục: trạng thái, timeout, thao tác operator và recovery | Runner lifecycle, schedule status, UI diagnostics · QA/Product | Không kẹt vô hạn hoặc báo success giả; operator biết case nào cần xử lý và tiếp tục đúng job; không gửi lại case đã commit |

PR-24/25/26 không phải điều kiện chung cho mọi sản phẩm production. Nếu không nằm trong phiên bản bán, phải feature-gate và sửa tài liệu; nếu đã cam kết thì phải nghiệm thu trước bàn giao.

## 6. Backlog release, tài liệu và trách nhiệm vận hành

| ID | Ưu tiên / hiện trạng | Việc cần làm | Vị trí / người phụ trách gợi ý | Điều kiện đóng |
| --- | --- | --- | --- | --- |
| PR-28 | P1 · có workflow, chưa chứng minh hosted run cho release này | Chạy CI bắt buộc, build/test kiến trúc host đích, lưu reports/SBOM/scans/provenance và phát hành immutable bundle | `.github/workflows/security.yml`, `platform.yml`, release scripts · DevOps/QA | Hosted run link gắn commit/digest; registry/bundle có artifact kiểm chứng; production dùng đúng digest. Một build M1 hoặc workflow file không chứng minh amd64/Windows/Ubuntu đã pass |
| PR-29 | P1 · cần rehearsal | Thử upgrade, migration interruption, rollback compatible code, health failure và khởi động host sạch; cấm bypass drain qua hướng dẫn deploy | Launcher/migrations/Compose · DevOps/DBA | Upgrade giữ dữ liệu/queue/manual pause; rollback giữ report mới; không restore snapshot cũ đè dữ liệu mới; runbook xác định ranh giới trước/sau migration |
| PR-30 | P2 · mâu thuẫn xác nhận | Đồng bộ README/API/deployment/SOC docs theo bản phát hành; sửa link thiếu, backup location, `/docs` production và mô tả scheduler | README:10,14,63,93,95; `docs/` · Product/Tech writer | Người khác cài/upgrade/backup/restore theo tài liệu trên môi trường sạch; mọi link local tồn tại; docs phân biệt runtime với source và thông số giới hạn |
| PR-31 | P1 cho nghiệm thu · thiếu yêu cầu định lượng | Chốt số tenant/workers/users, support matrix, uptime, latency, tốc độ/cửa sổ hoàn thành, data freshness, RPO/RTO và cửa sổ bảo trì | Product/SRE/QA | Requirement sheet có giá trị và phương pháp đo; release đạt hoặc có exception được chủ sản phẩm chấp nhận. Không tự lấy mẫu idle hiện tại làm capacity cam kết |
| PR-32 | P2 · thiếu bằng chứng tổ chức vận hành | Chỉ định chủ incident/security/DB/release, SOP severity/escalation, support/ticket và maintenance/key rotation | SOC/DevOps/Product | Drill sự cố đi qua detect→triage→acknowledge→recover→postmortem; người trực biết xem metrics/log/backup. Collector ghi JSONL chưa đồng nghĩa có SOC trực 24/7 |

Chuỗi cung ứng nên sinh provenance/SBOM ngay lúc build và kiểm tra lúc deploy; xem [Docker: SBOM and provenance with GitHub Actions](https://docs.docker.com/build/ci/github-actions/attestations/). Dùng [OWASP ASVS 5.0](https://owasp.org/projects/asvs) làm cơ sở truy vết kiểm chứng bảo mật; không tuyên bố đạt ASVS chỉ vì đã có scan hoặc checklist.

## 7. Trình tự để chủ sản phẩm chủ động triển khai

| Đợt | Đầu việc | Đầu ra phải nhìn thấy | Điều kiện sang đợt tiếp |
| --- | --- | --- | --- |
| 1 — khóa yêu cầu và sửa blocker | PR-31, PR-01/02/03/04/05/06, policy tenant/data | Requirement sheet, fix commits, regression probes, release candidate | Không còn collision tenant/gate lỗi; collector và release verification có kiểm thử âm |
| 2 — staging đúng release | PR-07 rehearsal, PR-08 theo access model, PR-09/10/21/22/23/28/29 | Tenant A/B, run report, security triage, workbook đối soát, deployed digests | Bản staged dùng đúng bundle; core flow và negative tests đạt, không chéo dữ liệu |
| 3 — chịu lỗi và vận hành | PR-11…20, PR-32 theo SLA; load/soak/recovery drills | RPO/RTO đo được, alerts có owner, capacity/retention report, restore drill | Đạt ngưỡng đã chốt; giới hạn single host/HA được mô tả trung thực |
| 4 — bàn giao | PR-24…27 theo scope, PR-30, deploy PR-07 thật và post-deploy smoke | Tài liệu nhất quán, UAT sign-off, manifest/digest/schema, backup/rollback/support | Runtime production đúng release được nghiệm thu; mọi exception còn lại có owner và hạn xử lý |

Không đưa SLA HA vào bán trước khi PR-13/20 được đáp ứng hoặc có thiết kế khác được kiểm chứng. Không cần tự chuyển sang Kubernetes/Redis/pooled multi-tenant DB nếu mô hình dedicated stack và công suất đã chọn đáp ứng SLA; chọn công nghệ theo gap đã đo.

## 8. Checklist chốt bàn giao

- [ ] Release/source/config/schema/images được xác định, có CI và chữ ký được kiểm tra lúc deploy.
- [ ] Tenant A/B độc lập; role/MFA/cookie/CSRF/worker/file boundary đạt trên runtime cuối.
- [ ] Dữ liệu và workbook khớp oracle; no-data/lỗi/conflict/thiếu case được phân biệt và truy vết.
- [ ] Queue/scheduler/retry/pause/resume/restart đạt cả happy path và failure matrix.
- [ ] Tải/soak đạt workload/SLO; overload không làm mất dữ liệu hoặc làm tenant khác mất SLA.
- [ ] Backup/keys/restore và RPO/RTO được đo; PITR/HA đạt nếu nằm trong cam kết.
- [ ] Metrics/alerts/support/runbook có người chịu trách nhiệm và drill thành công.
- [ ] Tài liệu và giới hạn sản phẩm đúng bản phát hành; P1 đóng, P2 còn lại có quyết định cụ thể.

Ma trận kiểm thử chi tiết đã có ở [system-test-cases.md](system-test-cases.md). Tài liệu đó ghi rõ chưa chứng nhận gate nào đạt từ riêng công việc viết test design; cần run report để đóng từng gate.

**Phạm vi lần review:** chỉ đọc runtime, SQL và source; probe bằng dữ liệu tạm; tạo báo cáo/evidence. Không sửa ứng dụng, ANALYZE/prune dữ liệu, chạy tải, thay secret hay deploy/restart stack chính. Lần deploy SOC trước bị automatic approval review chặn vì chưa có chấp thuận cụ thể cho drain/backup/restart và gián đoạn; báo cáo này không thực hiện lại hành động bị chặn.

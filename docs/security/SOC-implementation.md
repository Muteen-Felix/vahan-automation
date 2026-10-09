# SOC và bảo mật VAHAN — bản triển khai local

Công việc bắt đầu ngày 08/10/2026 và tiếp tục ngày 09/10/2026. Người dùng chọn dịch vụ cho nhiều doanh nghiệp và chưa cần kết nối tên miền, SIEM hoặc nơi lưu backup bên ngoài. Tài liệu này ghi nhận việc thực hiện; báo cáo đánh giá ngày 08/10 là snapshot trước remediation.

**Trạng thái bàn giao:** mã nguồn/image SOC đã được kiểm thử trên stack riêng. Stack chính chưa được cập nhật SOC: bộ duyệt quyền tự động từ chối lệnh drain/backup/restart và yêu cầu chấp thuận rõ lần triển khai có gián đoạn này. Controller giữ Docker socket đã được gỡ từ trước. Xem [hồ sơ nghiệm thu](SOC-deployment-evidence.json) và manifest có chữ ký trong `diagnostics/soc/release/`.

## Kiểm soát đã triển khai trong mã nguồn

| Hạng mục | Hành vi hiện tại |
| --- | --- |
| Cách ly doanh nghiệp | Một Compose project/database/volume/mạng/bộ khóa riêng mỗi tenant; token mang tenant claim; database lưu tenant identity bất biến đối với runtime. Không đưa nhiều khách hàng vào một database chung |
| Quyền quản trị | Role `admin` chỉ quản trị stack/database của doanh nghiệp đó. Quản trị platform là thao tác vận hành host; không cấp quyền platform bằng role admin của khách hàng |
| Worker | Mười credential khác nhau; server ràng buộc credential với worker ID, kiểm tra job được giao và state path. Credential dùng chung cũ không được production chấp nhận |
| Phiên UI | Cookie HttpOnly/SameSite=Strict, CSRF gắn với session cho mọi mutation; không trả bearer token cho browser, không lưu credential trong localStorage. Chỉ lưu marker giao diện không có quyền xác thực |
| MFA | Admin bắt buộc TOTP, seed mã hóa, OTP không được dùng lại; 10 recovery code dùng một lần, lưu hash. Challenge enrollment hết hạn 5 phút và bị vô hiệu khi password/role/active thay đổi |
| Chống lạm dụng đăng nhập | Counter PostgreSQL atomic theo account/IP/toàn tenant, KDF concurrency giới hạn, HTTP 429 và Retry-After. Counter tồn tại qua restart |
| Database | Runtime `vahan_app` DML, migrator/backup riêng; không superuser/CREATEDB/CREATEROLE/REPLICATION/BYPASSRLS hoặc membership đặc quyền. Runtime không sửa/xóa audit, tenant identity hay version migration |
| SOC | Event có tenant/request ID/source IP, thông tin nhạy cảm được loại bỏ; outbox PostgreSQL chuyển HMAC event tới collector riêng. Volume collector không mount vào API/worker; không có API xóa log |
| Cảnh báo | Nhiều login lỗi, rate limit, quản trị danh tính, worker credential sai, export bất thường, backup lỗi/cũ, heartbeat API mất. Cảnh báo ở JSONL và console collector; không tự gửi email/Slack |
| File và tài nguyên | Parser XLSX/CSV tách container không có credential ứng dụng, timeout/CPU/RAM/PID limit; body/upload/expanded ZIP/row/output bị giới hạn. Export streaming có quota và concurrency gate |
| Container | Non-root cho API/web/runner/SOC/backup; rootfs readonly khi phù hợp, capability tối thiểu, no-new-privileges và seccomp. Chromium sandbox giữ bật; bổ sung syscall chroot trong user namespace thay vì cấp SYS_ADMIN |
| Mạng và cổng | Database/processing/audit là mạng nội bộ riêng. Worker không nối vào DB. Web/API publish loopback. Origin và Host allowlist; truy cập production từ host ngoài localhost yêu cầu HTTPS và cookie Secure |
| Backup | Age encryption; private identity nằm ngoài archive. Backup đầy đủ chứa DB và cấu hình được mã hóa, dùng snapshot thống nhất, kiểm tra SHA-256/decryption và có chế độ restore test. Daemon hourly chỉ có DB role readonly và public recipient, dung lượng managed volume được giới hạn |
| Chuỗi cung ứng | Python lockfile có hash, npm lockfile đã vá; image base được cập nhật; CI security gate. Manifest local ký Ed25519 và override Compose bằng image ID bất biến, SBOM/CVE scan lưu cùng hồ sơ release |

## Sử dụng local

Dashboard vẫn ở `http://127.0.0.1:5173`. Khi triển khai version SOC, các phiên cũ bị thu hồi. Người dùng admin đăng nhập bằng mật khẩu đang có, nhập setup key vào ứng dụng authenticator, xác nhận OTP rồi lưu recovery code. Công việc này không tự đăng ký authenticator cho tài khoản thật.

Sau khi đăng nhập, Settings có mục **Security operations**: tenant, MFA policy, worker identity, số event chờ và thời điểm delivery thực tế. Collector lưu trong volume `<project>_soc_data`; backup tự động trong `<project>_backup_data`.

```bash
docker compose --env-file .docker.env logs --tail 100 soc
docker compose --env-file .docker.env logs --tail 30 backup
python3 scripts/security-audit.py --output /tmp/vahan-security.json
```

### Cấp một doanh nghiệp mới

```bash
python3 scripts/provision-tenant.py --tenant company-a --api-port 8101 --web-port 5201
```

Credential nằm trong file được bảo vệ `tenants/company-a/.env`. Script không in password/key. Dùng `--up` để khởi động khi đã bố trí đủ CPU/RAM/đĩa cho host. Không tái sử dụng project/volume hoặc copy credential giữa doanh nghiệp. Với yêu cầu cách ly host mạnh hơn, chạy mỗi stack trên VM/host riêng; container riêng trên cùng daemon không bảo vệ khỏi việc daemon/host bị chiếm.

### Backup và khôi phục thử

Cần `age`/`age-keygen` trên host cho backup đầy đủ. Cài theo [hướng dẫn chính thức của age](https://github.com/FiloSottile/age): macOS dùng Homebrew, Ubuntu dùng apt, Windows dùng winget. Khóa riêng mặc định trong `.secrets/<tenant>-backup.agekey`, mode 0600/ACL owner-only. Không đưa khóa riêng vào archive hoặc Git.

```bash
python3 scripts/backup-docker.py
python3 scripts/backup-docker.py --verify /path/to/backup.age --restore-test
```

Restore test chỉ tạo PostgreSQL tạm, không publish port, so sánh counts rồi xóa container/volume kiểm thử đó. Nó không restore đè dữ liệu đang chạy. Daemon chỉ tạo `.dump.age` và manifest; khôi phục cần cấu hình/khóa được quản lý riêng hoặc archive đầy đủ từ CLI.

Backup plaintext trước remediation được giữ nguyên, tiếp tục hạn chế quyền đọc; không tự xóa dữ liệu cũ. Offsite/immutable storage bên ngoài chưa kết nối theo lựa chọn của người dùng. Nếu host mất cả backup và private key, bản local không đáp ứng disaster recovery cho mất host.

### Triển khai an toàn

Launcher build trước, dừng nhận việc mới bằng gate pool SQL, chờ job và lease hiện tại hoàn tất, tạo backup rồi mới stop/recreate dịch vụ. Khi không drain được trong thời gian giới hạn, launcher không restart và trả pool về ready. Nếu lỗi xảy ra sau khi đã bắt đầu thay đổi runtime, phải kiểm tra trạng thái và phục hồi có kiểm soát; không tự bật lại queue trên một stack lỗi.

```bash
python3 scripts/run-docker.py --config-only
python3 scripts/run-docker.py --no-build
```

Không dùng `down -v` cho stack khách hàng. Không đổi signing/browser/MFA key tùy tiện: phải có backup khóa, kế hoạch thu hồi session và kiểm tra giải mã state cũ. Nếu thay signing key, recovery code cũ cũng cần được cấp lại theo quy trình quản trị.

## Bằng chứng nghiệm thu

- 14 kiểm tra unit/phân quyền; 8 SOC integration; 8 session integration trên PostgreSQL disposable.
- 10 kiểm tra stack thật ở tenant `soc-validation`: MFA, cookie/CSRF, host/origin, worker state, role DB, audit và parser/outbox.
- Kiểm thử browser thật: MFA enrollment, recovery, HttpOnly, reload, Settings security status và logout nhiều tab.
- Bộ UI platform pass: session, báo cáo, filter, UI Health, navigation, lịch chạy và history.
- Backup đầy đủ đã restore ở PostgreSQL riêng; 47.079 job, 64.638 report row, 2 user và 75.588 stored file khớp snapshot manifest.
- Worker sandbox hoạt động với cap_drop ALL và no-new-privileges; collector đã nhận sự kiện và backup tự động trên stack kiểm thử.

Chi tiết cuối cùng, image ID và trạng thái stack chính được ghi trong `SOC-deployment-evidence.json` sau khi triển khai. Các kiểm tra local không thay thế hosted Windows/Ubuntu CI, penetration test toàn diện hoặc thử tải production.

## Giới hạn còn phải quản lý

Kết quả scanner giữ phân biệt advisory/package instance với exploit đã chứng minh. High/Critical chưa có bản vá cần triage theo code path và vendor; không ghi “hết lỗ hổng” chỉ vì không còn lỗi có bản vá. PostgreSQL vẫn một primary, host vẫn một failure domain. Chưa có HA, SOC trực 24/7, SIEM ngoài host, offsite backup hoặc chứng nhận tuân thủ. Khi cung cấp Internet, cần HTTPS ingress và nghiệm thu hạ tầng/IdP/SLA trước khi mở cổng.
